"""Picking pockets: the party leader, a thief, tries the pocket of whoever they're talking to.

The game has one pickpocket of its own, the Trustee's key in the slave pens, in his script.
With the dice log's patched game, P in any conversation (DSCLOG's PROBE_PICK) has the Ledger
roll the leader's pick pockets chance as it stands now (thief_skills_now). On a success the
thief lifts one small thing (weight 10 or less, and nothing worn on the body) from the
person into the backpack. On a failure, a move silently roll decides whether they got away
unnoticed. A thief can go on trying the same person until caught (both rolls failed) or
until they have nothing left worth taking; after that, their pockets are out of reach.
"""

import random
import struct
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from . import game, ring
from .game import GameData

PICK_POCKETS, MOVE_SILENTLY = 0, 3  # thief skill numbers
BACKPACK = range(13, 27)  # the backpack's cells (0-12 are what's worn or held)
TYPE_WEIGHT, TYPE_WORN = 0x04, 0x09  # in an item type's record: its weight; where it's worn
MAX_WEIGHT = 10  # a bag, a quiver of arrows: pocket-sized (a long sword is 30, a helm 15)
# where on the body (TYPE_WORN) things can't be lifted from: chest, belt, arms, feet, head,
# cloak, legs (a pair of boots weighs 1). Hands (a dagger), fingers, neck and ammunition can.
ON_THE_BODY = (0x01, 0x02, 0x03, 0x04, 0x06, 0x08, 0x0A)
SCENERY = 0x60  # in its +08h: doors, haystacks, walls...
OWN_POCKETS = ("Trustee",)  # people whose script has its own pickpocket
MAX_ITEMS = 200


@dataclass
class Attempt:
    text: str  # for the game's dialogue window
    log: List[str]  # for the dice log
    key: Optional[str] = None  # the person's pockets, now out of reach (the thief was caught)


def _skill(gd: GameData, member: int, name: str) -> Optional[int]:
    return next((n for skill, n in gd.thief_skills_now(member) if skill == name), None)


def _chain(it: ring.Items, thing: int) -> List[Tuple[int, bytes]]:
    """The item numbers and records of one list (not what's inside containers)."""
    return list(it.chain(thing, inside=False))


def _carried(gd: GameData, it: ring.Items, creature: int) -> List[Tuple[int, int, int]]:
    """What a thief can lift from a creature: (list, item, the item before it or -1). People
    outside the party keep everything in backpack cells, what they wear and wield too, so it
    goes by the item's type: MAX_WEIGHT or less, nothing worn ON_THE_BODY, no keys (scripts
    may need them) and no scenery."""
    rec = gd.creature(creature)
    out = []
    for list_no, offset in enumerate(game.CREATURE_ITEM_LISTS):
        thing, = struct.unpack_from("<h", rec, offset)
        before = -1
        for item, data in _chain(it, thing):
            typ = gd.item_type_record(data)
            name = gd.item_name(struct.unpack_from("<H", data, game.ITEM_NAME)[0])
            if len(typ) == game.ITEM_TYPE_SIZE and typ[TYPE_WORN] not in ON_THE_BODY \
                    and struct.unpack_from("<H", typ, TYPE_WEIGHT)[0] <= MAX_WEIGHT \
                    and typ[0x08] & SCENERY != SCENERY and "key" not in name.lower():
                out.append((list_no, item, before))
            before = item
    return out


def _free_cell(gd: GameData, it: ring.Items, member: int) -> Optional[int]:
    used = set()
    rec = gd.creature(member)
    for offset in game.CREATURE_ITEM_LISTS:
        thing, = struct.unpack_from("<h", rec, offset)
        used.update(data[game.ITEM_SLOT] for _, data in _chain(it, thing))
    return next((cell for cell in BACKPACK if cell not in used), None)


def _take(gd: GameData, it: ring.Items, creature: int, list_no: int, item: int, before: int) -> None:
    """Unlink ITEM from the creature's list (freeing the list's object if it was the only one)."""
    ds = gd.ds * 16
    offset = game.CREATURE_ITEM_LISTS[list_no]
    base = game.far_pointer(gd.guest, gd.ds, game.CREATURES_PTR) + creature * game.CREATURE_SIZE
    thing, = struct.unpack_from("<h", gd.creature(creature), offset)
    after = it.item(item)[game.ITEM_NEXT:game.ITEM_NEXT + 2]
    if before >= 0:
        gd.guest.write(it.items + before * game.ITEM_SIZE + game.ITEM_NEXT, after)
    elif struct.unpack("<h", after)[0] >= 0 and struct.unpack("<H", after)[0] != game.NO_ITEM:
        gd.guest.write(it.things + thing * 3 + 1, after)  # the list now starts at the next one
    else:  # it was all the list held: the list's object goes back on the free list
        gd.guest.write(it.things + thing * 3, struct.pack("<BH", 0, it.word(ring.FREE_THINGS)))
        gd.guest.write(ds + ring.FREE_THINGS, struct.pack("<H", thing))
        gd.guest.write(ds + ring.THINGS_USED, struct.pack("<H", max(0, it.word(ring.THINGS_USED) - 1)))
        gd.guest.write(base + offset, struct.pack("<H", game.NO_ITEM))


def _give(gd: GameData, it: ring.Items, member: int, item: int, cell: int) -> bool:
    """Put ITEM first in one of the party member's lists, in backpack cell CELL."""
    ds = gd.ds * 16
    base = game.far_pointer(gd.guest, gd.ds, game.CREATURES_PTR) + member * game.CREATURE_SIZE
    rec = gd.creature(member)
    at = it.items + item * game.ITEM_SIZE
    gd.guest.write(at + game.ITEM_SLOT, bytes((cell,)))
    for offset in game.CREATURE_ITEM_LISTS:
        thing, = struct.unpack_from("<h", rec, offset)
        if 0 <= thing < ring.THING_COUNT and it.thing(thing)[0] == game.THING_ITEM:
            first = struct.pack("<h", it.thing(thing)[1])
            gd.guest.write(at + game.ITEM_NEXT, first)
            gd.guest.write(it.things + thing * 3 + 1, struct.pack("<H", item))
            return True
    for offset in game.CREATURE_ITEM_LISTS:  # no list yet: one, as the game's allocator gives it
        thing, = struct.unpack_from("<h", rec, offset)
        if thing != game.NO_ITEM:
            continue
        free = it.word(ring.FREE_THINGS)
        if free >= ring.THING_COUNT:
            return False
        gd.guest.write(ds + ring.FREE_THINGS, struct.pack("<H", it.thing(free)[1] & 0xFFFF))
        gd.guest.write(ds + ring.THINGS_USED, struct.pack("<H", it.word(ring.THINGS_USED) + 1))
        gd.guest.write(it.things + free * 3, struct.pack("<BH", game.THING_ITEM, item))
        gd.guest.write(at + game.ITEM_NEXT, struct.pack("<H", game.NO_ITEM))
        gd.guest.write(base + offset, struct.pack("<H", free))
        return True
    return False


def attempt(gd: GameData, tried: set, roll: Callable[[], int] = lambda: random.randint(1, 100)) -> Optional[Attempt]:
    """P pressed in a conversation: the leader tries the pocket of whoever is talked to. None
    when no one is (a narration, or someone in the party)."""
    who = gd.talk_target_creature()
    if who is None:
        return None
    npc = gd.creature_name(who)
    leader = gd.whose_turn()
    if not 0 <= leader < game.PARTY_SIZE:
        return None
    thief = gd.creature_name(leader)
    chance = _skill(gd, leader, "pick pockets")
    if chance is None:
        return Attempt(f"{thief} is no thief.", [])
    if npc in OWN_POCKETS:
        return Attempt(f"(Try the {npc}'s pocket with what you say to him.)", [])
    key = f"{gd.creature_name(0)}|{gd.region()}|{who}|{npc}"  # (the party's first name: another game's)
    if key in tried:
        return Attempt(f"{npc} keeps a hand on their pockets since catching {thief}.", [])
    it = ring.Items(gd)
    cell = _free_cell(gd, it, leader)
    if cell is None:
        return Attempt(f"{thief}'s backpack is full.", [])
    d100 = roll()
    lines = [f"{thief} picks {npc}'s pocket: d100 = {d100}, needs {chance} or less -> "
             + ("success" if d100 <= chance else "failed")]
    if d100 <= chance:
        loot = _carried(gd, it, who)
        if not loot:  # nothing to lift: this was the last try on them
            text = f"{thief} deftly searches {npc}'s pockets, but finds nothing worth taking."
            lines.append("  " + text)
            return Attempt(text, lines, key)
        else:
            list_no, item, before = random.choice(loot)
            data = it.item(item)
            name = gd.item_label(data, gd.item_type_record(data))
            _take(gd, it, who, list_no, item, before)
            if not _give(gd, ring.Items(gd), leader, item, cell):
                return Attempt(f"{thief} can't take anything now.", lines)
            text = f"{thief} lifts {name} from {npc} unnoticed."
        lines.append("  " + text)
        return Attempt(text, lines)  # free to try again
    quiet = _skill(gd, leader, "move silently") or 0
    d100 = roll()
    lines.append(f"  {thief} moves silently to get away: d100 = {d100}, needs {quiet} or less -> "
                 + ("success" if d100 <= quiet else "failed"))
    if d100 <= quiet:
        text = f"{thief} fumbles {npc}'s pockets, but slips away unnoticed."
        lines.append("  " + text)
        return Attempt(text, lines)  # free to try again
    text = f"{npc} catches {thief}'s hand! {npc} won't let {thief} near again."
    lines.append("  " + text)
    return Attempt(text, lines, key)
