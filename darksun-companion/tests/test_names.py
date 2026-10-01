"""The companion's items' names, past the game's own 322 in its name table."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game, names, ring, tools
from dscompanion.dicelog import HDR_SIG
from test_dicelog import HDR, NAMES, far
from test_dsclog import load_image
from test_ring import ITEMS, THINGS, arena


def entry(m, number, text=None):
    at = NAMES + 3 + number * game.ITEM_NAME_SIZE
    if text is not None:
        m[at:at + game.ITEM_NAME_SIZE] = text.ljust(game.ITEM_NAME_SIZE, b"\0")
    return bytes(m[at:at + game.ITEM_NAME_SIZE]).split(b"\0", 1)[0]


class NamesTests(unittest.TestCase):
    def setUp(self):
        self.log = arena()
        self.m = self.log.guest.mem
        self.gd = self.log.game

    def test_named(self):
        self.assertEqual((self.gd.item_name(names.RING), self.gd.item_name(names.TOOLS)),
                         ("Ring/Protection", "Thieves' Tools"))
        self.assertGreaterEqual(min(names.NAMES), names.OWN)

    def test_ready(self):
        self.assertTrue(names.ready(self.gd, HDR))
        self.assertFalse(names.ready(self.gd, None))
        self.m[HDR + names.TSR_NAMES_PTR:HDR + names.TSR_NAMES_PTR + 4] = far(NAMES + 0x1003)  # another table
        self.assertFalse(names.ready(self.gd, HDR))
        self.m[HDR + names.TSR_NAMES_PTR:HDR + names.TSR_NAMES_PTR + 4] = bytes(4)  # none yet
        self.assertFalse(names.ready(self.gd, HDR))

    def test_not_ready_nothing_given(self):
        """Without DSCLOG's names (an older DSCLOG, or the game reading its table in), no ring
        and no tools: they'd have no name."""
        self.m[HDR + names.TSR_NAMES_PTR:HDR + names.TSR_NAMES_PTR + 4] = bytes(4)
        self.assertFalse(names.update(self.gd, HDR))
        self.assertEqual(self.log.give_tools_now()[0][:23], "The game's name table h")

    def test_borrowed_entries_back(self):
        entry(self.m, 0x95, b"Ring/Protection")
        entry(self.m, 0x60, b"Thieves' Tools")
        self.assertTrue(names.update(self.gd, HDR))
        self.assertEqual((entry(self.m, 0x95), entry(self.m, 0x60)), (b"", b"Rest icon"))

    def test_others_left_be(self):
        entry(self.m, 0x95, b"Other")
        entry(self.m, 0x60, b"Rest icon")
        names.update(self.gd, HDR)
        self.assertEqual((entry(self.m, 0x95), entry(self.m, 0x60)), (b"Other", b"Rest icon"))

    def test_items_moved(self):
        """A ring on the ground (object 300) named in the old entry, and tools from each earlier
        version in a pile (object 301); a plain item with one of those entries stays."""
        for thing, item in ((300, 70), (301, 71)):
            struct.pack_into("<Bh", self.m, THINGS + thing * 3, game.THING_ITEM, item)
        old_ring = bytearray(ring.RING)
        struct.pack_into("<H", old_ring, game.ITEM_NAME, 0x95)
        recs = {70: old_ring, 71: tools.ITEM, 72: tools.ITEM, 73: bytes(game.ITEM_SIZE)}
        olds = {71: 0x60, 72: 0xAD, 73: 0x60}
        for item, rec in recs.items():
            rec = bytearray(rec)
            struct.pack_into("<h", rec, game.ITEM_NEXT, item + 1 if item in (71, 72) else game.NO_ITEM)
            if item in olds:
                struct.pack_into("<H", rec, game.ITEM_NAME, olds[item])
            self.m[ITEMS + item * game.ITEM_SIZE:ITEMS + (item + 1) * game.ITEM_SIZE] = rec
        self.assertEqual(names.migrate(self.gd), 3)
        got = [struct.unpack_from("<H", self.m, ITEMS + item * game.ITEM_SIZE + game.ITEM_NAME)[0]
               for item in (70, 71, 72, 73)]
        self.assertEqual(got, [names.RING, names.TOOLS, names.TOOLS, 0x60])
        self.assertEqual(names.migrate(self.gd), 0)


class HelperTests(unittest.TestCase):
    def test_dsclog_has_the_same_names(self):
        """DSCLOG copies its own list of the names into the game's table: the same as NAMES."""
        image = load_image()
        hdr = image.find(HDR_SIG)
        off, count = struct.unpack_from("<HH", image, hdr + names.TSR_NAMES_OFF)
        self.assertEqual(count, names.EXTRA)
        size = game.ITEM_NAME_SIZE
        listed = [image[off + i * size:off + (i + 1) * size] for i in range(count)]
        want = [names.NAMES.get(names.OWN + i, b"").ljust(size, b"\0") for i in range(count)]
        self.assertEqual(listed, want)


if __name__ == "__main__":
    unittest.main()
