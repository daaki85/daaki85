"""The Ring +1: an item of the companion's own, on the Tied-up Prisoner in the arena.

The game has a plain "Ring" item type that nothing in it has a plus on. The dice log's
patched game makes a worn ring's plus better AC and saving throws (DSCLOG's PROBE_RING_AC
and PROBE_RING_SAVE). When the Tied-up Prisoner dies (cut from his bonds, or killed where he
hangs), the game leaves his body, which can't be opened: looking at it, the arena's script
says "There is nothing on the body." While the ring is still to be found, the Ledger has
DSCLOG show SEARCH_TEXT instead of that line (its text swap), and then puts the ring in the
leader's backpack (give_ring): an item record from the game's free list. Once the party has
it, the game keeps and saves it like any other item.
"""

import struct
from typing import Optional

from . import game
from .game import GameData

REGION = 0x117C  # DS: the region the party is in (its RGNxx.GFF)
ARENA = 0x2A
NOTHING = "There is nothing on the body."  # the arena script's line for his body
SEARCH_TEXT = ("Searching the body, you find a ring sewn into his loincloth: a Ring of Protection +1 "
               "(+1 AC, +1 on saves).")
POSITIONS, POSITION_SIZE = 0x669D, 32  # DS: each object's x, y first
THING_COUNT = 0x208  # objects 0-519; 320-519 are handed out from a free list
FREE_THINGS, THINGS_USED = 0x4D72, 0x4C48  # DS: that list's first, and how many are out
FREE_ITEMS = 0x4D76  # DS: the first free item record (each names the next at +04h)
ITEM_CONTENTS = 0x08
# Its name, in the first of the entries DSCLOG adds after the game's 322 (names.py): the
# inventory screen shows the name alone, the box an item's Look opens shows it with the plus
# after it ("%Fs%+d": "Ring/Protection+1").
NAME_ENTRY = 0x142
NAME = b"Ring/Protection"  # the game's own way of shortening ("Helm/Contempltn")
# The box an item's Look opens is only so wide: the game's own names are at most 15 letters
# long (with its plus after them), and longer ones run out of it
NAME_FIT = 15
# The items the rule changes make better, named for it while the rule is on (the game shows
# no description of an item, only its name): entry, the game's own name, rule, what it gives
RULE_NAMES = ((6, "Helm", game.RULE_HELMS, " (AC 1)"), (145, "Dapartea's Helm", game.RULE_HELMS, " (AC 1)"),
              (107, "Helm/Contempltn", game.RULE_HELMS, " (AC 1)"), (236, "Helm of Might", game.RULE_HELMS, " (AC 1)"),
              (43, "Boots", game.RULE_BOOTS, " (+1 Move)"), (286, "Serpent Boots", game.RULE_BOOTS, " (+1 Move)"))
# the game's own record for a Ring (from SEGOBJEX), not worn (slot 255), with a plus of 1
VALUE = 5000  # its price (the game's Ring's 500, made a magic ring's)
RING = bytes.fromhex("1cfa0000" "0f27") + struct.pack("<H", VALUE) + bytes.fromhex("0f27" "6600" "00000000" "06" "ff") + \
    struct.pack("<Hb", NAME_ENTRY, 1)
MESSAGE = "{who} takes the Ring of Protection +1 (+1 AC, +1 on saves) from the Tied-up Prisoner's body."
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


def ring_needed(gd: GameData) -> bool:
    """In the arena, with no Ring +1 there yet (with the party or anywhere else in the region)."""
    it = Items(gd)
    if it.word(REGION) != ARENA:
        return False
    for thing in range(THING_COUNT):
        if it.thing(thing)[0] == game.THING_ITEM and any(is_ring(rec) for _, rec in it.chain(thing)):
            return False
    return True


def give_ring(gd: GameData) -> Optional[str]:
    """The ring, into the leader's backpack (or the first in the party with room). A line for
    the log, or None if there was no room or no item record to be had."""
    from . import pickpocket
    it = Items(gd)
    leader = gd.whose_turn()
    order = ([leader] if leader is not None and 0 <= leader < game.PARTY_SIZE else []) + list(range(game.PARTY_SIZE))
    for member in order:
        rec = gd.creature(member)
        if len(rec) < game.CREATURE_SIZE or not rec[game.CREATURE_NAME]:
            continue
        cell = pickpocket.free_cell(gd, it, member)
        item = it.word(FREE_ITEMS)
        if cell is None or item >= game.NO_ITEM:
            continue
        gd.guest.write(gd.ds * 16 + FREE_ITEMS, it.item(item)[game.ITEM_NEXT:game.ITEM_NEXT + 2])
        gd.guest.write(it.items + item * game.ITEM_SIZE, RING)
        if pickpocket.give(gd, Items(gd), member, item, cell):
            return MESSAGE.format(who=gd.creature_name(member))
    return None
