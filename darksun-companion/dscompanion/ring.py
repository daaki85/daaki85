"""The Ring +1: an item of the companion's own, on the dead prisoner in the arena.

The game has a plain "Ring" item type that nothing in it has a plus on. The dice log's
patched game makes a worn ring's plus better AC and saving throws (DSCLOG's PROBE_RING_AC
and PROBE_RING_SAVE), and this puts one Ring +1 in the body lying below the Tied-up
Prisoner, the way the game fills a container: an item from its free list, and for an empty
container an object ("thing") from that free list too. Once the party has it, the game keeps
and saves it like any other item.
"""

import struct
from typing import Optional

from . import game
from .game import GameData

REGION = 0x117C  # DS: the region the party is in (its RGNxx.GFF)
ARENA = 0x2A
BODY_TYPE = 108  # "Dead Body", a container: +08h the object its contents start at
BODY_AT = (741, 403)  # the dead prisoner, below the Tied-up Prisoner
NEAR = 8  # pixels
POSITIONS, POSITION_SIZE = 0x669D, 32  # DS: each object's x, y first
THING_COUNT = 0x208  # objects 0-519; 320-519 are handed out from a free list
FREE_THINGS, THINGS_USED = 0x4D72, 0x4C48  # DS: that list's first, and how many are out
FREE_ITEMS = 0x4D76  # DS: the first free item record (each names the next at +04h)
ITEM_CONTENTS = 0x08
# Its name: the game shows an item's name alone (its plus only when the name says it, as in
# "Sling +2"), so the ring gets a name of its own, in an entry of the game's name table that
# nothing uses (all zeros). The table is read from GPLDATA.GFF each time the game starts, so
# the companion writes the name whenever it looks (name_ring); without it, the name is blank.
NAME_ENTRY = 0x95
NAME = b"Ring +1"
# the game's own record for a Ring (from SEGOBJEX), not worn (slot 255), with a plus of 1
RING = bytes.fromhex("1cfa0000" "0f27" "f401" "0f27" "6600" "00000000" "06" "ff") + \
    struct.pack("<Hb", NAME_ENTRY, 1)
MESSAGE = "A Ring +1 (+1 AC, +1 on saves) is on the dead prisoner in the arena, below the Tied-up Prisoner."
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
    if any(entry):
        return False  # the game uses it after all
    gd.guest.write(at, want)
    return True


def place_ring(gd: GameData) -> Optional[str]:
    """In the arena, put a Ring +1 on the dead prisoner unless there is one already (there,
    with the party or anywhere else in the region). Returns a line for the log if it did."""
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
        if 0 <= index < game.NO_ITEM and struct.unpack_from("<H", it.item(index), game.ITEM_TYPE)[0] == BODY_TYPE:
            x, y = struct.unpack("<HH", gd.guest.read(gd.ds * 16 + POSITIONS + thing * POSITION_SIZE, 4))
            if abs(x - BODY_AT[0]) <= NEAR and abs(y - BODY_AT[1]) <= NEAR:
                body = index
    if body is None:
        return None
    # an item record, as the game's allocator hands one out
    ring = it.word(FREE_ITEMS)
    if ring >= game.NO_ITEM:
        return None
    free_thing = it.word(FREE_THINGS)
    contents, = struct.unpack_from("<H", it.item(body), ITEM_CONTENTS)
    if contents >= THING_COUNT and free_thing >= THING_COUNT:
        return None
    last = None
    if contents < THING_COUNT:
        for last, _ in it.chain(contents, inside=False):
            pass
        if last is None:
            return None  # not a list of items: leave it be
    ds = gd.ds * 16
    gd.guest.write(ds + FREE_ITEMS, it.item(ring)[game.ITEM_NEXT:game.ITEM_NEXT + 2])
    gd.guest.write(it.items + ring * game.ITEM_SIZE, RING)
    if last is not None:  # after what the body already holds
        gd.guest.write(it.items + last * game.ITEM_SIZE + game.ITEM_NEXT, struct.pack("<H", ring))
        return MESSAGE
    # an empty body: an object for its contents, as the game's allocator hands one out
    _, after = it.thing(free_thing)
    gd.guest.write(ds + FREE_THINGS, struct.pack("<H", after & 0xFFFF))
    gd.guest.write(ds + THINGS_USED, struct.pack("<H", it.word(THINGS_USED) + 1))
    gd.guest.write(it.things + free_thing * 3, struct.pack("<BH", game.THING_ITEM, ring))
    gd.guest.write(it.items + body * game.ITEM_SIZE + ITEM_CONTENTS, struct.pack("<H", free_thing))
    return MESSAGE
