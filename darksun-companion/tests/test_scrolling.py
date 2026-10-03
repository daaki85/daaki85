import struct
import sys
import unittest

from dscompanion import scrolling

HDR = 0x9000


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

    def words(self, at, n):
        return struct.unpack(f"<{n}H", self.guest.read(HDR + at, 2 * n))


class ScrollingTests(unittest.TestCase):
    def test_notch_pan(self):
        """A notch away from you: the view up (or left, sideways); toward you: down."""
        self.assertEqual(scrolling.notch_pan(120, False), (0, -scrolling.NOTCH_PIXELS))
        self.assertEqual(scrolling.notch_pan(-240, False), (0, 2 * scrolling.NOTCH_PIXELS))
        self.assertEqual(scrolling.notch_pan(120, True), (-scrolling.NOTCH_PIXELS, 0))

    def test_update(self):
        """The switch written when it changes (and again for a new DSCLOG), the wheel's pixels
        added to DSCLOG's totals (wrapping), none while switched off."""
        gd, s = Game(), scrolling.Scrolling()
        s.update(gd, HDR, True)
        self.assertEqual(gd.words(scrolling.TSR_SCROLL_ON, 3), (1, 0, 0))
        s.add(0, -48)
        s.add(16, 0)
        s.update(gd, HDR, True)
        self.assertEqual(gd.words(scrolling.TSR_PAN_X, 2), (16, 0x10000 - 48))
        s.update(gd, HDR, True)
        self.assertEqual(gd.words(scrolling.TSR_PAN_X, 2), (16, 0x10000 - 48))
        gd.guest.write(HDR + scrolling.TSR_SCROLL_ON, b"\0\0")  # (the game started again)
        s.forget()
        s.update(gd, HDR, True)
        self.assertEqual(gd.words(scrolling.TSR_SCROLL_ON, 1), (1,))
        s.update(gd, HDR, False)
        s.add(8, 8)
        s.update(gd, HDR, False)
        self.assertEqual(gd.words(scrolling.TSR_SCROLL_ON, 3), (0, 16, 0x10000 - 48))
        s.update(gd, HDR, True, right=True)  # (the right button too)
        self.assertEqual(gd.words(scrolling.TSR_SCROLL_ON, 1), (scrolling.DRAG_MIDDLE | scrolling.DRAG_RIGHT,))

    @unittest.skipIf(sys.platform == "win32", "the hook is Windows'")
    def test_wheel_elsewhere(self):
        """Outside Windows there is no wheel to watch."""
        self.assertFalse(scrolling.WheelWatch(lambda: None, lambda dx, dy: None).start())


if __name__ == "__main__":
    unittest.main()
