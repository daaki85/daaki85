"""Picking pockets: P in a conversation, the leader a thief (pickpocket.py)."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game, pickpocket, ring
from test_dicelog import CREATURES, DS, ITEM_TYPES, ITEMS, LOAD_SEG, NAMES
from test_now import ThiefTests

THINGS = (LOAD_SEG + game.COMBATANTS_SEG) * 16 + game.COMBATANTS_OFF
GUARD, GUARD_COMBATANT = 5, 43
CLUB, SWORD, KEY = 80, 81, 82


class PickTests(unittest.TestCase):
    def setUp(self):
        """Dag, a 4th level thief (pick pockets 11, move silently 16 with his sword in hand),
        leads, talking to a Guard (creature 5) who has a bag (item 80, type 66: worn nowhere),
        a long sword (81, type 45: in a hand) and a key (82)."""
        thief = ThiefTests()
        thief.setUp()
        self.log, m = thief.log, thief.log.guest.mem
        self.m = m
        guard = CREATURES + GUARD * game.CREATURE_SIZE
        m[guard + game.CREATURE_NAME:guard + game.CREATURE_NAME + 6] = b"Guard\0"
        struct.pack_into("<h", m, guard, 30)
        struct.pack_into("<hhh", m, guard + 8, 450, game.NO_ITEM, game.NO_ITEM)
        struct.pack_into("<Bh", m, THINGS + GUARD_COMBATANT * 3, 2, GUARD)
        struct.pack_into("<Bh", m, THINGS + 450 * 3, game.THING_ITEM, CLUB)
        for item, nxt, slot, name, typ in ((CLUB, SWORD, 14, 20, 66), (SWORD, KEY, 15, 21, 45),
                                           (KEY, game.NO_ITEM, 16, 22, 66)):
            rec = ITEMS + item * game.ITEM_SIZE
            struct.pack_into("<h", m, rec + game.ITEM_NEXT, nxt)
            m[rec + game.ITEM_SLOT] = slot
            struct.pack_into("<H", m, rec + game.ITEM_NAME, name)
            struct.pack_into("<H", m, rec + game.ITEM_TYPE, typ)
        m[ITEM_TYPES + 45 * game.ITEM_TYPE_SIZE + pickpocket.TYPE_WORN] = 5
        m[ITEM_TYPES + 66 * game.ITEM_TYPE_SIZE + 0x08] = game.NO_MATERIAL
        for entry, text in ((20, b"Bag"), (21, b"Long Sword"), (22, b"Cell Key")):
            at = NAMES + 3 + entry * game.ITEM_NAME_SIZE
            m[at:at + len(text)] = text
        struct.pack_into("<h", m, (LOAD_SEG + game.TALK_SEG) * 16 + game.TALK_TARGET, GUARD_COMBATANT)
        struct.pack_into("<H", m, DS * 16 + game.WHOSE_TURN, 0)
        struct.pack_into("<H", m, DS * 16 + ring.FREE_THINGS, 505)
        self.tried = set()

    def attempt(self, *rolls):
        rolls = list(rolls)
        return pickpocket.attempt(self.log.game, self.tried, lambda: rolls.pop(0))

    def guard_items(self):
        return [i for i, _ in ring.Items(self.log.game).chain(450, inside=False)]

    def dag_items(self):
        thing, = struct.unpack_from("<h", self.m, CREATURES + 8)
        return [(i, rec[game.ITEM_SLOT]) for i, rec in ring.Items(self.log.game).chain(thing, inside=False)]

    def test_lifts_what_is_carried(self):
        """Not the sword, nor the key: the bag, into Dag's backpack's first cell."""
        result = self.attempt(11)
        self.assertEqual(result.text, "Dag lifts Bag from Guard unnoticed.")
        self.assertEqual(self.guard_items(), [SWORD, KEY])
        self.assertEqual(self.dag_items()[0], (CLUB, 13))
        self.assertIn("d100 = 11, needs 11 or less -> success", result.log[0])
        self.tried.add(result.key)  # (as the dice log does)
        self.assertEqual(self.attempt(1).text, "Dag has had a try at Guard's pockets already.")

    def test_caught(self):
        result = self.attempt(12, 17)  # pick pockets 11, move silently 16
        self.assertEqual(result.text, "Guard catches Dag's hand! Guard won't let Dag near again.")
        self.assertEqual(self.guard_items(), [CLUB, SWORD, KEY])
        self.assertIn("moves silently to get away: d100 = 17, needs 16 or less -> failed", result.log[1])
        self.assertIsNotNone(result.key)

    def test_slips_away(self):
        self.assertEqual(self.attempt(50, 16).text, "Dag fumbles Guard's pockets, but slips away unnoticed.")

    def test_not_a_thief(self):
        from test_dicelog import SHEETS
        self.m[SHEETS + game.SHEET_CLASSES + 1] = 0
        self.assertEqual(self.attempt().text, "Dag is no thief.")

    def test_no_one_to_rob(self):
        struct.pack_into("<h", self.m, (LOAD_SEG + game.TALK_SEG) * 16 + game.TALK_TARGET, 2)  # a party member
        self.assertIsNone(self.attempt())


if __name__ == "__main__":
    unittest.main()
