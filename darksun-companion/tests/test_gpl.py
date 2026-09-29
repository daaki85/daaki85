"""Tests for the game-script decoder (dscompanion/gpl.py), on hand-made scripts."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import gpl


def packed(text: str) -> bytes:
    """A type-5 string: 7-bit codes, most significant bit first, ending with code 3."""
    bits = "".join(f"{ord(c):07b}" for c in text) + f"{3:07b}"
    bits += "0" * (-len(bits) % 8)
    return bytes([5]) + bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8))


FIELDS = bytes(256)


class DecodeTests(unittest.TestCase):
    def test_terms(self):
        # 16h: set variable 81h:05 to 2 + (-3 * 1000)
        script = bytes([0x16, 0x00, 0x02, 0xD1, 0xE2, 0x8F, 0xFD, 0xD3, 0x90, 0x03, 0xE8, 0xE1, 0x81, 0x05])
        (op,) = gpl.decode(script, FIELDS)
        self.assertEqual(op.code, 0x16)
        self.assertEqual(op.args[0], ("expr", [("n", 2), "+", "(", ("n", -3), "*", ("n", 1000), ")"]))
        self.assertEqual(op.args[1], ("var", 1, 5))

    def test_string(self):
        (op,) = gpl.decode(bytes([0x23]) + packed("The door is locked."), FIELDS)
        self.assertEqual(list(gpl.strings(op)), ["The door is locked."])

    def test_menu(self):
        script = (bytes([0x48, 0x92]) + packed("Pick the lock?") + bytes([0x92]) + packed("Yes") +
                  bytes([0x00, 0x40, 0x8F, 0x01, 0x92]) + packed("No") + bytes([0x00, 0x60, 0x8F, 0x01, 0x4A, 0x15]))
        menu, ret = gpl.decode(script, FIELDS)
        self.assertEqual((menu.code, ret.code), (0x48, 0x15))
        replies = menu.args[0]["replies"]
        self.assertEqual([r["goto"] for r in replies], [("n", 0x40), ("n", 0x60)])
        self.assertEqual(list(gpl.strings(menu)), ["Pick the lock?", "Yes", "No"])

    def test_unknown_command(self):
        with self.assertRaises(gpl.ScriptError):
            gpl.decode(bytes([0x81]), FIELDS)


class CheckTests(unittest.TestCase):
    def test_skill_and_ability_checks(self):
        script = (bytes([0x23]) + packed("The wall is slippery.") +
                  bytes([0x22, 0x8F, 0x03, 0x89, 0x25, 0x8F, 0x06, 0x8F, 0xFE]) +  # climb walls, -2
                  bytes([0x22, 0x8F, 0x03, 0x7F, 0xFE, 0x8F, 0x05, 0x8F, 0x00]) +  # the party hears noise
                  bytes([0x22, 0x8F, 0x10, 0x8F, 0x00, 0x8F, 0x00, 0x8F, 0x00]) +  # another action
                  bytes([0x22, 0x8F, 0x07, 0x91, 0x07, 0xF7, 0x8F, 0x3B, 0x8F, 0x0F]) +  # a trap goes off
                  bytes([0x59, 0x89, 0x25, 0x8F, 0x01, 0x8F, 0x05]))  # a CHA check
        found = gpl.checks({("GPL ", 7): script}, FIELDS)
        self.assertEqual([(c.kind, c.what, c.bonus) for c in found],
                         [("skill", "climb walls", -2), ("skill", "hear noise", 0),
                          ("trap", "find/remove traps", 0), ("ability", "CHA", None)])
        self.assertIn("object -2039", found[2].who)
        self.assertEqual(found[0].who, "the character acting")
        self.assertTrue(found[1].who.startswith("party"))
        self.assertEqual(found[0].script, "GPL 7")
        self.assertIn("The wall is slippery.", found[0].text)


if __name__ == "__main__":
    unittest.main()
