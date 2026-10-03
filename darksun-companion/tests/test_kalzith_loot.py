"""What Kalzith leaves when killed: one of his scrolls, a Cloak and a Quarterstaff (kalzith.loot)."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game, kalzith, ring
from test_dicelog import CREATURES, DS, ITEMS, LOAD_SEG
from test_now import ThiefTests

THINGS = (LOAD_SEG + game.COMBATANTS_SEG) * 16 + game.COMBATANTS_OFF
PILE, BAG = 450, 451


class LootTests(unittest.TestCase):
    def setUp(self):
        """His pile (object 450): three of his scrolls (items 80-82: Magic Missile, Blur, Lightning
        Bolt); the party's leader holds a fourth (83, Color Spray, bought); free item records 90-92."""
        thief = ThiefTests()
        thief.setUp()
        self.gd, m = thief.log.game, thief.log.guest.mem
        self.m = m
        self.flags = {kalzith.DIED}
        self.gd.flag = lambda n: n in self.flags
        self.gd.set_flag = lambda n, on=True: self.flags.add(n)
        struct.pack_into("<Bh", m, THINGS + PILE * 3, game.THING_ITEM, 80)
        struct.pack_into("<Bh", m, THINGS + BAG * 3, game.THING_ITEM, 83)
        struct.pack_into("<hhh", m, CREATURES + 8, BAG, game.NO_ITEM, game.NO_ITEM)
        for item, k, nxt in ((80, 0, 81), (81, 2, 82), (82, 4, game.NO_ITEM), (83, 1, game.NO_ITEM)):
            rec = kalzith.scroll(kalzith.SCROLLS[k][0], kalzith.SCROLLS[k][2], k)
            m[ITEMS + item * game.ITEM_SIZE:ITEMS + (item + 1) * game.ITEM_SIZE] = rec
            struct.pack_into("<h", m, ITEMS + item * game.ITEM_SIZE + game.ITEM_NEXT, nxt)
        for item, nxt in ((90, 91), (91, 92), (92, game.NO_ITEM)):
            struct.pack_into("<h", m, ITEMS + item * game.ITEM_SIZE + game.ITEM_NEXT, nxt)
        struct.pack_into("<H", m, DS * 16 + ring.FREE_ITEMS, 90)

    def objects(self, thing):
        return [-struct.unpack_from("<h", rec, 0)[0] for _, rec in ring.Items(self.gd).chain(thing)]

    def test_loot(self):
        """One scroll kept (here Blur), the other two taken back to the free list, the Cloak and
        Quarterstaff after it; the party's own scroll untouched; once only."""
        left = kalzith.loot(self.gd, choose=lambda items: 81)
        self.assertEqual(left, ["Scroll of Blur", "Quarterstaff", "Cloak"])
        self.assertEqual(self.objects(PILE), [1003, 1053, 1019])
        self.assertEqual(self.objects(BAG), [1002])
        free = struct.unpack_from("<H", self.m, DS * 16 + ring.FREE_ITEMS)[0]
        self.assertEqual(free, 90)  # (80 and 82 given back, then taken again for the two)
        self.assertIn(kalzith.LOOTED, self.flags)
        self.assertEqual(kalzith.loot(self.gd), [])

    def test_kept_first(self):
        """The kept scroll first in the pile: the others after it go."""
        kalzith.loot(self.gd, choose=lambda items: 80)
        self.assertEqual(self.objects(PILE), [1001, 1053, 1019])

    def test_alive(self):
        self.flags.discard(kalzith.DIED)
        self.assertEqual(kalzith.loot(self.gd), [])
        self.assertEqual(self.objects(PILE), [1001, 1003, 1005])

    def test_nothing_left(self):
        """All bought: nothing of his anywhere but with the party; nothing left, nothing added."""
        struct.pack_into("<Bh", self.m, THINGS + PILE * 3, 0, game.NO_ITEM)
        self.assertEqual(kalzith.loot(self.gd), [])
        self.assertIn(kalzith.LOOTED, self.flags)


if __name__ == "__main__":
    unittest.main()
