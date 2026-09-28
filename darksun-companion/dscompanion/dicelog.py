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

import re
import struct
import time
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, NamedTuple, Optional, Tuple

from . import game
from .game import (CONVENTIONAL_AND_UPPER, CREATURE_ABILITIES, CREATURE_SIDE, CREATURE_THAC0, EFFECT_NAMES,
                   EFFECT_RULES, MATERIAL_TO_HIT, MATERIALS, SAVE_NAMES, STR_DAMAGE, GameData)
from .guestmem import GuestMemory
from .textlog import KIND_MESSAGE, Dialogue, DialogueEntry, TextBuffer
from .tracker import PartyTracker

HDR_SIG = b"DSCLOGv6"
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
# DSCLOG only records calls whose calling code starts like one of these, so
# bursts of other randomness (animations) don't crowd out the rolls that
# matter: the "rand()*N/32768" rolls (attacks, checks, saves, damage dice)
# and the percentile check. The same list is built into DSCLOG.
SCALED_ROLL = b"\x66\x0f\xbf\xc0"  # movsx eax, ax
FILTERS = tuple(SCALED_ROLL + bytes.fromhex(h) for h in (
    "666bc0", "6669c0", "66c1e0", "660fbf56")) + (PERCENT_SITE[:8],)

KIND_ROLL, KIND_SAVE, KIND_AC = 0, 1, 2
THIEF = 17  # class number

EFFECT_INTERVAL = 0.25  # seconds between looks at the active effects
LOAD_SETTLE = 3.0  # seconds after the party changes (a game was loaded) when effects are not news
PENDING_SECONDS = 1.0  # how long dice wait to learn which spell they belong to


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
    other: int  # spells and the rest
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
        self._save_rolls: Dict[Tuple[int, int], int] = {}  # (SS, save frame BP) -> natural d20
        self._effects: Optional[Counter] = None
        self._party: Optional[bytes] = None
        self._party_changed_at = 0.0
        self._next_effect_check = 0.0
        self._names: Dict[int, str] = {}  # combatant -> name, for effects that end after a fight
        self._last_attacker = ""
        self._break_first: Optional[int] = None  # the 0-7 roll of a break check in progress
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
            if re.search(rb"DSCLOGv\d", low):
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
        self.tracker = PartyTracker(self.game)
        self.text = TextBuffer(self.guest.read, hdr)
        self.set_record_everything(self.record_everything)
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
        for rec in self.text.poll():
            if rec.kind == KIND_MESSAGE:
                if rec.text.strip():
                    out.append(f"Message: {' '.join(rec.text.split())}")
            else:
                self._dialogue += self.dialogue.add(rec, now)
        self._dialogue += self.dialogue.idle(now)
        if now >= self._next_effect_check:
            self._next_effect_check = now + EFFECT_INTERVAL
            out += self.effect_changes(now)
            if not self._party_check(now):
                out += self.tracker.check(now)
        out += self.flush(now)
        if self.missed:
            out.append(f"({self.missed} rolls came too fast to record)")
            self.missed = 0
        return out

    def speaker(self, portrait: Optional[int]) -> str:
        """Who a dialogue portrait belongs to, as far as is known."""
        if portrait is None:
            return "(no portrait)"
        if portrait == 0:
            return "Narration"  # the window shows an emblem, not a face
        return f"Portrait {portrait}"

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
            return self._describe(e, show_all, now)
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
        if e.kind == KIND_SAVE:
            return self._save(e)
        if e.kind == KIND_AC:
            return self._ac(e, show_all)
        code = e.code
        if code.startswith(ATTACK_SITE):
            return self.flush(now, force=True) + self._attack(e)
        if code.startswith(DICE_SITE):
            return self._dice_roll(e, show_all, now)
        if code.startswith(CHECK_SITE):
            return self.flush(now, force=True) + self._check(e, show_all)
        if code.startswith(BREAK_ROLL_1) or code.startswith(BREAK_ROLL_2):
            return self._break_check(e, code.startswith(BREAK_ROLL_1), show_all)
        if code.startswith(PERCENT_SITE):
            chance, roll = e.local(-2), e.raw % 100 + 1
            return [f"Percentile check: d100 = {roll}, needs {chance} or less "
                    f"-> {'success' if roll <= chance else 'failure'}"]
        if show_all:
            generic = generic_roll(code, e)
            where = f"{e.cs:04x}:{e.ip:04x}"
            if generic:
                return [f"{generic[0]} = {generic[1]}  (at {where})"]
            return [f"rand() = {e.raw}  (at {where})"]
        return []

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
        head = (f"{g.creature_name(attacker)} attacks {target}{how}{with_what}: d20 = {d20}{note}, "
                f"hits AC {thac0 - d20}, target AC {ac} -> {'HIT' if hit else 'miss'}")
        return [head, "    " + self._thac0_breakdown(e, thac0, attacker, attacker_combatant,
                                                     target_combatant, weapon, mode)]

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
                return self._save_roll(e)
            if count == 1 and sides == 10 and e.parent_code.startswith(SPECIAL_EFFECT_RETURN):
                target, attacker = e.parent_arg(6), e.parent_arg(8)
                return [f"    {self._name(attacker)}'s special effect on {self._name(target)}: d10 = {faces[0]}, "
                        f"works on a 1 -> {'it works' if faces[0] == 1 else 'no effect'}"]
            if count == 1:
                level_up = self._level_hp(e, sides, faces[0])
                if level_up:
                    return level_up
            if sides > 1:  # the game sometimes "rolls" 1d1
                pending = PendingDice(f"{count}d{sides} = {faces_text} = {sum(faces)}", now,
                                      damage=e.parent_code.startswith(SPELL_DAMAGE_RETURN))
                target, spell = e.parent_arg(6), e.parent_arg(8)
                if count == 1 and sides == 100 and target is not None and 1 <= spell <= game.SPELL_COUNT \
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
        return [f"  {g.creature_name(attacker)} hits {g.combatant_name(e.glob[0])} for {total}: {steps}"]

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

    def _save_roll(self, e: Entry) -> List[str]:
        """The d20 of a saving throw. A natural 1 or 20 ends the save here; otherwise the
        save probe reports the total."""
        natural = scaled(e.raw, 20) + 1
        spell, target, caster = e.parent_arg(0x0A), e.parent_arg(6), e.parent_arg(8)
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

    def _magic_resistance(self, target: int, spell: int, roll: int) -> List[str]:
        """The d100 the game rolls against a target's magic resistance before its saving throw."""
        resistance = self.game.magic_resistance(target) or 0
        if not resistance:  # the roll can't matter
            return []
        return [f"{self.game.combatant_name(target)} magic resistance {resistance}% vs "
                f"{self.game.spell_name(spell)}: d100 = {roll} -> {'resisted' if roll < resistance else 'not resisted'}"]

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
        who = f"{g.combatant_name(target)} saves vs {g.spell_name(spell)} from {g.combatant_name(caster)} ({kind})"
        if total is None:
            result = "saved" if natural == 20 else "failed"
            return f"{who}: d20 = {natural} (natural {natural}) -> {result}"
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
                steps += f", doubled for this spell = {rolled}"
            parts = []
            if rules and rules.save_modifier:
                parts.append(f"{signed(rules.save_modifier)} spell")
            rest = total - rolled - (rules.save_modifier if rules else 0)
            if rest:
                parts.append(f"{signed(rest)} {self._save_modifier_sources(target)}")
            if parts:
                steps += " " + " ".join(parts) + f" = {total}"
        else:
            steps += f" total {total}"
        return f"{who}: {steps}, needs {needed} -> {'saved' if total >= needed else 'failed'}"

    def _save_modifier_sources(self, target: int) -> str:
        """'modifiers', naming the target's effects the game counts in saving throws."""
        names = [EFFECT_NAMES[x.id] for x in self.game.effects()
                 if x.owner == target and x.id in EFFECT_RULES and "saves" in EFFECT_RULES[x.id]]
        return "modifiers" + (f" (incl. {', '.join(dict.fromkeys(names))})" if names else "")

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
