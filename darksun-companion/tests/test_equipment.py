"""A creature's items: the lists that start in its record, and each item's slot, material and plus."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game
from test_dicelog import CREATURES, DS, ITEMS, LOAD_SEG, make_game


class EquipmentTests(unittest.TestCase):
    def test_lists(self):
        """Dag holds item 5 (metal long sword +1) in his right hand and carries item 6 (a plain
        wooden long sword), chained from item 5; the list starts at object 40."""
        log = make_game()
        m = log.guest.mem
        things = (LOAD_SEG + game.COMBATANTS_SEG) * 16 + game.COMBATANTS_OFF
        struct.pack_into("<Bh", m, things + 40 * 3, game.THING_ITEM, 5)
        struct.pack_into("<h", m, CREATURES + game.CREATURE_ITEM_LISTS[1], 40)
        struct.pack_into("<h", m, CREATURES + game.CREATURE_ITEM_LISTS[0], 9999)
        sword, spare = ITEMS + 5 * game.ITEM_SIZE, ITEMS + 6 * game.ITEM_SIZE
        struct.pack_into("<h", m, sword + game.ITEM_NEXT, 6)
        struct.pack_into("<h", m, spare + game.ITEM_NEXT, game.NO_ITEM)
        m[sword + game.ITEM_SLOT], m[spare + game.ITEM_SLOT] = 3, 255
        g = game.GameData(log.guest, DS)
        self.assertEqual(g.equipment(0), [("right hand", "Metal Long Sword +1"), (None, "Wooden Long Sword")])

    def test_nothing(self):
        log = make_game()
        struct.pack_into("<hh", log.guest.mem, CREATURES + 8, 9999, 9999)
        self.assertEqual(game.GameData(log.guest, DS).equipment(0), [])


if __name__ == "__main__":
    unittest.main()
