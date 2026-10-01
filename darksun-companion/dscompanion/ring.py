"""The Ring +1: an item of the companion's own, on the Tied-up Prisoner in the arena.

The game has a plain "Ring" item type that nothing in it has a plus on. The dice log's
patched game makes a worn ring's plus better AC and saving throws (DSCLOG's PROBE_RING_AC
and PROBE_RING_SAVE), and once the Tied-up Prisoner has died this makes his body a container
with one Ring +1 in it, the way the game fills a container: an item and an object ("thing")
from the game's free lists. Once the party has it, the game keeps and saves it like any other
item.
"""

import struct
from typing import Optional

from . import game
from .game import GameData

REGION = 0x117C  # DS: the region the party is in (its RGNxx.GFF)
ARENA = 0x2A
# When the Tied-up Prisoner dies (cut from his bonds, or killed where he hangs), his script
# frees his creature and everything on it and puts two new items where he was: "Stakes" and
# his body, a "Dead Slave" of the game's scenery type, which can't be opened.
DEAD_SLAVE_NAME = 0xBB  # its name table entry
SCENERY_TYPE = 61
BODY_AT = (696, 392)  # where it lies
NEAR = 16  # pixels
BODY_TYPE = 108  # the type of a "Dead Body", a container: +08h the object its contents start at
POSITIONS, POSITION_SIZE = 0x669D, 32  # DS: each object's x, y first
THING_COUNT = 0x208  # objects 0-519; 320-519 are handed out from a free list
FREE_THINGS, THINGS_USED = 0x4D72, 0x4C48  # DS: that list's first, and how many are out
FREE_ITEMS = 0x4D76  # DS: the first free item record (each names the next at +04h)
ITEM_CONTENTS = 0x08
# Its name, in an entry of the game's name table that nothing uses (all zeros): the inventory
# screen shows the name alone, the box an item's Look opens shows it with the plus after it
# ("%Fs%+d": "Ring/Protection+1"). The table is read from GPLDATA.GFF each time the game
# starts, so the companion writes the name whenever it looks (name_ring); without it, the name
# is blank.
NAME_ENTRY = 0x95
NAME = b"Ring/Protection"  # the game's own way of shortening ("Helm/Contempltn")
OLD_NAMES = (b"Ring +1", b"Ring of Protection")  # what earlier versions called it
# The box an item's Look opens is only so wide: the game's own names are at most 15 letters
# long (with its plus after them), and longer ones run out of it
NAME_FIT = 15
# The items the rule changes make better, named for it while the rule is on (the game shows
# no description of an item, only its name): entry, the game's own name, rule, what it gives
RULE_NAMES = ((6, "Helm", game.RULE_HELMS, " (AC 1)"), (145, "Dapartea's Helm", game.RULE_HELMS, " (AC 1)"),
              (107, "Helm/Contempltn", game.RULE_HELMS, " (AC 1)"), (236, "Helm of Might", game.RULE_HELMS, " (AC 1)"),
              (43, "Boots", game.RULE_BOOTS, " (+1 Move)"), (286, "Serpent Boots", game.RULE_BOOTS, " (+1 Move)"))
# the game's own record for a Ring (from SEGOBJEX), not worn (slot 255), with a plus of 1
RING = bytes.fromhex("1cfa0000" "0f27" "f401" "0f27" "6600" "00000000" "06" "ff") + \
    struct.pack("<Hb", NAME_ENTRY, 1)
MESSAGE = "The Tied-up Prisoner's body holds a Ring of Protection +1 (+1 AC, +1 on saves)."
MAX_ITEMS = 200  # items followed before giving up (a damaged list)


class Items:
    def __init__(self, gd: GameData):
        self.gd, self.guest = gd, gd.guest
        self.things = (gd.load_seg + game.COMBATANTS_SEG) * 16 + game.COMBATANTS_OFF
        self.items = game.far_pointer(self.guest, gd.ds, game.ITEMS_PTR)
        self.table = self.guest.read(self.things, THING_COUNT * 3)

    def thing(self, index: int):
        return struct.unpack_from("<Bh", self.table, index * 3)

    def item(self, index: int) -> bytes:
        return self.guest.read(self.items + index * game.ITEM_SIZE, game.ITEM_SIZE)

    def word(self, offset: int) -> int:
        return struct.unpack("<H", self.guest.read(self.gd.ds * 16 + offset, 2))[0]

    def chain(self, thing: int, inside: bool = True):
        """The item numbers and records in the list starting at object `thing`, and (`inside`)
        in any containers in it."""
        if not 0 <= thing < THING_COUNT:
            return
        kind, index = self.thing(thing)
        if kind != game.THING_ITEM:
            return
        for _ in range(MAX_ITEMS):
            if not 0 <= index < game.NO_ITEM:
                return
            rec = self.item(index)
            yield index, rec
            contents, = struct.unpack_from("<H", rec, ITEM_CONTENTS)
            if inside and contents < THING_COUNT:
                yield from self.chain(contents)
            index, = struct.unpack_from("<h", rec, game.ITEM_NEXT)


def is_ring(rec: bytes) -> bool:
    return struct.unpack_from("<H", rec, game.ITEM_TYPE)[0] == game.RING_TYPE and \
        struct.unpack("b", rec[game.ITEM_PLUS:game.ITEM_PLUS + 1])[0] > 0


def name_ring(gd: GameData) -> bool:
    """Give the ring its name in the game's name table, if that entry is still free. True if
    the entry holds the name."""
    at = game.far_pointer(gd.guest, gd.ds, game.ITEM_NAMES_PTR) + NAME_ENTRY * game.ITEM_NAME_SIZE
    entry = gd.guest.read(at, game.ITEM_NAME_SIZE)
    want = NAME.ljust(game.ITEM_NAME_SIZE, b"\0")
    if entry == want:
        return True
    if any(entry) and entry.split(b"\0", 1)[0] not in OLD_NAMES:
        return False  # the game uses it after all
    gd.guest.write(at, want)
    return True


def name_items(gd: GameData, rules: int) -> None:
    """Name the helms and boots for what the rule changes give them ("Helm (AC 1)"), or back to
    the game's own names with the rules off. Names that would be too long for the Look box stay
    the game's own; entries that hold anything else are left alone."""
    table = game.far_pointer(gd.guest, gd.ds, game.ITEM_NAMES_PTR)
    for entry, own, rule, extra in RULE_NAMES:
        at = table + entry * game.ITEM_NAME_SIZE
        text = gd.guest.read(at, game.ITEM_NAME_SIZE).split(b"\0", 1)[0].decode("cp437", "replace")
        if text not in (own, own + extra):
            continue
        want = own + extra if rules & rule and len(own + extra) <= NAME_FIT else own
        if text != want:
            gd.guest.write(at, want.encode("cp437").ljust(game.ITEM_NAME_SIZE, b"\0"))


def place_ring(gd: GameData) -> Optional[str]:
    """In the arena, once the Tied-up Prisoner has died (freed, or killed where he hangs), make
    his body a container with a Ring +1 in it, unless there is a Ring +1 already (with the
    party or anywhere else in the region). Returns a line for the log if it did."""
    it = Items(gd)
    if it.word(REGION) != ARENA:
        return None
    body = None
    for thing in range(THING_COUNT):
        kind, index = it.thing(thing)
        if kind != game.THING_ITEM:
            continue
        for _, rec in it.chain(thing):
            if is_ring(rec):
                return None
        if not 0 <= index < game.NO_ITEM:
            continue
        rec = it.item(index)
        name, = struct.unpack_from("<H", rec, game.ITEM_NAME)
        kind_of, = struct.unpack_from("<H", rec, game.ITEM_TYPE)
        contents, = struct.unpack_from("<H", rec, ITEM_CONTENTS)
        if name == DEAD_SLAVE_NAME and kind_of == SCENERY_TYPE and contents >= THING_COUNT:
            x, y = struct.unpack("<HH", gd.guest.read(gd.ds * 16 + POSITIONS + thing * POSITION_SIZE, 4))
            if abs(x - BODY_AT[0]) <= NEAR and abs(y - BODY_AT[1]) <= NEAR:
                body = index
    if body is None:
        return None  # he's alive still (or his body is a container already)
    # an item record and an object for it, as the game's allocators hand them out
    ring, free_thing = it.word(FREE_ITEMS), it.word(FREE_THINGS)
    if ring >= game.NO_ITEM or free_thing >= THING_COUNT:
        return None
    ds = gd.ds * 16
    _, after = it.thing(free_thing)
    gd.guest.write(ds + FREE_ITEMS, it.item(ring)[game.ITEM_NEXT:game.ITEM_NEXT + 2])
    gd.guest.write(it.items + ring * game.ITEM_SIZE, RING)
    gd.guest.write(ds + FREE_THINGS, struct.pack("<H", after & 0xFFFF))
    gd.guest.write(ds + THINGS_USED, struct.pack("<H", it.word(THINGS_USED) + 1))
    gd.guest.write(it.things + free_thing * 3, struct.pack("<BH", game.THING_ITEM, ring))
    rec = it.items + body * game.ITEM_SIZE
    gd.guest.write(rec + ITEM_CONTENTS, struct.pack("<H", free_thing))
    gd.guest.write(rec + game.ITEM_TYPE, struct.pack("<H", BODY_TYPE))
    return MESSAGE
