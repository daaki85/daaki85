"""Dice log: shows the rolls Shattered Lands makes behind the scenes.

How it works:
  * The launcher runs DSUNLOG.EXE, a copy of the game whose rand() and two
    "probe" places (the end of the saving throw and of the AC calculation)
    start with INT instructions (see gamepatch.py).
  * DSCLOG.EXE (see dos/dsclog.asm), loaded before the game, answers those
    interrupts. Its rand() gives the same numbers as the game's but also
    records each call and the caller's stack frames in a ring buffer; the
    probes record the game's final numbers there.
  * attach() finds DSCLOG and the game in DOSBox's memory; lines() reads new
    entries and turns them into text, using what the calling code does with
    each number and the game's own data (names, THAC0, weapons, spell effects).

Everything game-specific here was taken from the GOG release of Shattered
Lands (DSUN.EXE, 611408 bytes).
"""

import random
import re
import struct
import time
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple

from . import bonescale, dust, game, rings, targeting, icons, kalzith, monsters, names, npcitems, pickpocket, ring, scrolling, semyon, shadows, sprites, stealth, tools, vulture
from .game import (CONVENTIONAL_AND_UPPER, CREATURE_ABILITIES, CREATURE_SIDE, CREATURE_THAC0, EFFECT_NAMES,
                   EFFECT_RULES, MATERIAL_TO_HIT, MATERIALS, SAVE_NAMES, STR_DAMAGE, GameData)
from .guestmem import GuestMemory
from .textlog import KIND_MESSAGE, KIND_PORTRAIT, KIND_TEXT, Dialogue, DialogueEntry, TextBuffer
from .tracker import PartyTracker

HDR_SIG = b"DSCLOGvT"
# DSCLOG's header: the in-game turn summaries (see PROBE_TURN in dos/dsclog.asm)
TSR_TURN_SEQ, TSR_REPLY_SEQ, TSR_POPUPS, TSR_MSG_OFF, TSR_ENDED, TSR_HDR_OFF = 138, 140, 142, 144, 146, 20
MSG_SIZE = 900
# the roll an attack needs and the chance of it, in the log's attack line (left out in the game)
TO_HIT_CHANCE = re.compile(r", (?:needs \d+\+|hits on anything but a 1|only a 20 hits) \(\d+%\)"
                           r"| \(\d+% to save\)")  # ... and a save's chance (its "needs 12" stays)
# ... and the party's spell slots, for the game's USE screen (PROBE_USE)
TSR_SLOTS_OFF, SLOTS_SIZE = 148, 96
SLOTS_LINES = 3  # lines of spell slots the USE screen has room for
# ... and what the Look box says about a monster (PROBE_LOOK)
TSR_LOOK_SEQ, TSR_LOOK_REPLY, TSR_LOOK_WHO, TSR_LOOK_OFF, TSR_LOOK_FULL_OFF, TSR_LOOK_ON = 150, 152, 154, 156, 158, 160
LOOK_SIZE, LOOK_FULL_SIZE = 80, 700
# ... and the party's THAC0 and saves as they stand now, for the game's screens (see STATS)
TSR_STATS_OFF, TSR_STATS_STAMP, TSR_STATS_REQ, TSR_STATS_REPLY, STATS_SIZE = 162, 164, 166, 168, 24
STATS_RANGER = 2  # a STATS entry's +17 for a ranger: only move silently and hide in shadows count
BIOS_TIMER = 0x46C
# ... and the rule changes it makes to the game (the Options tab)
TSR_RULES = 170
TSR_MAIN_TICKS = 260  # the map's main loop run (counted)
TSR_PICK_SEQ, TSR_PICK_REPLY, TSR_PICK_OFF, TSR_PICK_ON, PICK_SIZE = 172, 174, 176, 178, 240
TSR_USE_SEQ, TSR_USE_REPLY, TSR_USE_WHO, TSR_USE_TAKEN, TSR_USE_ITEM = 180, 182, 184, 186, 188
TSR_SWAP_ON, TSR_SWAP_SEQ, TSR_SWAP_OFF, SWAP_SIZE, SWAP_TEXT_SIZE = 190, 192, 194, 64, 240
RULE_HELMS, RULE_BOOTS = game.RULE_HELMS, game.RULE_BOOTS
SLOT_KINDS = {"Wizard": "WIZ", "Priest": "PRI"}
RAND_PATCHED = b"\xcd\x60"  # INT 60h at the start of rand() in DSUNLOG.EXE
RAND_IP = 0x822  # rand()'s offset in the game's first code segment
SEED = 0x4122  # DS offset of rand()'s 32-bit seed

TARGET_GLOBAL = 0x494A  # DS word: combatant id of the current attack's target
CHECK_MODS = (0x3971, 4)  # segment (relative to the load segment), offset: ability check modifiers

ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")

# Code right after known rand() calls (the calling code, identified by its bytes)
ATTACK_SITE = bytes.fromhex("660fbfc0666bc01466bb00800000669966f7fb408946fa")
DICE_SITE = bytes.fromhex("660fbfc0660fbf5608660fafc266bb00800000669966f7fb")
CHECK_SITE = bytes.fromhex("660fbfc0666bc01466bb00800000669966f7fb8946fc3d13")
PERCENT_SITE = bytes.fromhex("bb640099f7fb3b56fe")
# The weapon break check after an attack: 0-7, then 0-19; both under the chance (1) breaks it
BREAK_ROLL_1 = bytes.fromhex("660fbfc066c1e00366bb00800000669966f7fb3bc77d")
BREAK_ROLL_2 = bytes.fromhex("660fbfc0666bc01466bb00800000669966f7fb3bc77d")
# Code right after the attack function's call to the dice function
WEAPON_DAMAGE_RETURN = bytes.fromhex("83c4068946fc0bc07f05")
# ... and after the 1d10 for a creature's 1-in-10 special effect on a hit (the thri-kreen
# bite, for one); the caller's arguments are (target, attacker)
SPECIAL_EFFECT_RETURN = bytes.fromhex("83c4043d01007510")
# ... and in the routine that adds up a spell's damage dice
SPELL_DAMAGE_RETURN = bytes.fromhex("83c4045a03d0")
# ... and in the routine that works out a spell's duration (its arguments: spell, caster level);
# the dice are often NdS with S = 1, a fixed number
SPELL_DURATION_RETURN = bytes.fromhex("83c406660fbfc0665a66")
# The routine run whenever an effect uses up a charge (arguments: creature, effect): it rolls
# 2d4 first, and deals it as acid damage only for the acid effect (Acid Arrow, each round)
CHARGE_USED_RETURN = bytes.fromhex("83c4048946fe8b4608")
ACID = 1
# A confused creature's turn (its routine's first argument is the creature): d10, 1 it runs
# off, 2-6 it does nothing, 7-9 it fights for a side picked with a d2 (as a berserk creature
# always does), 10 it acts normally
CONFUSION_ROLL_RETURN = bytes.fromhex("83c4048ad080fa0174da")
RANDOM_SIDE_RETURN = bytes.fromhex("83c4048bde6bdb03ba")
CONFUSION_RESULTS = ((1, "runs off"), (6, "does nothing"), (9, "fights for a side picked at random"),
                     (10, "acts normally"))
# Strength (and the psionic Adrenalin Control): the special handler rolls 1d6 and stores it in
# the effect; while it lasts the game adds it to STR, keeping STR between 3 and 24
STRENGTH_ROLL_RETURN = bytes.fromhex("83c40450660fbf4618")
STR_MOST = 24
MIND_BAR, LOW_RESISTANCE, MIND_BAR_RESISTANCE = 32, 31, 75
# The magic resistance roll made straight from the spell code (arguments: target, spell, level)
RESISTANCE_ROLL_RETURN = bytes.fromhex("83c404508a460a50ff76")
# Dispel Magic, for each effect on the target (the effect id in [BP-2], the dispeller's level
# the handler's argument at +14h): d100 at or under 50 + 5 x (that level - the effect's level)
DISPEL_ROLL_RETURN = bytes.fromhex("83c4045a3bd07c108a46")
# Abjure: d20, which must reach 11 - the caster's level + the target's level; a creature of
# kind 14 (a summoned one) is then sent away (1000 damage)
ABJURE_ROLL_RETURN = bytes.fromhex("83c4045a3bd07e03e968")
ABJURE_KIND = 14
# A summoning spell picking which of its three creatures comes
SUMMON_ROLL_RETURN = bytes.fromhex("83c4043d0100740d3d02")
# What a return address shows when the overlay manager has redirected it (INT 3Fh)
OVERLAY_TRAP = b"\xcd\x3f"
# DSCLOG only records calls whose calling code starts like one of these, so
# bursts of other randomness (animations) don't crowd out the rolls that
# matter: the "rand()*N/32768" rolls (attacks, checks, saves, damage dice)
# and the percentile check. The same list is built into DSCLOG.
SCALED_ROLL = b"\x66\x0f\xbf\xc0"  # movsx eax, ax
FILTERS = tuple(SCALED_ROLL + bytes.fromhex(h) for h in (
    "666bc0", "6669c0", "66c1e0", "660fbf56")) + (PERCENT_SITE[:8],)

# The rolls at the start of each round (the code after each rand() call): initiative
# 20 + 0-9 + DEX + effects for every combatant, then 0-199 to break ties
INITIATIVE_ROLL = bytes.fromhex("660fbfc0666bc00a66bb00800000669966f7fb665057")
INITIATIVE_TIE = bytes.fromhex("660fbfc06669c0c800000066bb00800000669966f7fb8bde")
INITIATIVE_BASE = 20
INITIATIVE_WAIT = 0.3  # seconds after the last initiative roll before the order is shown

# Character creation (the die on the creation screen). Each ability is the best of four
# 4d4 + 4 + the race's adjustment, raised to the class's minimum; the code after the
# ability routine's call to the dice routine, whose arguments are (?, ability, ...,
# classes counted):
CREATION_ABILITY_RETURN = bytes.fromhex("83c40403069a498946fe")
CREATION_ABILITY_TRIES = 4
# Then each class level's hit point die, through the level-up routine (its caller's
# arguments are (sheet, class, level)); called from the creation screen, it returns here:
LEVEL_HP_RETURN = bytes.fromhex("83c4048bc8c45efc268a")
CREATION_HP_CALLER = 0x0232
CREATION_HP_WAIT = 0.3  # seconds after the last hit point roll before the total is shown
# ... and in the handler for spells with rules of their own (its arguments: caster, target, ...,
# spell at +0Eh): code after its dice calls -> what the roll is and what the game adds
SPELL_HANDLER_RETURNS = (
    (bytes.fromhex("83c40440e988"), 1),  # Cure Serious Wounds: 2d8 + 1
    (bytes.fromhex("83c404050300eb"), 3),  # Cure Critical Wounds: 3d8 + 3
    (bytes.fromhex("83c4045057900e"), 0),  # Cure Light Wounds 1d8, Blood Flow 2d6 (healing)
    (bytes.fromhex("83c40450ff7608"), 0),  # Aid 1d8, Vampiric Touch (level / 2)d6, drains
)
# ... and a name picked at random from the game's lists (the code after the dice call)
RANDOM_NAME_RETURNS = (bytes.fromhex("83c40448eb11"), bytes.fromhex("83c4040563008b"),
                       bytes.fromhex("83c40405c700eb"))

KIND_ROLL, KIND_SAVE, KIND_AC = 0, 1, 2
# How much each turn's pop-up in the game says (the Options' turn_popups_level)
POPUP_DETAIL, POPUP_SHORT, POPUP_MINIMAL = "detail", "short", "minimal"
POPUP_LEVELS = (POPUP_MINIMAL, POPUP_SHORT, POPUP_DETAIL)
# a spell's result in the log, for the least of them: "  Slig takes 9 from Fireball, now 9/18 HP"
SPELL_RESULT = re.compile(r"^\s+(.+? (?:takes \d+|regains \d+ HP) from [^,]+)")


def popup_level(settings: dict) -> str:
    """The pop-ups' level as saved (earlier versions had only detail or not)."""
    level = settings.get("turn_popups_level")
    if level in POPUP_LEVELS:
        return level
    return POPUP_DETAIL if settings.get("turn_popups_detail", True) else POPUP_SHORT

THIEF = 17  # class number

EFFECT_INTERVAL = 0.25  # seconds between looks at the active effects
RING_INTERVAL = 3.0  # seconds between looks for the arena's Ring +1
LOAD_SETTLE = 3.0  # seconds after the party changes (a game was loaded) when effects are not news
PENDING_SECONDS = 1.0  # how long dice wait to learn which spell they belong to
SPELL_WINDOW = 15.0  # seconds after a spell's roll in which HP changes are put down to the spell
HIT_WAIT = 3.0  # seconds after a weapon hit's damage roll with no HP lost: the target took none
FIGHT_GAP = 120  # game seconds without a new round after which the fight is over


class DiceLogError(Exception):
    pass


@dataclass
class Entry:
    seq: int
    ip: int
    cs: int
    raw: int
    bp: int
    ss: int
    ds: int
    parent_bp: int
    frame: bytes  # from SS:BP+2 (return address, then arguments)
    parent: bytes  # from SS:parentBP+2
    glob: Tuple[int, int, int, int]
    locals: bytes  # from SS:BP-10h
    code: bytes  # the code right after this call, copied when it ran
    parent_code: bytes  # the code at the caller's own return address
    parent_locals: bytes  # from SS:parentBP-28h
    kind: int  # KIND_ROLL, KIND_SAVE or KIND_AC
    extra: int = 0  # KIND_SAVE: the segment of the game's spell table

    SIZE = 192

    @classmethod
    def parse(cls, data: bytes) -> "Entry":
        head = struct.unpack_from("<8H", data, 0)
        return cls(*head, data[16:48], data[48:80], struct.unpack_from("<4H", data, 80), data[88:104],
                   data[104:128], data[128:144], data[144:184], *struct.unpack_from("<2H", data, 184))

    @staticmethod
    def _word(data: bytes, index: int) -> Optional[int]:
        if 0 <= index <= len(data) - 2:
            return struct.unpack_from("<h", data, index)[0]
        return None

    def arg(self, bp_offset: int) -> Optional[int]:
        """Signed word at [BP+bp_offset] in the caller's frame (2..20h), or None."""
        return self._word(self.frame, bp_offset - 2)

    def parent_arg(self, bp_offset: int) -> Optional[int]:
        """Signed word at [parentBP+bp_offset] (2..20h), or None."""
        return self._word(self.parent, bp_offset - 2)

    def local(self, bp_offset: int) -> Optional[int]:
        """Signed word at [BP+bp_offset] for bp_offset in -10h..-2, or None."""
        return self._word(self.locals, bp_offset + 0x10)

    def local_byte(self, bp_offset: int) -> int:
        return self.locals[bp_offset + 0x10]

    def parent_local(self, bp_offset: int) -> Optional[int]:
        """Signed word at [parentBP+bp_offset] for bp_offset in -28h..-2, or None."""
        return self._word(self.parent_locals, bp_offset + 0x28)


def scaled(raw: int, sides: int) -> int:
    """The game's rand()*N/32768: a number from 0 to N-1."""
    return raw * sides // 0x8000


def hit_chance(need: int) -> int:
    """The chance (percent) of a d20 attack roll reaching `need`: a 20 always hits, a 1 always misses."""
    return 5 * sum(1 for d in range(1, 21) if d == 20 or (d != 1 and d >= need))


def save_chance(needed: int, doubled: bool) -> int:
    """The chance (percent) that a d20 (doubled for some spells) reaches `needed` after the rest
    is added; a natural 20 always saves and a natural 1 always fails."""
    wins = sum(1 for d in range(1, 21) if d == 20 or (d != 1 and (d * 2 if doubled else d) >= needed))
    return wins * 5


def signed(n: int) -> str:
    return f"+{n}" if n >= 0 else f"-{abs(n)}"


def generic_roll(code: bytes, entry: Entry) -> Optional[Tuple[str, int]]:
    """(die, value), e.g. ("d20", 14) or ("0-9", 3), for the common 'rand()*N/32768 (+1)' shapes."""
    if not code.startswith(SCALED_ROLL):
        return None
    rest = code[4:]
    if rest[:3] == b"\x66\x6b\xc0":  # imul eax, eax, imm8
        sides, rest = rest[3], rest[4:]
    elif rest[:3] == b"\x66\x69\xc0":  # imul eax, eax, imm32
        sides, rest = struct.unpack_from("<i", rest, 3)[0], rest[7:]
    elif rest[:3] == b"\x66\xc1\xe0":  # shl eax, n
        sides, rest = 1 << rest[3], rest[4:]
    elif rest[:4] == b"\x66\x0f\xbf\x56" and rest[5:9] == b"\x66\x0f\xaf\xc2":  # N = word [bp+x]
        sides, rest = entry.arg(rest[4]), rest[9:]
    else:
        return None
    if sides is None or sides <= 0 or not rest.startswith(b"\x66\xbb\x00\x80\x00\x00\x66\x99\x66\xf7\xfb"):
        return None
    face = scaled(entry.raw, sides)
    if rest[11:12] == b"\x40":  # inc ax: a 1..N die
        return f"d{sides}", face + 1
    return f"0-{sides - 1}", face


@dataclass
class PendingDice:
    """Dice from the general dice routine, waiting to learn which spell they belong to."""
    text: str  # e.g. "9d6 = [4 + 3 + ...] = 29"
    at: float
    damage: bool = False  # rolled by the spell damage routine
    # a 1d100 whose caller's arguments are (target, spell): the magic resistance check
    # (its caller can't be told by its code: the overlay manager replaces that return address)
    resistance: Optional[Tuple[int, int, int]] = None  # target, spell, roll


class AcDetail(NamedTuple):
    base: int  # from the character sheet
    armour: int  # armour and shields (and spells that stand in for armour)
    dex: int
    other: int  # spells, rings and the rest
    total: int


class DiceLog:
    def __init__(self, guest: GuestMemory, record_everything: bool = False):
        self.guest = guest
        self.record_everything = record_everything  # also rand() calls that aren't rolls (noisy)
        self.tsr_hdr: Optional[int] = None
        self.rand_addr: Optional[int] = None
        self.last_seq: Optional[int] = None
        self.missed = 0
        self.game: Optional[GameData] = None
        self.last_ac: Dict[int, int] = {}  # creature index -> the AC the game last computed for it
        self.ac_detail: Dict[int, AcDetail] = {}  # creature index -> how that AC was made up
        self._dice: Dict[Tuple[int, int, int, int], List[int]] = {}
        self._pending: List[PendingDice] = []
        self._out_cold: Dict[int, bool] = {}  # creature index -> Out Cold when last looked at
        self._psp: Dict[int, int] = {}  # party member -> PSP when last looked at
        self._last_damage: Optional[Tuple[int, int]] = None  # (spell, damage) last rolled
        self._turn: Optional[int] = None  # whose turn it was when last looked at
        self.round_order: List[Tuple[Optional[int], str, int]] = []  # this round: (combatant, name, score)
        self.round_number = 0
        self._acted: set = set()  # combatants whose turn has come this round
        self._reply: Optional[Tuple[int, str]] = None  # the reply being flashed when last looked at
        self.speaker_names: Dict[int, str] = {}  # portrait -> the name the player gave it
        self.learned_speakers: Dict[int, str] = {}  # portrait -> the name worked out from conversations
        self._new_speakers: Dict[int, str] = {}  # learned since take_speakers()
        self._talk: Optional[dict] = None  # the conversation on screen: its portraits and who it's with
        self.popups = False  # in-game turn summaries (set_popups)
        self.popup_level = POPUP_DETAIL  # ... with the dice log's lines, in short, or the results only
        self.monster_info = True  # monsters' defences in the game's Look box (set_monster_info)
        self.arena_ring = True  # put the Ring +1 on the Tied-up Prisoner's body in the arena (ring.py)
        self.pickpockets = True  # P in a conversation picks a pocket (pickpocket.py)
        self.show_gear = True  # the party's map sprites dressed in what they wear (sprites.py)
        self.show_shadows = True  # shadows under the figures on the map (shadows.py)
        self._shadows = shadows.Shadows()
        self.show_dust = True  # dust raised by walkers on sand and dirt (dust.py)
        self._dust = dust.Dust()
        self.ring_mode = rings.ONLY_CHOSEN  # rings in a fight: off, the chosen enemy's, all the enemies' (rings.py)
        self._rings = rings.Rings()
        self.use_targeting = True  # Tab chooses an enemy in a fight, Enter attacks it (targeting.py)
        self._targeting = targeting.Targeting()
        self.scroll_map = True  # the map scrolled with the wheel, turned or pressed and dragged (scrolling.py)
        self.scroll_right = False  # ... and dragged with the right button held
        self._scrolling = scrolling.Scrolling()
        self._wheel: Optional[scrolling.WheelWatch] = None
        self._dresser: Optional[sprites.Dresser] = None
        self._dresser_tried = False
        self.picked: set = set()  # the pockets tried already (each person gets one try)
        # ... and when, by the game's clock: one tried after the game being played was saved is
        # forgotten when that save is loaded (the clock goes back past it)
        self.picked_at: Dict[str, Optional[int]] = {}
        self._picked_changed = False
        self._clock: Optional[int] = None
        self._mended_in: Optional[int] = None  # the area Kalzith's scrolls were last mended in
        self.tools_given: set = set()  # the thieves given thieving tools (tools.py)
        self._tools_session: set = set()  # ... while this runs
        self._swap_seq = 0  # DSCLOG's text swaps seen (the arena ring's search, ring.py)
        self._tools_new: List[str] = []
        self.rules = 0  # RULE_HELMS | RULE_BOOTS: rule changes DSCLOG makes (set_rules)
        self.stealth_roll: Callable[[], int] = lambda: random.randint(1, 100)  # hiding, moving silently
        self._ring_check = 0.0
        self._main_ticks: Optional[int] = None  # DSCLOG's count of the map's main loop, last read
        self._look_seq = 0
        self._turn_seq = 0
        self._turn_attacks: Dict[int, List[dict]] = {}  # creature -> this turn's attacks
        self._turn_log: List[str] = []  # this turn's rolls as the log has them (attacks, spells, saves)
        self._slots_written = b""
        self._stats_written = b""
        self._own_text: set = set()  # summaries shown in the game's window, not to log as dialogue
        self._skip_choice = False
        self._hits: Dict[int, dict] = {}  # creature -> weapon hits not yet seen in its HP: their
        # damage, in order ("hits"), when the last landed ("at"), its HP then ("hp")
        self._tables: Optional[monsters.MonsterTables] = None  # the monster kinds (read once)
        self._round, self._round_time = 0, None  # this fight's round, and the game time it began
        self._save_rolls: Dict[Tuple[int, int], int] = {}  # (SS, save frame BP) -> natural d20
        self._effects: Optional[Counter] = None
        self._party: Optional[bytes] = None
        self._party_changed_at = 0.0
        self._next_effect_check = 0.0
        self._initiative: List[Tuple[int, int]] = []  # this round's (0-9 roll, 0-199 roll) pairs
        self._initiative_roll: Optional[int] = None
        self._initiative_at = 0.0
        self._names: Dict[int, str] = {}  # combatant -> name, for effects that end after a fight
        self._last_attacker = ""
        self._break_first: Optional[int] = None  # the 0-7 roll of a break check in progress
        self._ability_tries: List[int] = []  # character creation: this ability's 4d4 totals so far
        self._ability_of: Optional[int] = None  # ... and which ability they are for
        self._creation_hp: List[Tuple[int, int, int, str]] = []  # (sheet, class, hit points, text)
        self._creation_hp_at = 0.0
        self._creation_con: Optional[int] = None  # the CON just rolled
        self._hp: Dict[int, int] = {}  # creature index -> HP at the last look
        self._spell_until = 0.0  # HP changes before this are a spell's doing
        self._spell_name = ""
        self.tracker: Optional[PartyTracker] = None
        self.text: Optional[TextBuffer] = None
        self.dialogue = Dialogue()
        self._dialogue: List[DialogueEntry] = []

    # ---- attaching ------------------------------------------------------------

    def attach(self) -> str:
        """Find DSCLOG and the game. Returns a status line."""
        low = self.guest.read(0, CONVENTIONAL_AND_UPPER)
        hdr = next((m.start() for m in re.finditer(re.escape(HDR_SIG), low) if m.start() % 16 == 0), None)
        if hdr is None:
            if re.search(rb"DSCLOGv[0-9A-Z]", low):
                raise DiceLogError("An older DSCLOG is loaded. Restart the game with 'Start Game with Dice Log.bat'.")
            raise DiceLogError("DSCLOG is not loaded. Start the game with 'Start Game with Dice Log.bat'.")
        ds = game.find_data_segment(self.guest, low)
        if ds is None:
            raise DiceLogError("Shattered Lands is not running yet.")
        rand_addr = (ds - game.DGROUP) * 16 + RAND_IP
        if low[rand_addr:rand_addr + 2] != RAND_PATCHED:
            raise DiceLogError("The game was started without the dice log. "
                               "Restart it with 'Start Game with Dice Log.bat'.")
        self.tsr_hdr, self.rand_addr = hdr, rand_addr
        self.guest.write(hdr + 22, struct.pack("<5H", SEED, TARGET_GLOBAL, 0, 0, 0))
        self.game = GameData(self.guest, ds)
        self._scrolling.forget()  # (a DSCLOG of its own: told again)
        self._dust = dust.Dust()
        self._rings = rings.Rings()
        self._targeting.forget()
        if self._wheel is None:
            proc = getattr(self.guest, "proc", None)
            self._wheel = scrolling.WheelWatch(lambda: getattr(proc, "pid", None), self._scrolling.add)
            self._wheel.start()
        self.tracker = PartyTracker(self.game)
        self.text = TextBuffer(self.guest.read, hdr)
        self.set_record_everything(self.record_everything)
        self.set_popups(self.popups)
        self.set_monster_info(self.monster_info)
        self.set_rules(self.rules)
        self.set_pickpockets(self.pickpockets)
        self._turn_seq = struct.unpack("<H", self.guest.read(hdr + TSR_TURN_SEQ, 2))[0]
        self._look_seq = struct.unpack("<H", self.guest.read(hdr + TSR_LOOK_SEQ, 2))[0]
        self._swap_seq = struct.unpack("<H", self.guest.read(hdr + TSR_SWAP_SEQ, 2))[0]
        self.last_seq = struct.unpack("<H", self.guest.read(hdr + 8, 2))[0]
        self._effects = None
        return "Dice log attached."

    def set_record_everything(self, record_everything: bool) -> None:
        """Record every rand() call, or (the default) only the ones shaped like rolls."""
        self.record_everything = record_everything
        if self.tsr_hdr is not None:
            filters = () if record_everything else FILTERS
            packed = b"".join(bytes([len(f)]) + f.ljust(8, b"\0") for f in filters)
            self.guest.write(self.tsr_hdr + 32, struct.pack("<H", len(filters)) + packed)

    def set_popups(self, on: bool) -> None:
        """Have the game show, when a turn in a fight ends, a summary of that turn's attacks."""
        self.popups = on
        if self.tsr_hdr is not None:
            self.guest.write(self.tsr_hdr + TSR_POPUPS, struct.pack("<H", int(on)))

    def set_pickpockets(self, on: bool) -> None:
        """Take P in a conversation as the leader trying the pocket of the person talked to."""
        self.pickpockets = on
        if self.tsr_hdr is not None:
            self.guest.write(self.tsr_hdr + TSR_PICK_ON, struct.pack("<H", int(on)))

    def load_picked(self, entries) -> None:
        """The pockets tried, as remembered (settings.json): "key@game time" (or a bare key, from
        an earlier version: forgotten the first time a game is loaded)."""
        self.picked, self.picked_at = set(), {}
        for entry in entries:
            key, at, when = entry.rpartition("@")
            if not (at and when.isdigit()):
                key, when = entry, ""
            self.picked.add(key)
            self.picked_at[key] = int(when) if when else None

    def take_picked(self) -> Optional[List[str]]:
        """All the pockets tried, for the caller to remember in place of what it had (settings.json),
        when they have changed since the last call; else None."""
        if not self._picked_changed:
            return None
        self._picked_changed = False
        return sorted(key if self.picked_at.get(key) is None else f"{key}@{self.picked_at[key]}"
                      for key in self.picked)

    def _remember_pick(self, key: str) -> None:
        self.picked.add(key)
        try:
            self.picked_at[key] = self.game.game_time()
        except (struct.error, IndexError, ValueError):
            self.picked_at[key] = None
        self._picked_changed = True

    def _forget_undone_picks(self) -> None:
        """Pockets tried later than the game's clock are forgotten (the person can be tried
        again): those since a save, when the save is loaded; another game's, in a new game."""
        try:
            now = self.game.game_time()
        except (struct.error, IndexError, ValueError):
            return
        if not now or now <= 0:  # (no game, or the menus)
            return
        went_back = self._clock is not None and now < self._clock
        if went_back:
            self._mended_in = None  # (a save loaded: its scrolls looked at again)
        # A try later than the game's clock is not this game's: one undone by loading an earlier
        # save, or another game's (a new game started with the same party, the Ledger started
        # after it: seen the first time the clock is read)
        undone = [k for k in self.picked
                  if (self.picked_at.get(k) is None and went_back)
                  or (self.picked_at.get(k) is not None and self.picked_at[k] > now)]
        for key in undone:
            self.picked.discard(key)
            self.picked_at.pop(key, None)
        self._picked_changed = self._picked_changed or bool(undone)
        self._clock = now

    def give_tools_now(self) -> List[str]:
        """Thieving tools for each thief in the party not carrying a set (the Ledger's button)."""
        if self.game is None:
            return []
        before = set(self.tools_given)
        try:
            if not names.update(self.game, self.tsr_hdr):
                return ["The game's name table has no room for the tools' name yet: load a game, then try again."]
            out = tools.give_tools(self.game, self.tools_given, now=True, session=self._tools_session)
        except (struct.error, IndexError, ValueError):
            return []
        self._tools_new += sorted(self.tools_given - before)
        return out or ["Every thief in the party has thieving tools already."]

    def take_tools_given(self) -> List[str]:
        """The thieves given tools since the last call, for the caller to remember."""
        new, self._tools_new = self._tools_new, []
        return new

    def _write_pick_text(self, text: str) -> None:
        offset = struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_PICK_OFF, 2))[0]
        base = self.tsr_hdr - struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_HDR_OFF, 2))[0]
        self.guest.write(base + offset, text.encode("cp437", "replace")[:PICK_SIZE - 1] + b"\0")

    def _answer_use(self) -> List[str]:
        """An item was used on something on the map: if it was the thieving tools on someone,
        try their pockets; if the cooked vulture, see what comes of it (vulture.py); and have
        DSCLOG show what came of it instead of the game's doing."""
        if self.tsr_hdr is None:
            return []
        seq = self.guest.read(self.tsr_hdr + TSR_USE_SEQ, 2)
        if seq == self.guest.read(self.tsr_hdr + TSR_USE_REPLY, 2):
            return []
        result, taken = None, False
        try:
            item, thing = struct.unpack("<HH", self.guest.read(self.tsr_hdr + TSR_USE_ITEM, 2) +
                                        self.guest.read(self.tsr_hdr + TSR_USE_WHO, 2))
            it = ring.Items(self.game)
            rec = it.item(item) if item < game.NO_ITEM else b""
            kind, index = it.thing(thing) if 0 <= thing < ring.THING_COUNT else (None, None)
            meal = vulture.use(self.game, rec, index, self._fighting()) if rec and kind == 2 else None
            if meal is not None:
                taken = 2 if meal.used_up else True
                result = pickpocket.Attempt(meal.text, meal.log)
            elif item < game.NO_ITEM and tools.is_tools(rec):
                kind, index = ring.Items(self.game).thing(thing)
                taken = True
                if self._fighting():  # (the tools stay on the pointer)
                    result = pickpocket.Attempt(tools.NOT_IN_A_FIGHT, [])
                else:
                    result = pickpocket.attempt(self.game, self.picked, who=index) if kind == 2 else None
                if result is None:
                    result = pickpocket.Attempt("There are no pockets to pick there.", [])
        except (struct.error, IndexError, ValueError):
            result, taken = None, False
        self._write_pick_text(result.text if result else "")
        self.guest.write(self.tsr_hdr + TSR_USE_TAKEN, struct.pack("<H", int(taken)))
        self.guest.write(self.tsr_hdr + TSR_USE_REPLY, seq)
        if not result:
            return []
        if result.key:
            self._remember_pick(result.key)
        return result.log or [result.text]

    def _answer_pick(self) -> List[str]:
        """P was pressed in a conversation: try the pocket, and hand DSCLOG what came of it."""
        if self.tsr_hdr is None:
            return []
        seq = self.guest.read(self.tsr_hdr + TSR_PICK_SEQ, 2)
        if seq == self.guest.read(self.tsr_hdr + TSR_PICK_REPLY, 2):
            return []
        try:
            result = pickpocket.attempt(self.game, self.picked)
        except (struct.error, IndexError, ValueError):
            result = None
        text = result.text if result else ""
        offset = struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_PICK_OFF, 2))[0]
        base = self.tsr_hdr - struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_HDR_OFF, 2))[0]
        self.guest.write(base + offset, text.encode("cp437", "replace")[:PICK_SIZE - 1] + b"\0")
        self.guest.write(self.tsr_hdr + TSR_PICK_REPLY, seq)
        if not result:
            return []
        if result.key:
            self._remember_pick(result.key)
        return result.log or [result.text]

    def set_monster_info(self, on: bool) -> None:
        """Have the game's Look box (in a fight) say what hurts a monster, and then show all of it."""
        self.monster_info = on
        if self.tsr_hdr is not None:
            self.guest.write(self.tsr_hdr + TSR_LOOK_ON, struct.pack("<H", int(on)))

    def use_settings(self, settings: dict) -> None:
        """The Options tab's switches for the game, as saved (for the logs without a window)."""
        self.popups = bool(settings.get("turn_popups", False))
        self.popup_level = popup_level(settings)
        self.monster_info = bool(settings.get("monster_info", True))
        self.arena_ring = bool(settings.get("arena_ring", True))
        self.pickpockets = bool(settings.get("pickpockets", True))
        self.show_gear = bool(settings.get("show_gear", True))
        self.show_shadows = bool(settings.get("shadows", True))
        self.scroll_map = bool(settings.get("scroll_map", True))
        self.show_dust = bool(settings.get("dust", True))
        self.ring_mode = rings.mode(settings)
        self.use_targeting = bool(settings.get("targeting", True))
        self.scroll_right = bool(settings.get("scroll_right", False))
        self.load_picked(settings.get("pickpocketed", []))
        self.tools_given = set(settings.get("tools_given", []))
        self.rules = game.rules_from_settings(settings)

    def set_rules(self, rules: int) -> None:
        """Turn the rule changes on or off (game.RULE_*). DSCLOG makes most of them; the spell
        save is the game's own table, written here."""
        self.rules = rules
        game.RULES_IN_FORCE = rules
        if self.game is not None:
            self.game.rules = rules
        if self.tsr_hdr is not None:
            self.guest.write(self.tsr_hdr + TSR_RULES, struct.pack("<H", rules))
            table = self.game.ds * 16 + game.SAVE_KINDS if self.game is not None else None
            # (only over the game's own table: kind 5 is petrification/polymorph or, so far, the spell save)
            if table is not None and struct.unpack("<5H", self.guest.read(table, 10)) == game.KIND_TO_SAVE[:5] \
                    and struct.unpack("<H", self.guest.read(table + 2 * game.SPELL_KIND, 2))[0] in (3, 5):
                save = game.kind_to_save(game.SPELL_KIND, rules)
                self.guest.write(table + 2 * game.SPELL_KIND, struct.pack("<H", save))
            if self.game is not None:
                self.game.set_cats_grace(bool(rules & game.RULE_CATS_GRACE))
                self.game.set_dodge(bool(rules & game.RULE_NO_DOUBLE))

    def _answer_look(self) -> List[str]:
        """DSCLOG asks about a creature the player looks at in a fight: give the Look box its
        short lines and the whole description, and log it."""
        if self.tsr_hdr is None:
            return []
        seq = struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_LOOK_SEQ, 2))[0]
        if seq == self._look_seq:
            return []
        self._look_seq = seq
        who = struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_LOOK_WHO, 2))[0]
        short: List[str] = []
        full: List[str] = []
        index = self.game.combatant_creature(who)
        if index is not None and index >= game.PARTY_SIZE:
            try:
                tables = monsters.MonsterTables(self.guest.read, self.game.load_seg)
                short, full = monsters.monster_lines(self.game, tables, index, self.last_ac.get(index))
            except (struct.error, IndexError, ValueError):
                short, full = [], []
        base = self.tsr_hdr - struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_HDR_OFF, 2))[0]
        text = "|".join(short).encode("cp437", "replace")[:LOOK_SIZE - 1]
        # the window only when there's more to say than the box's HP, AC and THAC0
        whole = " ".join(full).replace("%", " pct").encode("cp437", "replace")[:LOOK_FULL_SIZE - 1] \
            if len(full) > 1 else b""
        if whole:
            self._own_text.add(whole.decode("cp437"))  # not dialogue
        self.guest.write(base + struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_LOOK_OFF, 2))[0], text + b"\0")
        self.guest.write(base + struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_LOOK_FULL_OFF, 2))[0],
                         whole + b"\0")
        self.guest.write(self.tsr_hdr + TSR_LOOK_REPLY, struct.pack("<H", seq))
        return [f"Look: {full[0]}"] + [f"    {line}" for line in full[1:]] if full else []

    def _note_turn(self, lines: List[str]) -> None:
        """Keep the turn's rolls for the game's summary: everything the log says about them
        (attacks, damage, spells, saving throws), not the round's order or unlabelled dice."""
        skip = False
        for line in lines:
            if not line.startswith(" "):
                skip = line.startswith(("Round ", "Initiative", "Dice:", "Message:"))
            if not skip:
                self._turn_log.append(line)

    @staticmethod
    def _for_game(line: str) -> str:
        """A log line as the game's window shows it: without an attack's roll needed and chance
        ("needs 8+ (65%)", as the AC the roll hits and the target's AC say it) or a save's chance."""
        return TO_HIT_CHANCE.sub("", line.strip())

    def turn_summary(self, combatant: int, level: str = POPUP_DETAIL) -> str:
        """What happened during that combatant's turn, for the game's window. In detail, the dice
        log's lines for it, a line each: attacks (the roll, the THAC0 worked out, the damage
        dice), spells' damage and saving throws; in short, the attacks as
        "Daaki attacks Guard: 18 vs 8+ HIT, 13 damage; 5 vs 8+ miss" and the spells' first lines;
        at the least, what came of it, no dice: "Daaki hits Guard for 13, misses. Slig takes 9
        from Fireball"."""
        own = self.game.combatant_creature(combatant)
        order = sorted(self._turn_attacks, key=lambda c: c != own)  # stable: the rest in order of attacking
        if level == POPUP_DETAIL:
            text = "\n".join(self._for_game(line) for line in self._turn_log)
        elif level == POPUP_MINIMAL:
            parts = []
            for creature in order:
                target = None
                for a in self._turn_attacks[creature]:
                    what = (f"hits for {a['damage']}" if a["damage"] is not None else "hits") if a["hit"] else "misses"
                    if a["target"] != target:
                        target = a["target"]
                        what = what.replace("hits", f"hits {target}", 1) if a["hit"] else f"misses {target}"
                        parts.append(f"{self.game.creature_name(creature)} {what}")
                    else:
                        parts[-1] += f", {what}"
            parts += [m.group(1) for m in map(SPELL_RESULT.match, self._turn_log) if m]
            text = ". ".join(parts)
        else:
            parts = []
            for creature in order:
                target = None
                for a in self._turn_attacks[creature]:
                    roll = f"{a['d20']} vs {min(max(a['need'], 2), 20)}+"
                    roll += (f" HIT, {a['damage']} damage" if a["damage"] is not None else " HIT") if a["hit"] else " miss"
                    if a["target"] != target:
                        target = a["target"]
                        parts.append(f"{self.game.creature_name(creature)} attacks {target}: {roll}")
                    else:
                        parts[-1] += f"; {roll}"
            parts += [self._for_game(line) for line in self._turn_log
                      if not line.startswith(" ") and " attacks " not in line]  # spells, saves
            text = ". ".join(parts)
        if len(text) > MSG_SIZE - 1:  # what the game's window can take
            text = text[:MSG_SIZE - 4].rsplit(" ", 1)[0] + "..."
        return text

    def slots_lines(self, member: int) -> str:
        """A party member's spell slots for the game's USE screen, "|" between lines:
        "SPELLS LEFT BY LEVEL|WIZ 2/2 1/1|PRI 5/5 3/3 2/2 1/1" (six levels a line). The
        screen has room for SLOTS_LINES lines above the icons of any usable items, so the
        heading goes when the slots need them all, and anything past them is cut."""
        lines = []
        for kind, levels in self.game.spell_slots(member):
            top = max(level for level, _, _ in levels)
            by_level = {level: (left, most) for level, left, most in levels}
            cells = [f"{by_level.get(n, (0, 0))[0]}/{by_level.get(n, (0, 0))[1]}" for n in range(1, top + 1)]
            for i in range(0, len(cells), 6):
                lines.append(("    " if i else f"{SLOT_KINDS.get(kind, kind[:3].upper())} ") + " ".join(cells[i:i + 6]))
        if lines and len(lines) < SLOTS_LINES:
            lines.insert(0, "SPELLS LEFT BY LEVEL")
        return "|".join(lines[:SLOTS_LINES])

    def _write_slots(self) -> None:
        """Keep DSCLOG's copy of the party's spell slots current."""
        if self.tsr_hdr is None:
            return
        base = self.tsr_hdr - struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_HDR_OFF, 2))[0]
        table = base + struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_SLOTS_OFF, 2))[0]
        data = b""
        for member in range(game.PARTY_SIZE):
            try:
                text = self.slots_lines(member)
            except (struct.error, IndexError, ValueError):
                text = ""
            data += text.encode("cp437", "replace")[:SLOTS_SIZE - 1].ljust(SLOTS_SIZE, b"\0")
        if data != self._slots_written:
            self.guest.write(table, data)
            self._slots_written = data

    def stats_entry(self, member: int) -> bytes:
        """A party member's STATS entry for DSCLOG: THAC0 with the main weapon, the five saves as
        the d20 needed now, THAC0 with each weapon ready, and a thief's skills as they stand."""
        g = self.game
        rec = g.creature(member)
        if len(rec) < game.CREATURE_SIZE or not rec[game.CREATURE_NAME]:
            return bytes(STATS_SIZE)
        saves, hits = g.saves_now(member), g.weapon_hits(member)
        if len(saves) != 5 or not hits:
            return bytes(STATS_SIZE)
        clamp = lambda n: max(-99, min(99, n))
        weapons = [h for h in hits if h.item >= 0][:3]
        out = struct.pack("<Bb5Bx", 1, clamp(hits[0].thac0), *(s.needs for s in saves))
        out += struct.pack("<3H", *([h.item for h in weapons] + [game.NO_ITEM] * (3 - len(weapons))))
        out += struct.pack("<3b", *([clamp(h.thac0) for h in weapons] + [0] * (3 - len(weapons))))
        thief = g.thief_skills_now(member, game.PANEL_SKILLS)
        ranger = g.ranger_skills_now(member) if self.rules & game.RULE_STEALTH and not thief else []
        if len(thief) == 6:
            out += struct.pack("<B6B", 1, *(n for _, n in thief))
        elif len(ranger) == 2:  # move silently and hide in shadows, in a thief's places
            out += struct.pack("<B6B", STATS_RANGER, 0, 0, 0, *(min(n, 255) for _, n in ranger), 0)
        else:
            out += bytes(7)
        return out.ljust(STATS_SIZE, b"\0")

    def _answer_stats(self) -> None:
        """A game screen is about to show THAC0 and the saves: bring them up to date first (the
        game waits for this, so an item just put on counts)."""
        if self.tsr_hdr is None:
            return
        req = self.guest.read(self.tsr_hdr + TSR_STATS_REQ, 2)
        if req != self.guest.read(self.tsr_hdr + TSR_STATS_REPLY, 2):
            self._write_stats()
            self.guest.write(self.tsr_hdr + TSR_STATS_REPLY, req)

    def _write_stats(self) -> None:
        """Keep DSCLOG's copy of the party's THAC0 and saves current, and say it is."""
        if self.tsr_hdr is None:
            return
        offset = struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_STATS_OFF, 2))[0]
        if not offset:
            return
        table = self.tsr_hdr - struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_HDR_OFF, 2))[0] + offset
        data = b""
        for member in range(game.PARTY_SIZE):
            try:
                data += self.stats_entry(member)
            except (struct.error, IndexError, ValueError):
                data += bytes(STATS_SIZE)
        if data != self._stats_written:
            self.guest.write(table, data)
            self._stats_written = data
        self.guest.write(self.tsr_hdr + TSR_STATS_STAMP, self.guest.read(BIOS_TIMER, 2))

    def _not_ours(self, entries: List[DialogueEntry]) -> List[DialogueEntry]:
        """Dialogue without the turn summaries the log itself had the game show (and their
        "Continue")."""
        out = []
        for entry in entries:
            said = " ".join(entry.text.split())  # DSCLOG keeps the first 400 characters of a text
            own = next((t for t in self._own_text if said and " ".join(t.split()).startswith(said)), None)
            if own is not None:
                self._own_text.discard(own)
                self._skip_choice = True
            elif entry.chosen and self._skip_choice:
                self._skip_choice = False
            else:
                out.append(entry)
        return out

    def _turn_waiting(self) -> bool:
        """DSCLOG has counted a turn's end the log hasn't answered yet."""
        if self.tsr_hdr is None:
            return False
        return struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_TURN_SEQ, 2))[0] != self._turn_seq

    def _answer_turn(self) -> None:
        """DSCLOG counts a turn's end and waits a moment for the summary: give it."""
        if self.tsr_hdr is None:
            return
        seq = struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_TURN_SEQ, 2))[0]
        if seq == self._turn_seq:
            return
        self._turn_seq = seq
        ended = struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_ENDED, 2))[0]
        # Only in the party's own fights: a fight the scripts stage without the party (the
        # Defiler's show at the arena's start) waits on the game's dialogue window, and a summary
        # there would let its script run on before the fight is over.
        summary = self.turn_summary(ended, self.popup_level) if self.popups and self._party_fighting(ended) else ""
        if summary and self.popup_level != POPUP_MINIMAL:  # and who is still to come, so the order isn't lost
            try:
                still = self.still_to_act(ended, frozenset(self._turn_attacks))
            except (struct.error, IndexError, ValueError):
                still = ""
            if still:
                summary += ("\n" if self.popup_level == POPUP_DETAIL else ". ") + still
        summary = summary.replace("%", " pct")  # the game's window shows no "%", even as "%%"
        if len(summary) > MSG_SIZE - 1:
            summary = summary[:MSG_SIZE - 4].rsplit(" ", 1)[0] + "..."
        if summary:
            self._own_text.add(summary)  # to leave out of the Dialogue tab
        text = summary.encode("cp437", "replace")[:MSG_SIZE - 1]
        base = self.tsr_hdr - struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_HDR_OFF, 2))[0]
        msg = base + struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_MSG_OFF, 2))[0]
        self.guest.write(msg, text + b"\0")
        self.guest.write(self.tsr_hdr + TSR_REPLY_SEQ, struct.pack("<H", seq))
        self._turn_attacks.clear()
        self._turn_log.clear()

    def _party_fighting(self, ended: int) -> bool:
        """Whether the party is in this fight: someone of it in the round's order (or, before
        the log has seen an order, the turn that ended was a party member's)."""
        if self.round_order:
            return any(c is not None and 0 <= c < game.PARTY_SIZE for c, _, _ in self.round_order)
        return 0 <= ended < game.PARTY_SIZE

    @property
    def attached(self) -> bool:
        return self.rand_addr is not None

    @property
    def load_seg(self) -> int:
        return (self.rand_addr - RAND_IP) // 16

    def still_patched(self) -> bool:
        """False when the game has quit or been replaced by an unpatched one."""
        sig = self.guest.read(self.game.ds * 16 + game.BORLAND_SIG_OFFSET, len(game.BORLAND_SIG))
        return sig == game.BORLAND_SIG and self.guest.read(self.rand_addr, 2) == RAND_PATCHED

    def detach(self) -> None:
        self.rand_addr = None

    # ---- reading ----------------------------------------------------------------

    def poll(self) -> List[Entry]:
        """Entries written since the last poll, oldest first."""
        head = self.guest.read(self.tsr_hdr, 24)
        seq, _, nent, esize, ring_off = struct.unpack_from("<5H", head, 8)
        new = (seq - self.last_seq) & 0xFFFF
        if not new:
            return []
        ring_base = self.tsr_hdr - struct.unpack_from("<H", head, 20)[0] + ring_off
        ring = self.guest.read(ring_base, nent * esize)
        entries = {}
        for i in range(nent):
            e = Entry.parse(ring[i * esize:(i + 1) * esize])
            if 0 < (e.seq - self.last_seq) & 0xFFFF <= new:
                entries[e.seq] = e
        self.missed += new - len(entries)
        self.last_seq = seq
        return [entries[s] for s in sorted(entries, key=lambda s: (s - seq - 1) & 0xFFFF)]

    def lines(self, show_all: bool = False, now: Optional[float] = None) -> List[str]:
        """Everything new since the last call, as log lines. Call it every few tens of ms."""
        now = time.monotonic() if now is None else now
        out: List[str] = []
        for e in self.poll():
            out += self.describe(e, show_all, now)
        if self._initiative and self._initiative_roll is None and self._turn_waiting():
            # the round's last turn has ended and the new round's rolls are all in: its order
            # first, for the end of the summary
            out += self.initiative_lines()
        self._answer_turn()  # after the entries: they hold the turn's last attack
        self._forget_undone_picks()
        self._answer_stats()
        out += self._answer_pick()
        out += self._answer_use()
        out += self._answer_look()
        changes = self.hp_changes(now) + self.psp_changes()
        if not self._party_check(now):  # not while a game is loading: its records are half-filled
            out += changes
        for rec in self.text.poll():
            if rec.kind == KIND_MESSAGE:
                if rec.text.strip():
                    out.append(f"Message: {' '.join(rec.text.split())}")
            else:
                self._follow_talk(rec)
                self._dialogue += self._not_ours(self.dialogue.add(rec, now))
        self._dialogue += self._not_ours(self.dialogue.idle(now))
        self._dialogue += self._not_ours(self._reply_choice(now))
        if now >= self._next_effect_check:
            self._next_effect_check = now + EFFECT_INTERVAL
            out += self.effect_changes(now)
            self._write_slots()
            self._write_stats()
            if not self._party_check(now):
                out += self.tracker.check(now)
                out += self._arena_ring(now)
                out += self._drawn(now)
                self._kalzith_sold_out()
        self._scroll()
        if self._initiative and now - self._initiative_at >= INITIATIVE_WAIT:
            out += self.initiative_lines()
        out += self.turn_lines()  # after the round's order and the last turn's XP
        if self._creation_hp and now - self._creation_hp_at >= CREATION_HP_WAIT:
            out += self.creation_hp_lines()
        out += self.flush(now)
        if self.missed:
            out.append(f"({self.missed} rolls came too fast to record)")
            self.missed = 0
        return out

    def _arena_ring(self, now: float) -> List[str]:
        """The helms' and boots' names for the rules; once the game's name table has DSCLOG's
        names, the ring and tools from earlier versions named in them, and in the arena, the
        ring itself, and a set of tools for each thief who hasn't had one."""
        if now < self._ring_check:
            return []
        self._ring_check = now + RING_INTERVAL
        out: List[str] = []
        try:
            ring.name_items(self.game, self.rules)
            if not names.update(self.game, self.tsr_hdr):
                return out  # no names for them yet: none given
            if npcitems.types_ready(self.game, self.tsr_hdr):  # Kurzak's, Legcrusher's, Pehtucl's
                before = set(self.tools_given)
                out += npcitems.place(self.game, self.tools_given)
                out += bonescale.place(self.game, self.tools_given)  # the bone scale armour's set
                npcitems.reprice(self.game)  # (those given before they had a magic item's price)
                self._tools_new += sorted(self.tools_given - before)
            kalzith.stock(self.game, bool(self.rules & game.RULE_CATS_GRACE))  # (once a game, by its flag)
            semyon.watch(self.game)  # (killed: never put in the pens)
            if kalzith.watch(self.game):  # (killed: Dinos and the Trustee speak of him so)
                left = kalzith.loot(self.game)  # (one of his scrolls, his Cloak and Quarterstaff)
                if left:
                    out.append("Kalzith leaves: " + ", ".join(left))
            region = self.game.region()
            if region != self._mended_in:  # (his scrolls of before the fix, once in each area)
                kalzith.mend(self.game)
                self._mended_in = region
            if self.pickpockets:
                tools.repaint(self.game)
                before = set(self.tools_given)
                out += tools.give_tools(self.game, self.tools_given, session=self._tools_session)
                self._tools_new += sorted(self.tools_given - before)
            out += self._ring_search()
            icons.repaint(self.game, icons.ready(self.game, self.tsr_hdr))  # the items' own icons
            self._dress(now)
        except (struct.error, IndexError, ValueError):
            return out
        return out

    def _drawn(self, now: float) -> List[str]:
        """What DSCLOG draws and does for the Ledger, kept up four times a second (not with the
        ring's search, every 3 s: a Tab's ring and the Enter's target were that late): shadows,
        the enemy chosen with Tab and the rings, dust."""
        if self.tsr_hdr is None:
            return []
        try:
            self._shadows.update(self.game, self.tsr_hdr, self.show_shadows, now,
                                 needed=self.show_dust or self.ring_mode != rings.OFF)
            foes = rings.enemies(self.game)
            out = self._targeting.update(self.game, self.tsr_hdr, self.use_targeting, foes)
            self._rings.update(self.game, self.tsr_hdr, self.ring_mode != rings.OFF, self._shadows.palettes,
                               self._targeting.chosen, all_enemies=self.ring_mode == rings.ALL)
            self._dust.update(self.game, self.tsr_hdr, self.show_dust, self._shadows.palettes)
        except (struct.error, IndexError, ValueError):
            return []
        return out

    def _kalzith_sold_out(self) -> None:
        """All six of Kalzith's scrolls bought: no more shop, and he carries his two, put on him
        only while the map's main loop runs (DSCLOG's count of it went up since the last look: no
        talk, menu or shop open)."""
        if self.tsr_hdr is None:
            return
        try:
            ticks = struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_MAIN_TICKS, 2))[0]
            quiet = self._main_ticks is not None and ticks != self._main_ticks
            self._main_ticks = ticks
            kalzith.sold_out(self.game, quiet)
        except (struct.error, IndexError, ValueError):
            pass

    def _scroll(self) -> None:
        """The map scrolled by the wheel's turns, at every look (they come in as they're made)."""
        if self.tsr_hdr is None:
            return
        try:
            self._scrolling.update(self.game, self.tsr_hdr, self.scroll_map, self.scroll_right)
        except (struct.error, IndexError, ValueError):
            pass

    def _dress(self, now: float) -> None:
        """The party's sprites in what they wear, once the game has the Ledger's SEGOBJEX (whose
        party pictures the Ledger keeps dressed); as the game's own when switched off."""
        if not icons.ready(self.game, self.tsr_hdr):
            return
        if self._dresser is None and not self._dresser_tried:
            from . import launch
            self._dresser_tried = True
            import os
            copy = os.path.join(launch.DOS_DIR, icons.OBJECTS_FILE)
            self._dresser = sprites.Dresser.for_game(self.game, launch.find_game_dir(),
                                                     copy if os.path.exists(copy) else None)
            if self._dresser is not None and self.tsr_hdr is not None:
                hdr = self.tsr_hdr
                self._dresser.request_redraw = lambda: shadows.redraw(self.game, hdr)
        if self._dresser is not None and (self.show_gear or self._dresser.shown):
            self._dresser.update(self.show_gear, now)

    def _ring_search(self) -> List[str]:
        """While the arena's ring is still to be found: have DSCLOG show ring.SEARCH_TEXT instead
        of the arena script's "There is nothing on the body.", and once it has, put the ring
        in the leader's backpack."""
        if self.tsr_hdr is None:
            return []
        needed = self.arena_ring and ring.ring_needed(self.game)
        seq, = struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_SWAP_SEQ, 2))
        fired, self._swap_seq = seq != self._swap_seq, seq
        out = []
        if needed and fired:
            given = ring.give_ring(self.game)
            out.append(given or "No one in the party has room for the ring: make room and look at the body again.")
            needed = given is None
        on = struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_SWAP_ON, 2))[0]
        if needed and not on:
            offset, = struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_SWAP_OFF, 2))
            base = self.tsr_hdr - struct.unpack("<H", self.guest.read(self.tsr_hdr + TSR_HDR_OFF, 2))[0] + offset
            self.guest.write(base, ring.NOTHING.encode("cp437").ljust(SWAP_SIZE, b"\0")[:SWAP_SIZE])
            self.guest.write(base + SWAP_SIZE, ring.SEARCH_TEXT.encode("cp437")[:SWAP_TEXT_SIZE - 1] + b"\0")
            self.guest.write(self.tsr_hdr + TSR_SWAP_ON, struct.pack("<H", 1))
        elif not needed and on:
            self.guest.write(self.tsr_hdr + TSR_SWAP_ON, struct.pack("<H", 0))
        return out

    def psp_changes(self) -> List[str]:
        """The party's PSP going down (a psionic power used, or kept up another round: the game
        takes each maintained power's cost every round) or back up."""
        out = []
        for index in range(game.PARTY_SIZE):
            rec = self.game.creature(index)
            if len(rec) < 4:
                continue
            psp = struct.unpack_from("<h", rec, game.CREATURE_PSP)[0]
            before, self._psp[index] = self._psp.get(index), psp
            if before is None or before == psp or not rec[game.CREATURE_NAME] or not 0 <= before <= 1000:
                continue  # unchanged, an empty party slot, or a record still being loaded
            who = self.game.creature_name(index)
            if psp < before:
                out.append(f"    {who} spends {before - psp} PSP ({before} -> {psp})")
            else:
                out.append(f"    {who} regains {psp - before} PSP ({before} -> {psp})")
        return out

    def hp_changes(self, now: float) -> List[str]:
        """Every combatant's HP going down or up, with what's left (the game never shows a
        monster's HP). Put down to a spell while one is being cast (the damage after saves,
        resistances and protections, or the healing)."""
        g = self.game
        out = []
        current = {}
        for combatant, index in sorted(g.combatants().items()):
            rec = g.creature(index)
            if len(rec) < 2:
                continue
            hp = struct.unpack_from("<h", rec, 0)[0]
            current[index] = hp
            was_out_cold = self._out_cold.get(index, False)
            self._out_cold[index] = rec[game.CREATURE_STATUS] == game.OUT_COLD
            before = self._hp.get(index)
            if before is None or before == hp or not -100 <= before <= 2000:
                continue  # unchanged, or a record still being loaded
            who = g.creature_name(index)
            sheet = g.sheet(index)
            most = struct.unpack_from("<h", sheet, game.SHEET_MAX_HP)[0] if len(sheet) >= game.SHEET_SIZE else None
            left = f"now {hp}/{most} HP" if most and most > 0 else f"now {hp} HP"
            hit, resisted = self._hits_seen(index, max(before - hp, 0), hp)
            if now <= self._spell_until and before - hp > hit:
                # the game's damage code gives a creature that was Out Cold the most the dice can do
                out_cold = " (Out Cold: the most the dice can do)" if was_out_cold else ""
                also = f" and {hit} from the hit" if hit else ""
                out.append(f"  {who} takes {before - hp - hit} from {self._spell_name}{out_cold}{also}, {left}")
            elif now <= self._spell_until and hp > before:
                out.append(f"  {who} regains {hp - before} HP from {self._spell_name}, {left}")
            elif hp < before:
                out.append(f"  {who} {left} (-{before - hp}{resisted})")
            else:
                out.append(f"  {who} {left} (+{hp - before})")
        self._hp = current
        return out + self.unhurt(now)

    def _hit(self, target: int, damage: int, now: float) -> None:
        """A weapon hit's damage rolled against TARGET: to be seen in its HP."""
        entry = self._hits.setdefault(target, {"hits": [], "at": now, "hp": self._hp.get(target)})
        entry["hits"].append(damage)
        entry["at"] = now

    def _hits_seen(self, index: int, lost: int, hp: int) -> Tuple[int, str]:
        """The weapon hits a fall of LOST HP (to HP) took in, in the order they landed: (their
        damage, and a note when one did less than its roll: resisted)."""
        entry = self._hits.get(index)
        if not entry:
            return 0, ""
        hits, taken, note = entry["hits"], 0, ""
        if hp <= 0:  # (down: whatever was rolled, its HP ran out)
            del self._hits[index]
            return min(sum(hits), lost), ""
        while hits and lost - taken >= hits[0]:
            taken += hits.pop(0)
        if hits and not taken and lost:  # (less than the hit)
            rolled = hits.pop(0)
            taken = lost
            reason = self._weapon_reason(index)
            note = f": {lost} of the {rolled} rolled" + (f", {reason}" if reason else "")
        if hits:
            entry["hp"] = hp
        else:
            del self._hits[index]
        return taken, note

    def unhurt(self, now: float, force: bool = False) -> List[str]:
        """Weapon hits that took no HP (HIT_WAIT seconds on, or FORCE: a new round): the target
        immune to the weapon, or protected (Stoneskin...)."""
        out = []
        for index, entry in list(self._hits.items()):
            if not force and now - entry["at"] < HIT_WAIT:
                continue
            del self._hits[index]
            rec = self.game.creature(index)
            hp = struct.unpack_from("<h", rec, 0)[0] if len(rec) >= 2 else None
            if hp is None or hp <= 0 or (entry["hp"] is not None and entry["hp"] != hp):
                continue  # (its HP did go down, or it's gone: not unhurt)
            reason = self._weapon_reason(index) or "a protection or resistance took it"
            rolled = sum(entry["hits"])
            out.append(f"  {self.game.creature_name(index)} takes none of the {rolled} damage: {reason}")
        return out

    def _weapon_reason(self, index: int) -> Optional[str]:
        """What the creature's defences say about weapons, if anything."""
        if index < game.PARTY_SIZE:
            return None
        try:
            if self._tables is None:
                self._tables = monsters.MonsterTables(self.guest.read, self.game.load_seg)
            d = monsters.creature_defences(self.game, self._tables, index)
        except (struct.error, IndexError, ValueError):
            return None
        return monsters.weapon_reason(d) if d is not None else None

    def _spell_cast(self, spell: Optional[int], now: float) -> None:
        """A spell is taking effect: HP changes for the next few seconds are its doing."""
        if spell is not None:
            self._spell_name = self.game.spell_name(spell)
            self._spell_until = now + SPELL_WINDOW

    def speaker(self, portrait: Optional[int]) -> str:
        """Who a dialogue portrait belongs to, as far as is known."""
        if portrait is None:
            return "(no portrait)"
        if portrait == 0:
            return "Narration"  # the window shows an emblem, not a face
        return (self.speaker_names.get(portrait) or game.SPEAKERS.get(portrait)
                or self.learned_speakers.get(portrait) or f"Portrait {portrait}")

    def _follow_talk(self, rec) -> None:
        """Learn portraits' names: a conversation (the window opening to CLOSE) that shows a single
        face, started on a named creature, is that creature talking. With several faces (a scene
        where others speak too) it can't be told who is who, so nothing is learned."""
        if rec.kind == KIND_PORTRAIT:
            if self._talk is None:
                try:
                    target = self.game.talk_target()
                except (struct.error, IndexError, ValueError):
                    target = None
                self._talk = {"portraits": set(), "with": target}
            if rec.value:
                self._talk["portraits"].add(rec.value)
        elif rec.kind == KIND_TEXT and rec.text == "CLOSE" and self._talk is not None:
            talk, self._talk = self._talk, None
            if len(talk["portraits"]) == 1 and talk["with"]:
                portrait = next(iter(talk["portraits"]))
                if portrait in game.SPEAKERS:
                    pass  # known already (the Announcer calls out mid-fight, "started on" a fighter)
                elif self.learned_speakers.get(portrait) != talk["with"]:
                    self.learned_speakers[portrait] = talk["with"]
                    self._new_speakers[portrait] = talk["with"]

    def take_speakers(self) -> Dict[int, str]:
        """Portrait names learned since the last call."""
        out, self._new_speakers = self._new_speakers, {}
        return out

    def _reply_choice(self, now: float) -> List[DialogueEntry]:
        """The player's answer, once, when they click a reply."""
        chosen, before = self.game.reply_chosen(), self._reply
        self._reply = chosen
        if chosen is None or chosen == before or not chosen[1]:
            return []
        return self.dialogue.flush() + [DialogueEntry(None, chosen=chosen[1])]

    def take_dialogue(self) -> List[DialogueEntry]:
        """Dialogue that has come in since the last call (lines() collects it)."""
        out, self._dialogue = self._dialogue, []
        return out

    def _party_check(self, now: float) -> bool:
        """True for a while after the party changes (a game was loaded): what's there is not news."""
        party = self.game.party_signature()
        if party != self._party:
            self._party, self._party_changed_at = party, now
        if now - self._party_changed_at < LOAD_SETTLE:
            if self.tracker:
                self.tracker.reset()
            return True
        return False

    # ---- effects (spells and powers on creatures) ------------------------------

    def _name(self, combatant: int) -> str:
        """A combatant's name, remembered for when the fight is over."""
        name = self.game.combatant_name(combatant)
        if name != "?":
            self._names[combatant] = name
        return self._names.get(combatant, name)

    def effect_changes(self, now: float = 0.0) -> List[str]:
        """Lines for effects that started or ended since the last look."""
        current = Counter(self.game.effects())
        for eff in current:
            self._name(eff.owner)
            self._name(eff.caster)
        loading = self._party_check(now)
        if self._effects is None or loading:
            self._effects = current  # the first look, or just loaded: remember what is active
            return []
        started, ended = current - self._effects, self._effects - current
        self._effects = current
        out = []
        by_cast: Dict[Tuple[int, int], List[int]] = {}
        for eff in started.elements():
            by_cast.setdefault((eff.caster, eff.id), []).append(eff.owner)
        for (caster, eid), owners in by_cast.items():
            name = EFFECT_NAMES.get(eid, f"effect {eid}")
            targets = ", ".join(self._name(o) for o in owners)
            rule = f": {EFFECT_RULES[eid]}" if eid in EFFECT_RULES else ""
            if owners == [caster] * len(owners):  # on itself (or from a spell on the ground)
                out.append(f"{name} on {targets}{rule}")
            else:
                out.append(f"{self._name(caster)} gives {name} to {targets}{rule}")
        by_end: Dict[int, List[int]] = {}
        for eff in ended.elements():
            by_end.setdefault(eff.id, []).append(eff.owner)
        for eid, owners in by_end.items():
            name = EFFECT_NAMES.get(eid, f"effect {eid}")
            out.append(f"{name} ends on {', '.join(self._name(o) for o in owners)}")
        return out

    # ---- describing -----------------------------------------------------------

    def describe(self, e: Entry, show_all: bool = False, now: float = 0.0) -> List[str]:
        """Log lines for `e` (none if it isn't worth showing, or completes later)."""
        try:
            said = self._describe(e, show_all, now)
            self._note_turn(said)  # (only what's labelled: show_all adds rand() lines, not for the game)
            return said
        except Exception as err:  # an unexpected entry must never stop the log
            if show_all:
                return [f"rand() = {e.raw}  (at {e.cs:04x}:{e.ip:04x}; could not decode: {err})"]
            return []

    def flush(self, now: float, force: bool = False) -> List[str]:
        """Dice that waited long enough without a spell turning up."""
        out = []
        while self._pending and (force or now - self._pending[0].at >= PENDING_SECONDS):
            p = self._pending.pop(0)
            if p.resistance:
                out += self._magic_resistance(*p.resistance)
            else:
                out.append(f"Dice: {p.text}")
        return out

    def _describe(self, e: Entry, show_all: bool, now: float) -> List[str]:
        if e.kind == KIND_ROLL and e.code.startswith(INITIATIVE_ROLL):
            self._initiative_roll, self._initiative_at = scaled(e.raw, 10), now
            return []
        if e.kind == KIND_ROLL and e.code.startswith(INITIATIVE_TIE):
            if self._initiative_roll is not None:
                self._initiative.append((self._initiative_roll, scaled(e.raw, 200)))
            self._initiative_roll, self._initiative_at = None, now
            return []
        return self.initiative_lines() + self._describe_entry(e, show_all, now)

    def turn_lines(self) -> List[str]:
        """'Gerakis's turn' whenever the turn passes during a fight."""
        if self._initiative or self._initiative_roll is not None:
            return []  # a round is starting: its order comes first
        turn = self.game.whose_turn()
        if turn is None or turn == self._turn:
            return []
        self._turn = turn
        self._acted.add(turn)
        self._set_stealth(False)  # the last turn's hiding is over
        now = self.game.game_time()
        if self._round_time is None or now is None or now - self._round_time > FIGHT_GAP:
            return []  # not in a fight
        name = self.game.combatant_name(turn)
        out = [f"{name}'s turn"] if name != "?" else []
        if self.rules & game.RULE_STEALTH and turn < game.PARTY_SIZE:
            try:
                lines, hidden = stealth.turn(self.game, turn, self.stealth_roll)
            except (struct.error, IndexError, ValueError):
                lines, hidden = [], False
            out += lines
            self._set_stealth(hidden, turn)
        return out

    def _fighting(self) -> bool:
        """In a fight, by the game's own flag (game time barely moves outside fights, so the time
        since the last round can't tell: the party stood "in a fight" until they rested)."""
        try:
            return self.game.in_combat()
        except (struct.error, IndexError, ValueError):
            return False

    def _set_stealth(self, hidden: bool, member: int = 0) -> None:
        """Have DSCLOG make this party member's next attack one from behind (or no one's)."""
        if self.tsr_hdr is not None:
            self.guest.write(self.tsr_hdr + stealth.TSR_STEALTH, struct.pack("<H", 1 << member if hidden else 0))

    def round_status(self, acted_creatures: frozenset = frozenset()) -> Optional[dict]:
        """The round in progress, for keeping its order in view: {"round", "now": (name, score),
        "next": [(name, score)...], "done": [...], "down": [...]}, in initiative order; None
        outside a fight. Creatures (indexes) in `acted_creatures` count as done: their rolls
        are in, though the game hasn't passed the turn on yet."""
        now = self.game.game_time()
        if not self.round_order or self._round_time is None or now is None or now - self._round_time > FIGHT_GAP:
            return None
        acting = self.game.whose_turn()
        out = {"round": self.round_number, "now": None, "next": [], "done": [], "down": []}
        for combatant, name, score in self.round_order:
            index = self.game.combatant_creature(combatant) if combatant is not None else None
            try:
                if index is not None:
                    hp = struct.unpack_from("<h", self.game.creature(index), 0)[0]
                else:  # a killed creature leaves the fight's table
                    hp = 0 if combatant is not None else 1
            except (struct.error, IndexError, ValueError):
                hp = 1
            if hp <= 0:
                out["down"].append((name, score))
            elif index is not None and index in acted_creatures:
                out["done"].append((name, score))
            elif combatant == acting:
                out["now"] = (name, score)
            elif combatant in self._acted:
                out["done"].append((name, score))
            else:
                out["next"].append((name, score))
        return out

    def still_to_act(self, ended: Optional[int] = None, acted_creatures: frozenset = frozenset()) -> str:
        """For the end of the game's turn summary: 'Still to act this round: Mlemlem, Guard';
        when the turn that ended (combatant `ended`) was the last of its round and the new
        round's order is in, 'Round 3: Dreamwalker, Jellybelly'; when everyone has acted but
        the new round isn't rolled yet, 'End of round 2.'; or "". The creatures whose rolls the
        summary shows (`acted_creatures`) have had their turn, whoever the game says is acting:
        it runs a monster's whole turn before the helper can ask."""
        new_round = ended is not None and ended not in self._acted  # its rolls were the last round's
        status = self.round_status(frozenset() if new_round else acted_creatures)
        if not status:
            return ""
        names = ([status["now"][0]] if status["now"] else []) + [n for n, _ in status["next"]]
        if new_round and status["round"] and names:
            return f"Round {status['round']}: " + ", ".join(names)
        if not names:
            return f"End of round {status['round']}." if status["round"] else ""
        return "Still to act this round: " + ", ".join(names)

    def _round_number(self) -> int:
        """The round of this fight: the game's clock moves 60 seconds a round, and a longer gap
        means a new fight."""
        now = self.game.game_time()
        if now is None:
            return 0
        if self._round_time is None or now - self._round_time > FIGHT_GAP:
            self._round = 0
            # a new fight: the game hands its creature records to new monsters, so an AC worked
            # out for one in an earlier fight isn't this one's (the party's stay theirs)
            for remembered in (self.last_ac, self.ac_detail):
                for index in [i for i in remembered if i >= game.PARTY_SIZE]:
                    del remembered[index]
        self._round_time = now
        self._round += 1
        return self._round

    def initiative_lines(self) -> List[str]:
        """The round's order, from the rolls collected since the round began."""
        pairs, self._initiative = self._initiative, []
        if not pairs:
            return []
        unhurt = self.unhurt(0.0, force=True)  # a new round: hits not seen in HP by now never will be
        g = self.game
        combatants = g.combatants()
        table = g.initiative(max(combatants.values(), default=0) + 1)
        effects = g.effects()
        rows, used = [], set()
        for roll, tie in pairs:
            # the game keeps each creature's tie-break roll: that says whose rolls these were
            found = [(c, i) for c, i in sorted(combatants.items()) if i not in used and table[i][1] == tie]
            if not found:
                rows.append((INITIATIVE_BASE + roll, tie, f"? {INITIATIVE_BASE + roll}", f"{roll} (0-9 roll)", None, "?"))
                continue
            combatant, index = found[0]
            used.add(index)
            parts = []
            dex = g.dex_initiative(g.creature(index)[CREATURE_ABILITIES + 1])
            if dex:
                parts.append((dex, "DEX"))
            ids = {x.id for x in effects if x.owner == combatant and x.id in game.INITIATIVE_EFFECTS}
            parts += [(game.INITIATIVE_EFFECTS[eid], EFFECT_NAMES[eid]) for eid in sorted(ids)]
            score = INITIATIVE_BASE + roll + sum(v for v, _ in parts)
            stored = table[index][0]
            if stored >= 0 and stored != score:  # not acted yet, and something else counted
                parts.append((stored - score, "other"))
                score = stored
            steps = f"{roll} (0-9 roll)" + "".join(f" {signed(v)} {name}" for v, name in parts)
            rows.append((score, tie, f"{g.creature_name(index)} {score}", steps, combatant, g.creature_name(index)))
        rows.sort(key=lambda r: (-r[0], -r[1]))
        scores = Counter(r[0] for r in rows)
        number = self._round_number()
        self.round_number = number
        self.round_order = [(combatant, name, score) for score, _, _, _, combatant, name in rows]
        self._acted = set()
        order = ", ".join(r[2] for r in rows)
        out = [f"Round {number}" + (f": {order}" if order else "") if number else f"Initiative: {order}"]
        for score, tie, who, steps, _, _ in rows:
            tied = f", tie broken by {tie} (0-199 roll)" if scores[score] > 1 else ""
            out.append(f"    {who} = {INITIATIVE_BASE} + {steps}{tied}")
        return unhurt + out

    def _describe_entry(self, e: Entry, show_all: bool, now: float) -> List[str]:
        if e.kind == KIND_SAVE:
            return self._save(e)
        if e.kind == KIND_AC:
            return self._ac(e, show_all)
        code = e.code
        if code.startswith(ATTACK_SITE):
            self._spell_until = 0.0
            return self.flush(now, force=True) + self._attack(e)
        if code.startswith(DICE_SITE):
            return self._dice_roll(e, show_all, now)
        if code.startswith(CHECK_SITE):
            return self.flush(now, force=True) + self._check(e, show_all)
        if code.startswith(BREAK_ROLL_1) or code.startswith(BREAK_ROLL_2):
            return self._break_check(e, code.startswith(BREAK_ROLL_1), show_all)
        if code.startswith(PERCENT_SITE):
            return self._thief_skill(e)
        if show_all:
            generic = generic_roll(code, e)
            where = f"{e.cs:04x}:{e.ip:04x}"
            if generic:
                return [f"{generic[0]} = {generic[1]}  (at {where})"]
            return [f"rand() = {e.raw}  (at {where})"]
        return []

    def _thief_skill(self, e: Entry) -> List[str]:
        """A thief skill check (the game's routine at 803B8h): d100 under the skill's chance plus
        the situation's bonus. Its arguments are (character, skill, bonus); [BP-2] the chance.
        Effects change the bonus in place before the roll (Enlarge scales it; an effect that
        rules the skill out takes 1000 off), so the frame holds the bonus as it was used."""
        chance, roll = e.local(-2), e.raw % 100 + 1
        who, skill, bonus = e.arg(6), e.arg(8), e.arg(0x0C) or 0
        if chance is None or who is None or skill is None:
            return []
        name = game.THIEF_SKILLS[skill] if 0 <= skill < len(game.THIEF_SKILLS) else f"skill {skill}"
        head = f"{self._name(who)} tries to {name}: d100 = {roll}"
        if chance <= -500:  # the game takes 1000 off when an effect makes it impossible
            return [f"{head} -> failure (an effect stops it)"]
        head += f", needs {chance} or less -> {'success' if roll <= chance else 'failure'}"
        creature = self.game.combatant_creature(who)
        parts = self.game.thief_skill_parts(creature, skill) if creature is not None else None
        if parts is None:
            return [head]
        rest = chance - bonus - sum(n for _, n in parts)
        steps = [f"{n}" if what == "base" else f"{signed(n)} {what}" for what, n in parts]
        if bonus:
            steps.append(f"{signed(bonus)} this attempt")
        if rest:  # the only other part of the chance: the equipment penalty
            steps.append(f"{signed(rest)} equipment")
        return [head, f"    {name} {chance} = " + " ".join(steps).replace(" +", " + ").replace(" -", " - ")]

    # attacks ---------------------------------------------------------------------

    def _attack(self, e: Entry) -> List[str]:
        g = self.game
        d20 = scaled(e.raw, 20) + 1
        thac0, ac = e.arg(0x0A), e.arg(0x0C)
        attacker, sheet_item, item, item_type, mode = e.arg(0x0E), e.arg(0x10), e.arg(0x12), e.arg(0x14), e.arg(0x16)
        attacker_combatant, target_combatant = e.arg(0x18), e.glob[0]
        need = thac0 - ac
        hit = d20 == 20 or (d20 != 1 and d20 >= need)
        note = " (natural 20)" if d20 == 20 else " (natural 1)" if d20 == 1 else ""

        self._last_attacker = g.creature_name(attacker)
        target_index = g.combatant_creature(target_combatant)
        if target_index is not None:
            self.last_ac[target_index] = ac
        weapon = g.weapon(item, item_type)
        with_what = f" with {g.weapon_name(weapon)} ({weapon.dice()})" if weapon else ""
        target = g.combatant_name(target_combatant)
        # the attack's own arguments: [BP+1Eh] a backstab, [BP+20h] from behind
        how = " BACKSTAB" if e.arg(0x1E) and e.arg(0x20) else " from behind" if e.arg(0x20) else ""
        chance = hit_chance(need)
        needs = ("hits on anything but a 1" if need <= 2 else "only a 20 hits" if need > 20 else f"needs {need}+")
        head = (f"{g.creature_name(attacker)} attacks {target}{how}{with_what}: d20 = {d20}{note}, "
                f"{needs} ({chance}%), hits AC {thac0 - d20}, target AC {ac} -> {'HIT' if hit else 'miss'}")
        breakdown = self._thac0_breakdown(e, thac0, attacker, attacker_combatant, target_combatant, weapon, mode)
        self._turn_attacks.setdefault(attacker, []).append(
            {"target": target, "d20": d20, "need": need, "hit": hit, "damage": None})
        return [head, "    " + breakdown]

    def _thac0_breakdown(self, e: Entry, thac0: int, attacker: int, attacker_combatant: int,
                         target_combatant: int, weapon, mode: int) -> str:
        """'THAC0 16, +6 STR, +1 Blessed, ... = 9', from the attack setup's locals and the game's rules."""
        g = self.game
        base = g.creature(attacker)[CREATURE_THAC0]
        after_f1, hit_bonus = e.parent_local(-0x20), e.parent_local(-8)
        rear, backstab = e.parent_local(-0x1A), e.parent_local(-0x24)
        parts: List[Tuple[str, int]] = []
        if None in (after_f1, hit_bonus) or after_f1 - hit_bonus != thac0:
            return f"THAC0 {base} base, {signed(base - thac0)} in bonuses = {thac0}"
        if rear:
            parts.append(("from behind", 2))
        if backstab:
            parts.append(("backstab", 2))
        situational = base - after_f1 - 2 * bool(rear) - 2 * bool(backstab)
        # the spell effects the game checks here (from its code)
        effects = g.effects()
        on = lambda combatant, eid: any(x.owner == combatant and x.id == eid for x in effects)
        for eid, value in ((7, 1), (12, -1), (47, -4), (49, 1)):
            if on(attacker_combatant, eid):
                parts.append((EFFECT_NAMES[eid], value))
                situational -= value
        if on(target_combatant, 55):
            parts.append(("target's Blur", -2))
            situational += 2
        prayer = next((x for x in effects if x.owner == attacker_combatant and x.id == 73), None)
        if prayer:
            caster = g.combatant_creature(prayer.caster)
            same = caster is not None and g.creature(caster)[CREATURE_SIDE] == g.creature(attacker)[CREATURE_SIDE]
            parts.append(("Prayer", 1 if same else -1))
            situational -= 1 if same else -1
        if situational:
            parts.append(("STR" if mode <= 1 else "DEX", situational))
        rest = hit_bonus
        if weapon:
            if weapon.plus:
                parts.append(("weapon", weapon.plus))
                rest -= weapon.plus
            if not weapon.plus and not weapon.nonmagical_flag and weapon.material in MATERIAL_TO_HIT:
                penalty = MATERIAL_TO_HIT[weapon.material]
                parts.append((MATERIALS[weapon.material].lower(), penalty))
                rest -= penalty
        # With two weapons ready the game adjusts every melee attack by the DEX table it
        # also uses for initiative, sign flipped and never below 0 (rangers excepted): a
        # bonus at DEX 5 or less, nothing otherwise. The manual's off-hand penalty isn't there,
        # unless the companion's rule puts AD&D's in (GameData.two_weapons).
        weapons_ready = e.parent_local(-0x16)
        if mode <= 1 and weapons_ready is not None and weapons_ready >= 2:
            item = e.arg(0x12)
            slot = None
            if item is not None and 0 <= item < game.NO_ITEM:
                at = game.far_pointer(g.guest, g.ds, game.ITEMS_PTR) + item * game.ITEM_SIZE
                slot = g.guest.read(at + game.ITEM_SLOT, 1)[0]
            why, two_weapons = g.two_weapons(attacker, slot)
            if two_weapons:
                parts.append((why, two_weapons))
                rest -= two_weapons
        if attacker_combatant is not None and attacker_combatant >= 4:
            difficulty = g.difficulty() - 1
            if difficulty:
                parts.append(("difficulty", difficulty))
                rest -= difficulty
        if rest:
            parts.append(("off-hand and other", rest))
        text = ", ".join(f"{signed(v)} {name}" for name, v in parts if v)
        return f"THAC0 {base}" + (f", {text}" if text else "") + f" = {thac0}"

    def _dice_roll(self, e: Entry, show_all: bool, now: float) -> List[str]:
        weapon = e.parent_code.startswith(WEAPON_DAMAGE_RETURN)
        # Two routines roll NdS with this code; only the weapon one takes a bonus argument
        count, sides, bonus = e.arg(6), e.arg(8), e.arg(0x0A) if weapon else 0
        key = (e.ss, e.bp, e.cs, e.ip)
        faces = self._dice.setdefault(key, [])
        faces.append(scaled(e.raw, sides) + 1)
        if len(faces) < count:
            return []
        del self._dice[key]
        faces_text = "[" + " + ".join(map(str, faces)) + "]"
        if not weapon:
            if count == 1 and sides == 20 and self._is_save_roll(e):
                return self._save_roll(e, now)
            if count == 1 and sides == 10 and e.parent_code.startswith(SPECIAL_EFFECT_RETURN):
                target, attacker = e.parent_arg(6), e.parent_arg(8)
                return [f"    {self._name(attacker)}'s special effect on {self._name(target)}: d10 = {faces[0]}, "
                        f"works on a 1 -> {'it works' if faces[0] == 1 else 'no effect'}"]
            if e.parent_code.startswith(CREATION_ABILITY_RETURN):
                return self._creation_ability(e, sum(faces))
            if count == 1 and e.parent_code.startswith(LEVEL_HP_RETURN) and e.parent_arg(2) == CREATION_HP_CALLER:
                return self._creation_hp_roll(e, sides, faces[0], now)
            if count == 1 and any(e.parent_code.startswith(c) for c in RANDOM_NAME_RETURNS):
                return [f"Character creation: a name picked at random, 1d{sides} = {faces[0]}"]
            if count == 1:
                level_up = self._level_hp(e, sides, faces[0])
                if level_up:
                    return level_up
            if count == 1 and sides == 10 and e.parent_code.startswith(CONFUSION_ROLL_RETURN):
                what = next(text for top, text in CONFUSION_RESULTS if faces[0] <= top)
                return self.flush(now, force=True) + [
                    f"{self._name(e.parent_arg(6))} is confused: d10 = {faces[0]} -> {what}"]
            if count == 1 and sides == 2 and e.parent_code.startswith(RANDOM_SIDE_RETURN):
                side = "the party's" if faces[0] == 1 else "the monsters'"
                return [f"    {self._name(e.parent_arg(6))} fights on {side} side this turn (d2 = {faces[0]})"]
            if count == 1 and e.parent_code.startswith(STRENGTH_ROLL_RETURN) and e.parent_arg(0x0E) is not None:
                spell, target = e.parent_arg(0x0E), e.parent_arg(6)
                self._spell_cast(spell, now)
                # (Cat's Grace, in Flaming Sphere's place, uses Strength's code for DEX)
                ability = "DEX" if spell == game.FLAMING_SPHERE and self.rules & game.RULE_CATS_GRACE else "STR"
                return self.flush(now, force=True) + [
                    f"{self.game.spell_name(spell)}: 1d{sides} = {faces[0]} -> {self._name(target)}'s {ability} "
                    f"+{faces[0]} while it lasts (at most {STR_MOST})"]
            if count == 1 and sides == 100 and e.parent_code.startswith(RESISTANCE_ROLL_RETURN):
                return self._magic_resistance(e.parent_arg(6), e.parent_arg(8), faces[0])
            if count == 1 and sides == 100 and e.parent_code.startswith(DISPEL_ROLL_RETURN):
                return self._dispel(e, faces[0])
            if count == 1 and sides == 20 and e.parent_code.startswith(ABJURE_ROLL_RETURN):
                return self._abjure(e, faces[0])
            if count == 1 and e.parent_code.startswith(SUMMON_ROLL_RETURN):
                return [f"    Summoning: 1d{sides} = {faces[0]} picks which of its {sides} creatures comes"]
            if e.parent_code.startswith(CHARGE_USED_RETURN):
                who, eid = self._name(e.parent_arg(6)), e.parent_arg(8)
                if eid == ACID:
                    return self.flush(now, force=True) + [
                        f"    {EFFECT_NAMES[ACID]} on {who}: {count}d{sides} = {faces_text} = {sum(faces)} acid damage"]
                # the 2d4 means nothing here: a Stoneskin, Ironskin, Mirror Image... used a charge
                name = EFFECT_NAMES.get(eid, f"effect {eid}")
                return [f"    {name} on {who}: one charge used"]
            handler = next((bonus for code, bonus in SPELL_HANDLER_RETURNS if e.parent_code.startswith(code)), None)
            if handler is not None and e.parent_arg(0x0E) is not None:
                spell = e.parent_arg(0x0E)
                self._spell_cast(spell, now)
                total = sum(faces) + handler
                return self.flush(now, force=True) + [
                    f"{self.game.spell_name(spell)}: {count}d{sides} = [" + " + ".join(map(str, faces)) + "]"
                    + (f" {signed(handler)}" if handler else "") + f" = {total}"]
            if e.parent_code.startswith(SPELL_DURATION_RETURN) or self._overlay_duration(e, count, sides):
                return self._spell_duration(e, count, sides, faces)
            if e.parent_code.startswith(SPELL_DAMAGE_RETURN):
                self._spell_cast(e.parent_arg(6), now)
                return self.flush(now, force=True) + [self._spell_damage(e, count, sides, faces)]
            steps = self._missile_steps(e, count, sides)
            if steps is not None:
                self._spell_cast(e.parent_arg(6), now)
                return self.flush(now, force=True) + [self._spell_damage(e, count, sides, faces, steps)]
            if sides > 1:  # the game sometimes "rolls" 1d1
                pending = PendingDice(f"{count}d{sides} = {faces_text} = {sum(faces)}", now,
                                      damage=e.parent_code.startswith(SPELL_DAMAGE_RETURN))
                target, spell = e.parent_arg(6), e.parent_arg(8)
                if count == 1 and sides == 100 and target is not None and 1 <= spell < game.PSIONIC_FIRST + game.PSIONIC_COUNT \
                        and self.game.combatant_creature(target) is not None:
                    pending.resistance = (target, spell, faces[0])
                self._pending.append(pending)
            return []
        g = self.game
        attacker, mode = e.parent_arg(0x0E), e.parent_arg(0x16)
        total = max(sum(faces) + bonus, 1)
        steps = f"{count}d{sides} = {faces_text}" + (f" {signed(bonus)} weapon" if bonus else "")
        if sum(faces) + bonus < 1:
            steps += " (raised to the minimum of 1)"
        if mode is not None and mode <= 1:  # melee: the game adds the attacker's STR bonus
            strength = g.creature(attacker)[CREATURE_ABILITIES]
            str_bonus = STR_DAMAGE.get(strength, 0)
            if str_bonus:
                steps += f" {signed(str_bonus)} STR {strength}"
                total += str_bonus
        # a backstab (a thief attacking from right behind, see the THAC0 line) multiplies all of
        # that on the attacker's first attack of the round: x2, x3 from thief level 5, x4 from 9,
        # x5 from 13. The attack's frame: [BP+1Eh] backstab, [BP+20h] from behind, [BP-0Ah] the
        # attacks already made this round
        backstab, rear, made = e.parent_arg(0x1E), e.parent_arg(0x20), e.parent_local(-0x0A)
        if backstab and rear and made is not None and made <= 1:
            sheet = g.sheet(attacker)
            thief = [sheet[game.SHEET_LEVELS + i] for i in range(3) if sheet[game.SHEET_CLASSES + i] == THIEF]
            times = min(2 + (max(thief[0], 1) - 1) // 4, 5) if thief else 2
            total *= times
            steps = f"({steps}) x{times} backstab"
        target = g.combatant_creature(e.glob[0])
        if target is not None:  # so the HP it takes isn't put down to a spell being cast
            self._hit(target, total, now)
        last = next((a for a in reversed(self._turn_attacks.get(attacker, [])) if a["hit"] and a["damage"] is None),
                    None)
        line = f"{g.creature_name(attacker)} hits {g.combatant_name(e.glob[0])} for {total}: {steps}"
        if last is not None:  # for the turn's summary in the game
            last["damage"] = total
        return ["  " + line]

    def _overlay_duration(self, e: Entry, count: int, sides: int) -> bool:
        """The duration routine's roll when the overlay manager has swapped its return address
        for an INT 3Fh stub (so its code can't be matched): its arguments are still (spell,
        caster level), and the dice are the spell record's duration dice."""
        if not e.parent_code.startswith(OVERLAY_TRAP):
            return False
        spell, level = e.parent_arg(6), e.parent_arg(8)
        if spell is None or level is None or not 1 <= spell < game.PSIONIC_FIRST + game.PSIONIC_COUNT or not 1 <= level <= 40:
            return False
        rec = self.game.spell_record(spell)
        return len(rec) > 4 and (rec[4] & 0x0F, rec[4] >> 4) == (count, sides)

    def _spell_duration(self, e: Entry, count: int, sides: int, faces: List[int]) -> List[str]:
        g = self.game
        spell, level = e.parent_arg(6), (e.parent_arg(8) or 0) & 0xFF
        if spell is None:
            return []
        dice = f"{count}d{sides}" + (f" = [{' + '.join(map(str, faces))}]" if sides > 1 else "")
        found = g.spell_duration(spell, level, sum(faces))
        if found is not None:
            units, how = found
            return [f"    {g.spell_name(spell)} lasts {game.game_time(units)} (caster level {level}: {how}; "
                    f"dice {dice})"]
        charges = g.spell_charges(spell, level, sum(faces))
        if charges is not None:  # lasts until used up (blows taken, images struck...)
            count, how = charges
            return [f"    {g.spell_name(spell)} has {count} charge{'' if count == 1 else 's'} "
                    f"(caster level {level}: {how}; dice {dice})"]
        return []  # permanent until removed

    def _missile_steps(self, e: Entry, count: int, sides: int) -> Optional[int]:
        """Magic Missile, Flame Arrow, Minute Meteors: their damage is rolled by another routine,
        whose return address the overlay manager has taken, but the dice routine's own
        arguments name the spell (as does its caller's first). The steps of caster level the
        roll stands for, when the dice fit the spell's formula; else None."""
        if not e.parent_code.startswith(OVERLAY_TRAP):
            return None
        spell = e.arg(0x0C)
        if spell is None or spell != e.parent_arg(6) or not 1 <= spell < game.PSIONIC_FIRST + game.PSIONIC_COUNT:
            return None
        rule = self.game.spell_damage(spell)
        if rule is None or rule.sides != sides or sides < 2:
            return None
        if not rule.step_dice:  # fixed dice (Slay Living's 4d8)
            return 0 if count == rule.base_dice else None
        steps, extra = divmod(count - rule.base_dice, rule.step_dice)
        return steps if steps >= 1 and not extra else None

    def _spell_damage(self, e: Entry, count: int, sides: int, faces: List[int],
                      missile_steps: Optional[int] = None) -> str:
        """A spell's damage dice, rolled by the routine whose arguments are (spell, caster level):
        the game adds a flat bonus for each step of caster level."""
        g = self.game
        spell, level = e.parent_arg(6), (e.parent_arg(8) or 0) & 0xFF
        name = g.spell_name(spell) if spell is not None else "Spell"
        text = f"{name} damage: {count}d{sides} = [" + " + ".join(map(str, faces)) + "]"
        rule = g.spell_damage(spell) if spell is not None else None
        self._last_damage = (spell, sum(faces))
        if rule is None or rule.sides != sides:
            return f"{text} = {sum(faces)}"
        steps = rule.steps(level) if missile_steps is None else missile_steps
        bonus = rule.step_bonus * steps
        self._last_damage = (spell, sum(faces) + bonus)
        if bonus:
            text += f" {signed(bonus)}"
        text += f" = {sum(faces) + bonus}"
        per = (f"{rule.step_dice}d{sides}" if rule.step_dice else "") + \
            (f"{signed(rule.step_bonus)}" if rule.step_dice and rule.step_bonus else
             f"{rule.step_bonus}" if rule.step_bonus else "")
        if not per:
            return text
        unit = "caster level" if rule.per_levels == 1 else f"{rule.per_levels} caster levels"
        counted = min(level, game.SPELL_LEVEL_CAP) + rule.adjust
        how = f"{per} for each {unit}"
        if rule.adjust:
            how += f" (counting {signed(rule.adjust)})"
        base = f"{rule.base_dice}d{sides} + " if rule.base_dice else ""
        if missile_steps is not None:  # the caster's level isn't in this routine's arguments
            return f"{text} ({base}{how}, counted up to level {game.SPELL_LEVEL_CAP}: {steps})"
        cap = f", which counts as {game.SPELL_LEVEL_CAP}" if level > game.SPELL_LEVEL_CAP else ""
        return f"{text} ({base}{how}: {steps} at caster level {level}{cap})" if counted >= 0 else text

    # weapons breaking and levels ------------------------------------------------------

    def _break_check(self, e: Entry, first: bool, show_all: bool) -> List[str]:
        """After an attack the game checks the weapon: non-magical wood, bone, stone and
        obsidian break when a 0-7 roll and then a 0-19 roll both come up 0 (1 in 160)."""
        item, item_type = e.arg(6), e.arg(8)
        weapon = self.game.weapon(item, item_type)
        name = self.game.weapon_name(weapon) if weapon else "weapon"
        who = f"{self._last_attacker}'s " if self._last_attacker else ""
        if not self.game.item_breaks(item, item_type):
            return [f"    {who}{name} can't break"] if show_all and first else []
        if first:
            self._break_first = scaled(e.raw, 8)
            if self._break_first == 0 or show_all:
                return []  # wait for the second roll (there is one only if this was 0)
            return []
        second, first_roll, self._break_first = scaled(e.raw, 20), self._break_first, None
        if second == 0:
            return [f"    {who}{name} BREAKS: 0 on 0-7 and 0 on 0-19 (1 in 160 after each hit)"]
        return [f"    {who}{name} nearly broke: {first_roll if first_roll is not None else 0} on 0-7, "
                f"then {second} on 0-19 (needed 0)"]

    def _level_hp(self, e: Entry, sides: int, roll: int) -> List[str]:
        """The hit point roll of a new level: the caller's arguments are (party member, class, level)."""
        member, cls, level = e.parent_arg(6), e.parent_arg(8), e.parent_arg(0x0A)
        if member is None or not 0 <= member < game.PARTY_SIZE or cls is None or level is None:
            return []
        sheet = self.game.sheet(member)
        if len(sheet) < game.SHEET_SIZE:
            return []
        slots = [i for i in range(3) if sheet[game.SHEET_CLASSES + i] == cls]
        if not slots or sheet[game.SHEET_LEVELS + slots[0]] != level:
            return []
        rule = self.game.level_hp_rule(cls)
        if rule is None or rule.sides != sides:
            return []
        con = sheet[game.SHEET_ABILITIES + 2]
        text = f"d{sides} = {roll}"
        gained = roll
        minimum = self.game.level_hp_minimum(con)
        if minimum > roll:
            gained = minimum
            text += f", raised to {minimum} for CON {con}"
        if sheet[game.SHEET_RACE] == game.RACE_HALF_GIANT:
            gained *= 2
            text += f", doubled for a half-giant = {gained}"
        cls_name = game.CLASS_NAMES.get(cls, f"class {cls}")
        return [f"{self.game.creature_name(member)}'s {game.ordinal(level)} {cls_name} level: hit points {text}"]

    # character creation ----------------------------------------------------------------

    def _creation_ability(self, e: Entry, roll: int) -> List[str]:
        """One of the four 4d4 rolls for an ability; the line comes with the fourth."""
        ability, class_count = e.parent_arg(8), e.parent_arg(0x0E)
        if self._ability_of != ability:  # a new ability (or rolls went missing)
            self._ability_of, self._ability_tries = ability, []
        self._ability_tries.append(roll)
        if len(self._ability_tries) < CREATION_ABILITY_TRIES:
            return []
        tries, self._ability_tries, self._ability_of = self._ability_tries, [], None
        out = self.creation_hp_lines()  # the last character's, when the die is clicked again
        g = self.game
        if ability is None or not 0 <= ability < 6:
            return out + [f"Character creation: 4d4 four times: {', '.join(map(str, tries))}"]
        sheet = g.creation_sheet()
        race = sheet[game.SHEET_RACE]
        adjustment = g.race_adjustment(race, ability)
        best = max(tries)
        steps = f"best of four 4d4 ({', '.join(map(str, tries))}) = {best}, +4"
        value = best + 4 + adjustment
        if adjustment:
            steps += f", {signed(adjustment)} {game.RACE_NAMES.get(race, f'race {race}')}"
        steps += f" = {value}"
        classes = [sheet[game.SHEET_CLASSES + i] for i in range(min(max(class_count or 1, 1), 3))]
        minimums = [(g.class_minimum(c, ability), c) for c in classes if c]
        if minimums:
            least, cls = max(minimums)
            if value < least:
                name = game.CREATION_CLASS_NAMES.get(cls, f"class {cls}")
                why = "prime requisite" if least == game.CREATION_PRIME_MINIMUM else "least"
                steps += f", raised to {least} (the {name}'s {why})"
                value = least
        if ability == 2:
            self._creation_con = value
        return out + [f"Character creation, {ABILITIES[ability]} {value}: {steps}"]

    def _creation_hp_roll(self, e: Entry, sides: int, roll: int, now: float) -> List[str]:
        """A class level's hit point die on the creation screen: (sheet, class, level)."""
        index, cls, level = e.parent_arg(6), e.parent_arg(8), e.parent_arg(0x0A)
        sheet = self.game.sheet_at(index) if index is not None and index >= 0 else b""
        if len(sheet) < game.SHEET_SIZE or cls is None:
            return [f"Character creation: hit points d{sides} = {roll}"]
        text, gained = str(roll), roll
        con = sheet[game.SHEET_ABILITIES + 2]
        minimum = self.game.level_hp_minimum(con)
        if minimum > roll:
            text, gained = f"{roll} (raised to {minimum} for CON {con})", minimum
        if sheet[game.SHEET_RACE] == game.RACE_HALF_GIANT:
            gained *= 2
        self._creation_hp.append((index, cls, gained, text))
        self._creation_hp_at = now
        return []

    def creation_hp_lines(self) -> List[str]:
        """The new character's hit points, from the rolls collected. The game adds them up,
        divides by the number of classes (a dual-classed human counts one) and adds CON's
        bonus for each level that rolled: the full bonus for warriors, at most +2 for others."""
        rolls, self._creation_hp = self._creation_hp, []
        if not rolls:
            return []
        g = self.game
        index = rolls[-1][0]
        sheet = g.sheet_at(index)
        by_class: Dict[int, List[str]] = {}
        for _, cls, _, text in rolls:
            by_class.setdefault(cls, []).append(text)
        parts = []
        for cls, texts in by_class.items():
            rule = g.level_hp_rule(cls)
            die = f" d{rule.sides}" if rule else ""
            parts.append(f"{game.CLASS_NAMES.get(cls, f'class {cls}')}{die} per level: {' + '.join(texts)}")
        rolled = sum(r[2] for r in rolls)
        steps = "; ".join(parts)
        if len(sheet) < game.SHEET_SIZE:
            return [f"Character creation, hit points: {steps} = {rolled}"]
        if sheet[game.SHEET_RACE] == game.RACE_HALF_GIANT:
            steps = f"({steps}) x2 half-giant"
        steps += f" = {rolled}"
        classes = 1 if sheet[game.SHEET_RACE] == 1 else max(sum(1 for i in range(3) if sheet[game.SHEET_CLASSES + i]), 1)
        hp = rolled // classes
        if classes > 1:
            steps += f", / {classes} classes = {hp}" + (" (rounded down)" if rolled % classes else "")
        # CON's bonus counts levels that roll dice: a warrior's (group 1) at the full bonus, and
        # the rest of the highest class's up to +2
        con = self._creation_con if self._creation_con is not None \
            else g.creature(index)[CREATURE_ABILITIES + 2]
        bonus_per_level = g.level_hp_con_bonus(con)
        levels = {}
        for _, cls, _, _ in rolls:
            levels[cls] = levels.get(cls, 0) + 1
        warrior = max((n for c, n in levels.items() if g.level_hp_group(c) == 1), default=0)
        highest = max(levels.values())
        bonus = bonus_per_level * warrior + min(bonus_per_level, 2) * (highest - warrior)
        if bonus:
            hp += bonus
            steps += f", {signed(bonus)} CON {con} = {hp}"
        least = sum(levels.values())
        if hp < least:
            hp = least
            steps += f", raised to {least} (at least 1 per level)"
        return [f"Character creation, hit points {hp}: {steps}"]

    # saving throws -------------------------------------------------------------------

    def _is_save_roll(self, e: Entry) -> bool:
        """The dice routine's caller is the saving throw if its frame holds a far pointer to
        the target's creature record at [BP-1Eh] (set just before it rolls)."""
        target = e.parent_arg(6)
        index = self.game.combatant_creature(target) if target is not None else None
        off, seg = e.parent_local(-0x1E), e.parent_local(-0x1C)
        if index is None or off is None or seg is None:
            return False
        table = game.far_pointer(self.guest, self.game.ds, game.CREATURES_PTR)
        return (seg & 0xFFFF) * 16 + (off & 0xFFFF) == table + index * game.CREATURE_SIZE

    def _save_roll(self, e: Entry, now: float = 0.0) -> List[str]:
        """The d20 of a saving throw. A natural 1 or 20 ends the save here; otherwise the
        save probe reports the total."""
        natural = scaled(e.raw, 20) + 1
        spell, target, caster = e.parent_arg(0x0A), e.parent_arg(6), e.parent_arg(8)
        self._spell_cast(spell, now)
        needed = e.parent_locals[0x28 - 1]
        index = e.parent_local(-6)
        pending = self._flush_spell(spell)
        if natural in (1, 20):
            return pending + [self._save_line(target, caster, spell, index, natural, None, needed)]
        self._save_rolls[(e.ss, e.parent_bp)] = natural
        return pending

    def _save(self, e: Entry) -> List[str]:
        total, needed = e.raw & 0xFF, e.raw >> 8
        natural = self._save_rolls.pop((e.ss, e.bp), None)
        spell, target, caster = e.arg(0x0A), e.arg(6), e.arg(8)
        return self._flush_spell(spell) + [
            self._save_line(target, caster, spell, e.local(-6), natural, total, needed)]

    def _dispel(self, e: Entry, roll: int) -> List[str]:
        """One effect's chance against Dispel Magic."""
        g = self.game
        target, level, eid = e.parent_arg(6), (e.parent_arg(0x14) or 0) & 0xFF, e.parent_local(-2)
        if target is None or eid is None:
            return []
        name = EFFECT_NAMES.get(eid, f"effect {eid}")
        # the game weighs every effect of that kind on the target (usually one): each effect's level
        levels = []
        for effect, spell in g.effect_spells():
            if effect.owner == target and effect.id == eid:
                caster = g.combatant_creature(effect.caster)
                found = g.effect_caster_level(caster, spell) if caster is not None else None
                levels.append(found or 0)
        chance = 50 + 5 * level - 5 * sum(levels)
        against = f" - 5 x {sum(levels)} (its caster's level)" if levels else ""
        return [f"    Dispel Magic on {self._name(target)}'s {name}: d100 = {roll}, needs {chance} or less "
                f"(50 + 5 x {level}{against}) -> {'dispelled' if roll <= chance else 'stays'}"]

    def _abjure(self, e: Entry, roll: int) -> List[str]:
        g = self.game
        target, level = e.parent_arg(6), (e.parent_arg(0x14) or 0) & 0xFF
        creature = g.combatant_creature(target) if target is not None else None
        sheet = g.sheet(creature) if creature is not None else b""
        if len(sheet) < game.SHEET_SIZE:
            return [f"    Abjure: d20 = {roll}"]
        their = sheet[game.SHEET_LEVELS]
        need = 11 - level + their
        kind = sheet[game.SHEET_RACE]
        works = roll >= need
        result = ("sent away" if kind == ABJURE_KIND else "no effect: only summoned creatures can be sent away") \
            if works else "fails"
        return [f"    Abjure on {self._name(target)}: d20 = {roll}, needs {need} or more (11 - caster level {level} "
                f"+ its level {their}) -> {result}"]

    def _magic_resistance(self, target: int, spell: int, roll: int) -> List[str]:
        """The d100 the game rolls against a target's magic resistance before its saving throw."""
        g = self.game
        resistance = g.magic_resistance(target) or 0
        how = []
        # the game's rules (its routine at 7A4A1h): Mind Bar +75 against mind-affecting spells,
        # then Lower Resistance halves it
        on = {x.id for x in g.effects() if x.owner == target}
        if MIND_BAR in on and g.mind_affecting(spell):
            resistance += MIND_BAR_RESISTANCE
            how.append(f"+{MIND_BAR_RESISTANCE} Mind Bar")
        if LOW_RESISTANCE in on and resistance:
            resistance //= 2
            how.append("halved by Lower Resistance")
        if not resistance:  # the roll can't matter
            return []
        detail = f" ({', '.join(how)})" if how else ""
        return [f"{g.combatant_name(target)} magic resistance {resistance}%{detail} vs "
                f"{g.spell_name(spell)}: d100 = {roll} -> {'resisted' if roll < resistance else 'not resisted'}"]

    def _flush_spell(self, spell: int) -> List[str]:
        """Dice rolled just before a spell's saving throws belong to that spell."""
        name = self.game.spell_name(spell)
        out = []
        for p in self._pending:
            if p.resistance:
                out += self._magic_resistance(*p.resistance)
            else:
                out.append(f"{name}{' damage' if p.damage else ''}: {p.text}")
        self._pending.clear()
        return out

    def _save_line(self, target, caster, spell, index, natural, total, needed) -> str:
        g = self.game
        kind = SAVE_NAMES.get(index, "?")
        # a spell left on the ground (Grease, a cloud) makes its victims save with themselves as the caster
        source = f" from {g.combatant_name(caster)}" if caster != target else ""
        who = f"{g.combatant_name(target)} saves vs {g.spell_name(spell)}{source} ({kind})"
        if total is None:
            return f"{who}: d20 = {natural} (natural {natural}) -> {self._save_result(spell, natural == 20)}"
        if total >= 0x80:  # the game adds -100 / +100 for "can't save" / "always saves"
            total -= 0x100
        if total < -50:
            return f"{who}: cannot save"
        if total > 100:
            return f"{who}: saves automatically"
        rules = g.spell_rules(spell)
        steps, rolled = "d20", None
        if natural is not None:
            steps, rolled = f"d20 = {natural}", natural
            if rules and rules.doubles_roll:
                rolled = natural * 2
                steps += f", doubled against {rules.doubled_for} = {rolled}"
            parts = []
            if rules and rules.save_modifier:
                parts.append(f"{signed(rules.save_modifier)} spell")
            rest = total - rolled - (rules.save_modifier if rules else 0)
            try:
                known = g.save_modifiers(target, caster, spell, index)
            except (struct.error, IndexError, ValueError):
                known = []
            parts += [f"{signed(amount)} {why}" for amount, why in known]
            other = rest - sum(amount for amount, _ in known)
            if other:  # Dismissal weighs the levels; anything else the log doesn't know of
                parts.append(f"{signed(other)} " + ("levels (the target's less the caster's)"
                                                    if g.spell_name(spell) == "Dismissal" else "other"))
            if parts:
                steps += " " + " ".join(parts) + f" = {total}"
        else:
            steps += f" total {total}"
        chance = ""
        if natural is not None:
            doubled = bool(rules and rules.doubles_roll)
            chance = f" ({save_chance(needed - (total - (rolled or 0)), doubled)}% to save)"
        return f"{who}: {steps}, needs {needed}{chance} -> {self._save_result(spell, total >= needed)}"

    def _save_result(self, spell: int, saved: bool) -> str:
        """'saved' or 'failed', and what that does to the spell's damage: the amount from the
        damage roll just before (the game rolls each target's damage, then its save; resistances
        and protections can still lower it, which the HP line after shows)."""
        rule = self.game.spell_damage(spell)
        rolled = self._last_damage[1] if self._last_damage and self._last_damage[0] == spell else None
        if rule is None or rule.sides < 2:  # no damage dice (1d1 is the game's "none")
            return "saved" if saved else "failed"
        if not saved:
            return f"failed: full damage, {rolled}" if rolled is not None else "failed: full damage"
        if self.game.save_negates_damage(spell):
            return f"saved: no damage (not {rolled})" if rolled is not None else "saved: no damage"
        return f"saved: half damage, {rolled // 2} of {rolled}" if rolled is not None else "saved: half damage"

    # AC --------------------------------------------------------------------------------

    def _ac(self, e: Entry, show_all: bool) -> List[str]:
        """The end of the game's AC calculation: [BP-6] is the AC after armour (and spells that
        replace armour, such as Spirit Armor); SI adds DEX, when not attacked from behind,
        and spells."""
        target, rear = e.arg(6), e.arg(0x0A)
        index = self.game.combatant_creature(target) if target is not None else None
        ac = e.raw if e.raw < 0x8000 else e.raw - 0x10000
        if index is not None:
            self.last_ac[index] = ac
            sheet, rec = self.game.sheet(index), self.game.creature(index)
            armour = e.local(-6)
            if len(sheet) >= game.SHEET_SIZE and len(rec) >= game.CREATURE_SIZE and armour is not None:
                base = struct.unpack("b", sheet[game.SHEET_BASE_AC:game.SHEET_BASE_AC + 1])[0]
                dex = self.game.dex_ac(rec[CREATURE_ABILITIES + 1]) if not rear else 0
                self.ac_detail[index] = AcDetail(base, armour - base, dex, ac - armour - dex, ac)
        if show_all:
            return [f"AC of {self.game.combatant_name(target)} against {self.game.combatant_name(e.arg(8))}: {ac}"]
        return []

    # ability checks --------------------------------------------------------------------

    def _check(self, e: Entry, show_all: bool) -> List[str]:
        d20 = scaled(e.raw, 20) + 1
        ability = e.arg(0x0A)
        if not 0 <= ability < 6:
            return [f"Check: d20 = {d20}"] if show_all else []
        base = self.game.creature(e.arg(6))[CREATURE_ABILITIES + ability]
        seg, off = CHECK_MODS
        mod = struct.unpack("<b", self.guest.read((self.load_seg + seg) * 16 + off + e.arg(8), 1))[0]
        ok = d20 != 20 and d20 <= base + mod
        mod_text = f" {signed(mod)}" if mod else ""
        return [f"{self.game.creature_name(e.arg(6))} {ABILITIES[ability]} check: d20 = {d20}, "
                f"needs {base + mod} or less ({ABILITIES[ability]} {base}{mod_text}) "
                f"-> {'success' if ok else 'failure'}"]
