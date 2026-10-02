"""Kurzak's, Legcrusher's and Pehtucl's things, of the companion's own."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game, npcitems, pickpocket, ring
from test_dicelog import CREATURES, DS, HDR, ITEM_TYPES, ITEMS, NAMES, far
from test_ring import THINGS, arena

KURZAK, LEGCRUSHER, PEHTUCL = 3, 4, 5
KEY = 0x40  # a name entry, made "Slavepen key"


def item_at(m, item):
    return bytes(m[ITEMS + item * game.ITEM_SIZE:ITEMS + (item + 1) * game.ITEM_SIZE])


class NpcItemTests(unittest.TestCase):
    def setUp(self):
        """In the pens: Kurzak (creature 3) with a key, Legcrusher (4) with a club, and a
        Templar (5) with the Bloodwrath, each one list (objects 401-403, items 80-82); items
        60-69 free; DSCLOG's types in."""
        self.log = log = arena()
        self.gd = log.game
        self.m = m = log.guest.mem
        struct.pack_into("<H", m, DS * 16 + ring.REGION, npcitems.REGION)
        for item in range(60, 70):
            struct.pack_into("<h", m, ITEMS + item * game.ITEM_SIZE + game.ITEM_NEXT, item + 1 if item < 69 else game.NO_ITEM)
        m[NAMES + 3 + KEY * 25:NAMES + 3 + KEY * 25 + 12] = b"Slavepen key"
        for creature, name, thing, item, item_name in ((KURZAK, b"Kurzak", 401, 80, KEY),
                                                        (LEGCRUSHER, b"Legcrusher", 402, 81, 0),
                                                        (PEHTUCL, b"Templar", 403, 82, npcitems.BLOODWRATH)):
            rec = CREATURES + creature * game.CREATURE_SIZE
            m[rec + game.CREATURE_NAME:rec + game.CREATURE_NAME + 16] = name.ljust(16, b"\0")
            struct.pack_into("<h", m, rec, 30)
            struct.pack_into("<hhh", m, rec + 8, game.NO_ITEM, game.NO_ITEM, thing)
            struct.pack_into("<Bh", m, THINGS + thing * 3, game.THING_ITEM, item)
            struct.pack_into("<Bh", m, THINGS + (0x30 + creature) * 3, 2, creature)  # a combatant
            irec = bytearray(game.ITEM_SIZE)
            struct.pack_into("<HhH", irec, game.ITEM_NEXT, game.NO_ITEM, 0, 0)
            struct.pack_into("<H", irec, game.ITEM_NAME, item_name)
            irec[game.ITEM_SLOT] = 0x0E
            m[ITEMS + item * game.ITEM_SIZE:ITEMS + (item + 1) * game.ITEM_SIZE] = irec
        for number, rec in enumerate(npcitems.TYPES, game.GAME_TYPES):
            m[ITEM_TYPES + number * game.ITEM_TYPE_SIZE:ITEM_TYPES + (number + 1) * game.ITEM_TYPE_SIZE] = rec
        struct.pack_into("<H", m, HDR + npcitems.TSR_TYPES_FIRST, game.GAME_TYPES)
        m[HDR + npcitems.TSR_TYPES_PTR:HDR + npcitems.TSR_TYPES_PTR + 4] = far(ITEM_TYPES)

    def carried(self, creature):
        it = ring.Items(self.gd)
        thing, = struct.unpack_from("<h", self.gd.creature(creature), 8 + 4)
        return [(data[game.ITEM_SLOT], struct.unpack_from("<H", data, game.ITEM_NAME)[0],
                 struct.unpack_from("<H", data, game.ITEM_TYPE)[0], data[game.ITEM_PLUS]) for _, data in it.chain(thing)]

    def test_ready(self):
        self.assertTrue(npcitems.types_ready(self.gd, HDR))
        struct.pack_into("<H", self.m, HDR + npcitems.TSR_TYPES_FIRST, 0)
        self.assertFalse(npcitems.types_ready(self.gd, HDR))
        self.assertFalse(npcitems.types_ready(self.gd, None))

    def test_who(self):
        it = ring.Items(self.gd)
        self.assertEqual([npcitems.who(self.gd, it, c) for c in (KURZAK, LEGCRUSHER, PEHTUCL, 0)],
                         ["Kurzak", "Legcrusher", "Pehtucl", None])
        self.m[ITEMS + 82 * game.ITEM_SIZE + game.ITEM_NAME] = 0  # a Templar without the Bloodwrath
        self.assertIsNone(npcitems.who(self.gd, it, PEHTUCL))

    def test_placed_once(self):
        given = set()
        self.assertEqual(npcitems.place(self.gd, given), [])  # (nothing for the log)
        head, chest, cloak = (game.EQUIP_SLOTS.index(s) for s in ("head", "chest", "cloak"))
        sword, helm = self.carried(KURZAK)[1], self.carried(KURZAK)[0]
        self.assertEqual(helm, (head, 6, 5, 0))
        self.assertEqual(sword[1:], (npcitems.SHORT_SWORD, game.SHORT_SWORD_TYPE, 0))
        self.assertGreaterEqual(sword[0], 0x0E)  # in a backpack cell
        self.assertEqual(self.carried(LEGCRUSHER)[0], (chest, 7, 6, 1))
        self.assertEqual(self.carried(PEHTUCL)[:2], [(game.FINGER, npcitems.RING, game.RING_TYPE, 1),
                                                     (cloak, npcitems.CLOAK, game.CLOAK_TYPE, 1)])
        self.assertEqual(len(given), 5)
        self.assertEqual(npcitems.place(self.gd, given), [])  # once a game
        self.assertEqual(len(self.carried(KURZAK)), 3)

    def test_worn_slot_taken(self):
        """A helm on Kurzak's head already: his goes in a backpack cell."""
        self.m[ITEMS + 80 * game.ITEM_SIZE + game.ITEM_SLOT] = game.EQUIP_SLOTS.index("head")
        npcitems.place(self.gd, set())
        self.assertGreaterEqual(self.carried(KURZAK)[0][0], 0x0E)

    def test_only_in_the_pens(self):
        struct.pack_into("<H", self.m, DS * 16 + ring.REGION, 0x2A)
        self.assertEqual(npcitems.place(self.gd, set()), [])

    def test_not_the_dead(self):
        struct.pack_into("<h", self.m, CREATURES + KURZAK * game.CREATURE_SIZE, 0)
        given = set()
        npcitems.place(self.gd, given)
        self.assertFalse(any("Kurzak" in key for key in given))

    def test_lifted(self):
        """A thief can lift Kurzak's short sword (whatever its weight) and Pehtucl's ring, not
        the key, helm, armour or worn cloak."""
        npcitems.place(self.gd, set())
        for number, weight in ((5, 15), (6, 750), (game.RING_TYPE, 1)):
            struct.pack_into("<H", self.m, ITEM_TYPES + number * game.ITEM_TYPE_SIZE + pickpocket.TYPE_WEIGHT, weight)
        self.m[ITEM_TYPES + 5 * game.ITEM_TYPE_SIZE + pickpocket.TYPE_WORN] = 6  # the head
        self.m[ITEM_TYPES + 6 * game.ITEM_TYPE_SIZE + pickpocket.TYPE_WORN] = 1  # the chest
        it = ring.Items(self.gd)
        names = lambda c: sorted(struct.unpack_from("<H", it.item(i), game.ITEM_NAME)[0]
                                 for _, i, _ in pickpocket._carried(self.gd, it, c))
        self.assertEqual(names(KURZAK), [npcitems.SHORT_SWORD])
        self.assertEqual(names(LEGCRUSHER), [0])  # (the fake's club, weight 0)
        self.assertIn(npcitems.RING, names(PEHTUCL))
        self.assertNotIn(npcitems.CLOAK, names(PEHTUCL))

    def test_cloak_on_saves(self):
        """Worn by Dag: +1 on saves, as a ring of protection."""
        struct.pack_into("<hhh", self.m, CREATURES + 8, game.NO_ITEM, game.NO_ITEM, 404)
        struct.pack_into("<Bh", self.m, THINGS + 404 * 3, game.THING_ITEM, 83)
        self.m[ITEMS + 83 * game.ITEM_SIZE:ITEMS + 84 * game.ITEM_SIZE] = bytes.fromhex("00000000ffff0000ffff") + bytes(11)
        self.m[ITEMS + 83 * game.ITEM_SIZE + game.ITEM_SLOT] = 0x0E
        self.assertEqual(self.gd.ring_plus(0), 0)
        self.assertTrue(npcitems.add_to(self.gd, 0, npcitems.CLOAK_ITEM, game.CLOAK_SLOT))
        self.assertEqual(self.gd.ring_plus(0), 1)


if __name__ == "__main__":
    unittest.main()
