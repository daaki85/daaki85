"""Writing the game's scripts: what gpl.decode reads, gpl.encode writes back."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import gpl


class WriteTests(unittest.TestCase):
    def roundtrip(self, ops):
        back = gpl.decode(gpl.encode(ops), b"")
        self.assertEqual([(o.code, o.args) for o in back], [(o[0], o[1]) for o in ops])

    def test_text_menu_flags(self):
        self.roundtrip([
            (0x54, [("n", 79)]),
            (0x18, [("expr", [("var", 0x8D, 1900), "==", ("n", 1)])]),
            (0x3E, [("n", 40)]),
            (0x4F, [("n", 115), ("str", "Ah. The arena's champions.")]),
            (0x16, [("n", 2), ("var", 13, 1900)]),
            (0x16, [("n", -1), ("var", 14, 3)]),
            (0x0C, [("n", -50)]),
            (0x24, [("n", -2300)]),
            (0x48, [{"before": [], "title": ("str", "Kalzith"),
                     "replies": [{"text": ("str", "  Show us."), "goto": ("n", 300), "if": ("n", 1),
                                  "before": [], "after": []}]}]),
            (0x31, []),
        ])

    def test_strings(self):
        for s in ("", "a", "Hello, it's good to meet you.", "x" * 300):
            r = gpl._Reader(b"\x92" + gpl._put_string(s), b"")
            r.byte()
            self.assertEqual(gpl._string(r), ("str", s))
        with self.assertRaises(gpl.ScriptError):
            gpl._put_string("café")

    def test_numbers(self):
        for v in (0, 1, 0x7FFF, -1, -128, 127, -0x8000, 0x8000, 1000000, -1000000):
            self.assertEqual(gpl.decode(gpl.encode([(0x0C, [("n", v)])]), b"")[0].args, [("n", v)])


if __name__ == "__main__":
    unittest.main()
