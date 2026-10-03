import struct
import unittest

from dscompanion import game, rings, targeting

HDR, BASE = 0x9000, 0x8000
DS = 0x2000
FOES = {42: (600, 500), 44: (300, 500), 45: (900, 900)}
ME = (500, 500)


class Guest:
    def __init__(self):
        self.mem = bytearray(0x110000)

    def read(self, at, n):
        return bytes(self.mem[at:at + n])

    def write(self, at, data):
        self.mem[at:at + len(data)] = data


class Game:
    def __init__(self):
        self.guest, self.ds = Guest(), DS
        for thing, (x, y) in list(FOES.items()) + [(0, ME)]:
            self.guest.write(DS * 16 + targeting.MAP_THINGS + thing * 32 + targeting.MAP_FEET, struct.pack("<HH", x, y))
        self.guest.write(DS * 16 + targeting.CAMERA, struct.pack("<HH", 400, 400))
        self.turn = 0

    def in_combat(self):
        return True

    def whose_turn(self):
        return self.turn

    def combatant_creature(self, c):
        return None

    def press(self, tabs=0, backs=0):
        t, b = struct.unpack("<HH", self.guest.read(HDR + targeting.TSR_TAB, 4))
        self.guest.write(HDR + targeting.TSR_TAB, struct.pack("<HH", t + tabs, b + backs))

    def target(self):
        return struct.unpack("<H", self.guest.read(HDR + targeting.TSR_TARGET, 2))[0]


class TargetingTests(unittest.TestCase):
    def test_tab_steps_nearest_first(self):
        """Tab: the nearest enemy, then the next nearest...; Shift+Tab back; a new turn forgets."""
        gd, t = Game(), targeting.Targeting()
        foes = list(FOES)
        t.update(gd, HDR, True, foes)
        self.assertEqual(gd.target(), targeting.NONE)
        self.assertEqual(struct.unpack("<H", gd.guest.read(HDR + targeting.TSR_TARGET_ON, 2))[0], 1)
        gd.press(tabs=1)
        t.update(gd, HDR, True, foes)
        self.assertEqual(gd.target(), 42)  # (100 away)
        gd.press(tabs=1)
        t.update(gd, HDR, True, foes)
        self.assertEqual(gd.target(), 44)  # (200 away)
        gd.press(backs=1)
        t.update(gd, HDR, True, foes)
        self.assertEqual(gd.target(), 42)
        gd.turn = 1
        t.update(gd, HDR, True, foes)
        self.assertEqual(gd.target(), targeting.NONE)

    def test_far_one_scrolled_to(self):
        """Choosing one out of view has the view scrolled to it."""
        gd, t = Game(), targeting.Targeting()
        foes = [45]
        t.update(gd, HDR, True, foes)
        gd.press(tabs=1)
        t.update(gd, HDR, True, foes)
        self.assertEqual(struct.unpack("<hh", gd.guest.read(HDR + targeting.TSR_PAN, 4)), (500 - 160, 500 - 100))

    def test_ring_table(self):
        table = rings.ring_table([42, 44], 44)
        self.assertEqual((table[42], table[44], table[45]), (rings.RING, rings.CHOSEN, 0))

    def test_red_table(self):
        """A sand colour reddens to the palette's red one; a red one has none redder."""
        dac = bytearray(768)
        dac[20 * 3:20 * 3 + 3] = bytes((52, 40, 32))
        dac[21 * 3:21 * 3 + 3] = bytes((55, 20, 15))
        table = rings.red_table(bytes(dac))
        self.assertEqual(table[20], 21)
        self.assertEqual(table[21], 0)


if __name__ == "__main__":
    unittest.main()
