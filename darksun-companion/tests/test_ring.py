"""The Ring +1: found on the Tied-up Prisoner's body in the arena, named, and counted on saving throws."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game, ring
from test_dicelog import CREATURES, DS, ITEM_TYPES, ITEMS, LOAD_SEG, NAMES, make_game

THINGS = (LOAD_SEG + game.COMBATANTS_SEG) * 16 + game.COMBATANTS_OFF
def arena():
    """The arena, the ring still to be found; item 60 first on the free item list, object 505
    first on the free object list; Dag (creature 0) leads."""
    log = make_game()
    m = log.guest.mem
    struct.pack_into("<H", m, DS * 16 + ring.REGION, ring.ARENA)
    struct.pack_into("<HH", m, DS * 16 + ring.FREE_ITEMS, 60, 0)
    struct.pack_into("<h", m, ITEMS + 60 * game.ITEM_SIZE + game.ITEM_NEXT, 61)
    struct.pack_into("<H", m, DS * 16 + ring.FREE_THINGS, 505)
    struct.pack_into("<Bh", m, THINGS + 505 * 3, 0, 504)
    struct.pack_into("<H", m, DS * 16 + ring.THINGS_USED, 15)
    struct.pack_into("<H", m, DS * 16 + game.WHOSE_TURN, 0)
    # (the fake's creatures' lists: none)
    for index in range(8):
        struct.pack_into("<hhh", m, CREATURES + index * game.CREATURE_SIZE + 8, *(game.NO_ITEM,) * 3)
    return log


def word(m, addr):
    return struct.unpack_from("<H", m, addr)[0]


class SearchTests(unittest.TestCase):
    def test_found_on_the_body(self):
        """Looked for on the body: into the leader's backpack (its first cell), and then no
        more is needed."""
        log = arena()
        m = log.guest.mem
        self.assertTrue(ring.ring_needed(log.game))
        self.assertEqual(ring.give_ring(log.game), ring.MESSAGE.format(who=log.game.creature_name(0)))
        thing, = struct.unpack_from("<h", m, CREATURES + 8)
        self.assertEqual(struct.unpack_from("<Bh", m, THINGS + thing * 3), (game.THING_ITEM, 60))
        rec = bytearray(ring.RING)
        rec[game.ITEM_SLOT] = 14
        struct.pack_into("<H", rec, game.ITEM_NEXT, game.NO_ITEM)
        self.assertEqual(bytes(m[ITEMS + 60 * game.ITEM_SIZE:ITEMS + 61 * game.ITEM_SIZE]), bytes(rec))
        self.assertFalse(ring.ring_needed(log.game))

    def test_party_has_it(self):
        """Dag carries a Ring +1 already (his list starting at object 401)."""
        log = arena()
        m = log.guest.mem
        struct.pack_into("<Bh", m, THINGS + 401 * 3, game.THING_ITEM, 70)
        struct.pack_into("<h", m, CREATURES + 8, 401)
        m[ITEMS + 70 * game.ITEM_SIZE:ITEMS + 71 * game.ITEM_SIZE] = ring.RING
        self.assertFalse(ring.ring_needed(log.game))

    def test_elsewhere(self):
        log = arena()
        struct.pack_into("<H", log.guest.mem, DS * 16 + ring.REGION, 0x2B)
        self.assertFalse(ring.ring_needed(log.game))


class NameTests(unittest.TestCase):
    def test_free_entry(self):
        log = arena()
        self.assertTrue(ring.name_ring(log.game))
        self.assertEqual(log.game.item_name(ring.NAME_ENTRY), "Ring/Protection")

    def test_old_name(self):
        """Saved with an earlier version: its "Ring +1" or "Ring of Protection" (too long for
        the Look box) becomes the new name."""
        log = arena()
        at = NAMES + 3 + ring.NAME_ENTRY * game.ITEM_NAME_SIZE
        for old in (b"Ring +1", b"Ring of Protection"):
            log.guest.mem[at:at + game.ITEM_NAME_SIZE] = old.ljust(game.ITEM_NAME_SIZE, b"\0")
            self.assertTrue(ring.name_ring(log.game))
            self.assertEqual(log.game.item_name(ring.NAME_ENTRY), "Ring/Protection")
        self.assertEqual(log.game.item_name(ring.NAME_ENTRY), "Ring/Protection")

    def test_rule_names(self):
        """Helms and boots named for the rules while they're on, and back without them."""
        log = arena()
        m = log.guest.mem
        for entry, text in ((6, b"Helm"), (43, b"Boots")):
            m[NAMES + 3 + entry * game.ITEM_NAME_SIZE:NAMES + 3 + entry * game.ITEM_NAME_SIZE + len(text)] = text
        ring.name_items(log.game, game.RULE_HELMS | game.RULE_BOOTS)
        self.assertEqual((log.game.item_name(6), log.game.item_name(43)), ("Helm (AC 1)", "Boots (+1 Move)"))
        ring.name_items(log.game, game.RULE_BOOTS)
        self.assertEqual((log.game.item_name(6), log.game.item_name(43)), ("Helm", "Boots (+1 Move)"))

    def test_rule_names_fit_the_look_box(self):
        """Names the rule would make longer than 15 letters stay the game's own (and one an
        earlier version made that long goes back)."""
        log = arena()
        m = log.guest.mem
        for entry, text in ((236, b"Helm of Might (AC 1)"), (286, b"Serpent Boots")):
            at = NAMES + 3 + entry * game.ITEM_NAME_SIZE
            m[at:at + game.ITEM_NAME_SIZE] = text.ljust(game.ITEM_NAME_SIZE, b"\0")
        ring.name_items(log.game, game.RULE_HELMS | game.RULE_BOOTS)
        self.assertEqual((log.game.item_name(236), log.game.item_name(286)), ("Helm of Might", "Serpent Boots"))

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
        self.assertEqual(self.log.game.equipment(0), [("finger", "Ring/Protection +1")])

    def test_saves(self):
        self.assertEqual(self.log.game.ring_plus(0), 1)
        self.assertIn((1, "Ring of Protection"), self.log.game.save_modifiers(0, 0x29, 27, 3))

    def test_carried_only(self):
        self.log.guest.mem[ITEMS + 70 * game.ITEM_SIZE + game.ITEM_SLOT] = 0xFF
        self.assertEqual(self.log.game.ring_plus(0), 0)


if __name__ == "__main__":
    unittest.main()
