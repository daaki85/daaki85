"""The cooked vulture: a meal at last.

Hitting the arena's vulture knocks its feathers off (a plucked vulture), and the slave pens'
campfire cooks it, but nothing in the game ever uses the cooked vulture. With the Ledger, Dinos
(the pens' fine cook) is asked about it in his talk while the party carries it ("We cooked the
vulture from the arena.", pensasks.py): he takes it, shows them how to prepare it properly and
they eat it together, with the sound of a quest done. His script sets the Ledger's flag MEAL, on
which the Ledger gives each party member XP_REWARD XP and restores them as after a full rest (HP,
PSP and spell slots), once (EATEN).

Eaten by the party themselves (used on one of them, DSCLOG's PROBE_USE_ITEM), it is no use.
"""

import struct
from typing import List, NamedTuple, Optional

from . import game
from .game import GameData

COOKED_PICTURE, TYPE = 0xF5B4, 60  # the cooked vulture (object A4Ch); small things carried
COOKED = 0xA4C  # (its object, as the campfire's script makes it)
MEAL, EATEN = 780, 781  # (the Ledger's flags) set by Dinos's script; the reward given
OWN_NAME = 0x101  # the game's "Vulture"
XP_REWARD = 100
SHEET_MAX_PSP = 0x0C
STATUS_DEAD = 5
DOWN = (2, 3, 4)  # Stunned, Out Cold, Dying: up again after the meal

MEAL_TEXT = ("A vulture! Give it here. A little salt, some agafari leaf, slow over the coals... Sit, "
             "eat with me: the best meal in the pens!")
REWARD = f"For sharing the vulture with Dinos, each of you earns {XP_REWARD} EXP, and you are fully rested."


class Use(NamedTuple):
    text: str  # for the game's message window
    log: List[str]  # for the dice log
    used_up: bool = False  # the vulture is gone (eaten)


def is_vulture(rec: bytes) -> bool:
    """The cooked vulture (by its picture and type)."""
    return len(rec) >= game.ITEM_SIZE and struct.unpack_from("<H", rec, 0)[0] == COOKED_PICTURE \
        and struct.unpack_from("<H", rec, game.ITEM_TYPE)[0] == TYPE


def _sheet_at(gd: GameData, member: int) -> int:
    index, = struct.unpack_from("<H", gd.creature(member), game.CREATURE_SHEET_INDEX)
    return game.far_pointer(gd.guest, gd.ds, game.SHEETS_PTR) + index * game.SHEET_SIZE


def _party(gd: GameData) -> List[int]:
    """The party members there are, alive."""
    out = []
    for member in range(game.PARTY_SIZE):
        rec = gd.creature(member)
        if len(rec) >= game.CREATURE_SIZE and rec[game.CREATURE_NAME] and rec[game.CREATURE_STATUS] != STATUS_DEAD:
            out.append(member)
    return out


def rest(gd: GameData, member: int) -> None:
    """As after a full rest: HP and PSP to their most, the spell slots full (as the game fills
    them), up again if down."""
    at = game.far_pointer(gd.guest, gd.ds, game.CREATURES_PTR) + member * game.CREATURE_SIZE
    sheet = gd.sheet(member)
    hp, psp = struct.unpack_from("<hh", sheet, game.SHEET_MAX_HP)[0], struct.unpack_from("<h", sheet, SHEET_MAX_PSP)[0]
    gd.guest.write(at, struct.pack("<hh", hp, max(psp, 0)))
    if gd.creature(member)[game.CREATURE_STATUS] in DOWN:
        gd.guest.write(at + game.CREATURE_STATUS, bytes([game.STATUS_OKAY]))
    for kind_name, bit in game.MAGIC_KINDS:
        slots = bytes(min(255, gd.max_spell_slots(member, bit, level)) for level in range(1, game.SPELL_LEVELS + 1))
        gd.guest.write(gd.ds * 16 + game.SLOTS_LEFT[kind_name] + member * game.SLOTS_STRIDE + 1, slots)


def eat(gd: GameData) -> List[str]:
    """Each party member there is, alive: XP_REWARD XP and a full rest. For the dice log."""
    party = _party(gd)
    for member in party:
        at = _sheet_at(gd, member)
        xp, = struct.unpack("<I", gd.guest.read(at + game.SHEET_XP, 4))
        gd.guest.write(at + game.SHEET_XP, struct.pack("<I", xp + XP_REWARD))
        rest(gd, member)
    names = ", ".join(gd.creature_name(m) for m in party)
    return [f"Dinos cooks the vulture and the party eats with him: {names} +{XP_REWARD} XP each, "
            "and restored as after a full rest (HP, PSP and spell slots)"]


def meal(gd: GameData) -> List[str]:
    """Once Dinos's script has set MEAL: the reward, once (EATEN)."""
    if not gd.flag(MEAL) or gd.flag(EATEN):
        return []
    gd.set_flag(EATEN)
    return eat(gd)


def use(gd: GameData, rec: bytes, target: int, fighting: bool = False) -> Optional[Use]:
    """The item (its record `rec`) on the pointer used on creature `target`: what comes of it, or
    None when it isn't the cooked vulture or nothing does (the game goes on as usual: on Dinos
    too, who is asked about it in his talk)."""
    if not is_vulture(rec):
        return None
    if target < game.PARTY_SIZE:
        return Use("The cooked vulture is tough and bland: hardly worth the chewing. Someone in the pens "
                   "might know how to make a meal of it.", [])
    return None
