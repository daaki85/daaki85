import struct
import unittest

from dscompanion import game, shadows

HDR, BASE, TABLE_OFF = 0x9000, 0x8000, 0x200
DS, LOAD = 0x2000, 0x100


class Guest:
    def __init__(self):
        self.mem = bytearray(0x110000)

    def read(self, at, n):
        return bytes(self.mem[at:at + n])

    def write(self, at, data):
        self.mem[at:at + len(data)] = data


class Game:
    """Things 0 (a living creature), 1 (a dead one), 2 (an item), 300 (a living creature)."""

    def __init__(self):
        self.guest, self.ds, self.load_seg, self.area = Guest(), DS, LOAD, 0x29
        things = (LOAD + game.COMBATANTS_SEG) * 16 + game.COMBATANTS_OFF
        for thing, kind, index in ((0, 2, 0), (1, 2, 1), (2, 1, 5), (300, 2, 2)):
            self.guest.write(things + thing * 3, struct.pack("<Bh", kind, index))
        self.records = {i: bytearray(game.CREATURE_SIZE) for i in range(3)}
        for i, rec in self.records.items():
            rec[game.CREATURE_NAME] = ord("A")
        self.records[1][game.CREATURE_STATUS] = shadows.STATUS_DEAD
        self.guest.write(HDR + shadows.TSR_HDR_OFF, struct.pack("<H", HDR - BASE))
        self.guest.write(HDR + shadows.TSR_TABLE, struct.pack("<H", TABLE_OFF))

    def creature(self, i):
        return bytes(self.records.get(i, b""))

    def region(self):
        return self.area

    def word(self, at):
        return struct.unpack("<H", self.guest.read(at, 2))[0]

    def redrawn(self):
        """The view asked to be drawn again (and the request taken, as DSCLOG does)."""
        asked = self.word(HDR + shadows.TSR_VIEW_REDRAW)
        self.guest.write(HDR + shadows.TSR_VIEW_REDRAW, b"\0\0")
        return bool(asked)


class ShadowsTests(unittest.TestCase):
    def test_casting(self):
        """The living creatures among all 520 things: not the dead, not items."""
        table = shadows.casting(Game())
        self.assertEqual(len(table), shadows.THINGS)
        self.assertEqual([t for t in range(shadows.THINGS) if table[t]], [0, 300])

    def test_update(self):
        """On: DSCLOG's switch, its table, the darker colours asked for (and again after an area
        change), the view drawn again (DSCLOG asked: no figure marked changed); off: drawn again
        without."""
        gd, s = Game(), shadows.Shadows()
        s.update(gd, HDR, True, 100.0)
        self.assertEqual(gd.word(HDR + shadows.TSR_ON), 1)
        self.assertEqual(gd.word(HDR + shadows.TSR_BUILD), 1)
        self.assertEqual(gd.guest.read(BASE + TABLE_OFF, 3), b"\x01\x00\x00")
        self.assertEqual(gd.guest.read(BASE + TABLE_OFF + 300, 1), b"\x01")
        gd.guest.write(HDR + shadows.TSR_BUILD, struct.pack("<H", 0))  # (DSCLOG made them)
        s.update(gd, HDR, True, 100.3)
        self.assertFalse(gd.redrawn())
        s.update(gd, HDR, True, 101.0)
        self.assertTrue(gd.redrawn())
        self.assertEqual(s.palettes, 1)
        self.assertEqual(gd.word(HDR + shadows.TSR_BUILD), 0)
        gd.area = 0x2A  # (another area: its palette)
        s.update(gd, HDR, True, 102.0)
        self.assertEqual(gd.word(HDR + shadows.TSR_BUILD), 0)
        s.update(gd, HDR, True, 102.0 + shadows.BUILD_AFTER[0])
        self.assertEqual(gd.word(HDR + shadows.TSR_BUILD), 1)
        s.update(gd, HDR, False, 110.0)
        self.assertEqual(gd.word(HDR + shadows.TSR_ON), 0)
        self.assertTrue(gd.redrawn())  # (drawn again: the shadows gone)


if __name__ == "__main__":
    unittest.main()
