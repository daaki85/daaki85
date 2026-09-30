"""The Ring +1: put on the dead prisoner in the arena, named, and counted on saving throws."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game, ring
from test_dicelog import CREATURES, DS, ITEM_TYPES, ITEMS, LOAD_SEG, NAMES, make_game

THINGS = (LOAD_SEG + game.COMBATANTS_SEG) * 16 + game.COMBATANTS_OFF
BODY, BODY_THING = 22, 297


def arena():
    """The arena with the dead prisoner (item 22, object 297) where the game has it, empty;
    item 60 first on the free item list, object 505 first on the free object list."""
    log = make_game()
    m = log.guest.mem
    struct.pack_into("<H", m, DS * 16 + ring.REGION, ring.ARENA)
    struct.pack_into("<Bh", m, THINGS + BODY_THING * 3, game.THING_ITEM, BODY)
    struct.pack_into("<HH", m, DS * 16 + ring.POSITIONS + BODY_THING * ring.POSITION_SIZE, *ring.BODY_AT)
    body = ITEMS + BODY * game.ITEM_SIZE
    struct.pack_into("<HHH", m, body + game.ITEM_NEXT, game.NO_ITEM, 1, game.NO_ITEM)
    struct.pack_into("<H", m, body + game.ITEM_TYPE, ring.BODY_TYPE)
    struct.pack_into("<HH", m, DS * 16 + ring.FREE_ITEMS, 60, 0)
    struct.pack_into("<h", m, ITEMS + 60 * game.ITEM_SIZE + game.ITEM_NEXT, 61)
    struct.pack_into("<H", m, DS * 16 + ring.FREE_THINGS, 505)
    struct.pack_into("<Bh", m, THINGS + 505 * 3, 0, 504)
    struct.pack_into("<H", m, DS * 16 + ring.THINGS_USED, 15)
    # (the fake's other creatures' lists: none)
    for index in range(8):
        struct.pack_into("<hhh", m, CREATURES + index * game.CREATURE_SIZE + 8, *(game.NO_ITEM,) * 3)
    return log


def word(m, addr):
    return struct.unpack_from("<H", m, addr)[0]


class PlaceTests(unittest.TestCase):
    def test_empty_body(self):
        log = arena()
        m = log.guest.mem
        self.assertEqual(ring.place_ring(log.game), ring.MESSAGE)
        self.assertEqual(word(m, ITEMS + BODY * game.ITEM_SIZE + ring.ITEM_CONTENTS), 505)
        self.assertEqual(struct.unpack_from("<Bh", m, THINGS + 505 * 3), (game.THING_ITEM, 60))
        self.assertEqual(bytes(m[ITEMS + 60 * game.ITEM_SIZE:ITEMS + 61 * game.ITEM_SIZE]), ring.RING)
        self.assertEqual((word(m, DS * 16 + ring.FREE_ITEMS), word(m, DS * 16 + ring.FREE_THINGS),
                          word(m, DS * 16 + ring.THINGS_USED)), (61, 504, 16))
        self.assertIsNone(ring.place_ring(log.game))  # once only: it's there now

    def test_after_what_the_body_holds(self):
        """A body holding items 30 and 31 (from object 400): the ring goes after 31."""
        log = arena()
        m = log.guest.mem
        struct.pack_into("<H", m, ITEMS + BODY * game.ITEM_SIZE + ring.ITEM_CONTENTS, 400)
        struct.pack_into("<Bh", m, THINGS + 400 * 3, game.THING_ITEM, 30)
        struct.pack_into("<h", m, ITEMS + 30 * game.ITEM_SIZE + game.ITEM_NEXT, 31)
        struct.pack_into("<h", m, ITEMS + 31 * game.ITEM_SIZE + game.ITEM_NEXT, game.NO_ITEM)
        self.assertEqual(ring.place_ring(log.game), ring.MESSAGE)
        self.assertEqual(word(m, ITEMS + 31 * game.ITEM_SIZE + game.ITEM_NEXT), 60)
        self.assertEqual(word(m, DS * 16 + ring.FREE_THINGS), 505)  # no new object

    def test_party_has_it(self):
        """Dag carries a Ring +1 already (his list starting at object 401)."""
        log = arena()
        m = log.guest.mem
        struct.pack_into("<Bh", m, THINGS + 401 * 3, game.THING_ITEM, 70)
        struct.pack_into("<h", m, CREATURES + 8, 401)
        m[ITEMS + 70 * game.ITEM_SIZE:ITEMS + 71 * game.ITEM_SIZE] = ring.RING
        self.assertIsNone(ring.place_ring(log.game))

    def test_elsewhere(self):
        log = arena()
        struct.pack_into("<H", log.guest.mem, DS * 16 + ring.REGION, 0x2B)
        self.assertIsNone(ring.place_ring(log.game))


class NameTests(unittest.TestCase):
    def test_free_entry(self):
        log = arena()
        self.assertTrue(ring.name_ring(log.game))
        self.assertEqual(log.game.item_name(ring.NAME_ENTRY), "Ring +1")

    def test_entry_in_use(self):
        log = arena()
        at = NAMES + 3 + ring.NAME_ENTRY * game.ITEM_NAME_SIZE
        log.guest.mem[at:at + 5] = b"Other"
        self.assertFalse(ring.name_ring(log.game))
        self.assertEqual(log.game.item_name(ring.NAME_ENTRY), "Other")


class WornTests(unittest.TestCase):
    def setUp(self):
        """Dag wears the Ring +1 (item 70, from object 401)."""
        self.log = arena()
        m = self.log.guest.mem
        ring.name_ring(self.log.game)
        struct.pack_into("<Bh", m, THINGS + 401 * 3, game.THING_ITEM, 70)
        struct.pack_into("<h", m, CREATURES + 0x0C, 401)
        m[ITEMS + 70 * game.ITEM_SIZE:ITEMS + 71 * game.ITEM_SIZE] = ring.RING
        m[ITEMS + 70 * game.ITEM_SIZE + game.ITEM_SLOT] = game.FINGER
        m[ITEM_TYPES + game.RING_TYPE * game.ITEM_TYPE_SIZE + 0x08] = game.NO_MATERIAL

    def test_named(self):
        self.assertEqual(self.log.game.equipment(0), [("finger", "Ring +1")])

    def test_saves(self):
        self.assertEqual(self.log.game.ring_plus(0), 1)
        self.assertIn((1, "Ring +1"), self.log.game.save_modifiers(0, 0x29, 27, 3))

    def test_carried_only(self):
        self.log.guest.mem[ITEMS + 70 * game.ITEM_SIZE + game.ITEM_SLOT] = 0xFF
        self.assertEqual(self.log.game.ring_plus(0), 0)


if __name__ == "__main__":
    unittest.main()
