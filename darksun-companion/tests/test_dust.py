import struct
import unittest

from dscompanion import dust

HDR, BASE, LIGHT, DAC = 0x9000, 0x8000, 0x300, 0x400
SAND, SAND_LIGHT, GREY, BLUE = 20, 21, 30, 40


def palette() -> bytes:
    """Colours 0-63 as the VGA has them: a sand, a lighter sand, a grey, a blue; the rest black."""
    dac = bytearray(768)
    for i, rgb in ((SAND, (52, 40, 32)), (SAND_LIGHT, (60, 52, 44)), (GREY, (40, 40, 40)), (BLUE, (10, 20, 50))):
        dac[i * 3:i * 3 + 3] = bytes(rgb)
    return bytes(dac)


class Guest:
    def __init__(self):
        self.mem = bytearray(0x10000)

    def read(self, at, n):
        return bytes(self.mem[at:at + n])

    def write(self, at, data):
        self.mem[at:at + len(data)] = data


class Game:
    def __init__(self):
        self.guest = Guest()
        self.guest.write(HDR + dust.TSR_HDR_OFF, struct.pack("<H", HDR - BASE))
        self.guest.write(HDR + dust.TSR_LIGHT, struct.pack("<HH", LIGHT, DAC))
        self.guest.write(BASE + DAC, palette())


class DustTests(unittest.TestCase):
    def test_light_table(self):
        """Sand is lightened to the palette's lighter sand; grey, blue and black take no dust."""
        table = dust.light_table(palette())
        self.assertEqual(table[SAND], SAND_LIGHT)
        self.assertEqual([table[c] for c in (GREY, BLUE, 0, SAND_LIGHT)], [0, 0, 0, 0])

    def test_update(self):
        """LIGHT written, and dust switched on, once DSCLOG has read the palette (and again for
        each new one); switched off when asked."""
        gd, d = Game(), dust.Dust()
        d.update(gd, HDR, True, 0)
        self.assertEqual(gd.guest.read(HDR + dust.TSR_DUST_ON, 2), b"\0\0")
        d.update(gd, HDR, True, 1)
        self.assertEqual(gd.guest.read(HDR + dust.TSR_DUST_ON, 2), b"\1\0")
        self.assertEqual(gd.guest.read(BASE + LIGHT + SAND, 1), bytes([SAND_LIGHT]))
        d.update(gd, HDR, False, 1)
        self.assertEqual(gd.guest.read(HDR + dust.TSR_DUST_ON, 2), b"\0\0")


if __name__ == "__main__":
    unittest.main()
