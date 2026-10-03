"""Tests for monsters.py: the game's resistance rules, with classes as the game has them."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import monsters as M
from dscompanion.monsters import Rule

# resistance classes as the running game holds them
MAGIC_ONLY = [Rule(0x38, 0), Rule(0xB200, 100)]  # class 11
PLUS2_ONLY = [Rule(0x1038, 0), Rule(0xA200, 100)]  # class 13
UNDEADISH = [Rule(0x139, 0), Rule(0xB000, 100)]  # class 4
NO_CRUSHING = [Rule(0x8, 0), Rule(0x30, 100)]  # class 3
ONLY_EDGED = [Rule(0x6A, 0), Rule(0x10, 100)]  # class 7
FIRE_COLD = [Rule(0x6, 0), Rule(0x80, 50), Rule(0x38, 100)]  # class 6
HALF_WEAPONS = [Rule(0x438, 50), Rule(0xF200, 100)]  # class 10


class RuleTests(unittest.TestCase):
    def test_largest_matching_percent(self):
        self.assertEqual(M.damage_percent(MAGIC_ONLY, M.SLASHING), 0)
        self.assertEqual(M.damage_percent(MAGIC_ONLY, M.weapon_kinds(M.SLASHING, 1)), 100)
        self.assertEqual(M.damage_percent(MAGIC_ONLY, M.FIRE | M.MAGIC), 100)
        self.assertEqual(M.damage_percent([], M.FIRE), 100)  # no rule: all of it

    def test_weapon_magic_bits(self):
        self.assertEqual(M.weapon_kinds(M.CRUSHING, 0), 0x8)
        self.assertEqual(M.weapon_kinds(M.CRUSHING, 2), 0x8 | 0x1000 | 0x2000)
        self.assertEqual(M.weapon_kinds(M.PIERCING, 5), 0x20 | 0x1000 | 0x2000 | 0x8000)


class DefenceTests(unittest.TestCase):
    def test_magic_weapons_needed(self):
        d = M.defences(MAGIC_ONLY, 0, False)
        self.assertEqual((d.weapon_plus, d.weapons_immune, d.immune), (1, [], []))
        self.assertEqual(M.short_line(d), "NEEDS +1 WEAPON")
        self.assertEqual(M.describe(d), ["Only +1 or better weapons hurt it."])
        self.assertEqual(M.defences(PLUS2_ONLY, 0, False).weapon_plus, 2)

    def test_immunities_and_halves(self):
        d = M.defences(UNDEADISH, 0, False)
        self.assertEqual((d.weapon_plus, d.immune), (1, ["poison", "draining"]))
        d = M.defences(FIRE_COLD, 0, False)
        self.assertEqual((d.immune, d.half), (["fire", "cold"], ["electricity"]))
        self.assertEqual(M.short_line(d), "IMM FIRE COLD")
        d = M.defences(HALF_WEAPONS, 0, False)
        self.assertTrue(d.weapons_half)
        self.assertEqual(d.half, ["psionic attacks"])

    def test_weapon_kinds_that_never_hurt(self):
        d = M.defences(NO_CRUSHING, 0, False)
        self.assertEqual((d.weapon_plus, d.weapons_immune), (0, ["crushing"]))
        self.assertEqual(M.describe(d), ["Crushing weapons can't hurt it."])
        d = M.defences(ONLY_EDGED, 0, False)
        self.assertEqual(d.weapons_immune, ["crushing", "pointed"])
        self.assertEqual(d.immune, ["fire", "acid"])

    def test_properties_and_undead(self):
        d = M.defences([], (1 << 5) | (1 << 9) | (1 << 3), True)
        self.assertEqual(d.immune, ["poison", "draining"])  # undead
        self.assertEqual(d.special, ["paralysis"])
        text = " ".join(M.describe(d))
        self.assertIn("can't be charmed or held", text.lower())
        self.assertIn("Not held by Grease", text)
        self.assertIn("Undead", text)


class TablesTests(unittest.TestCase):
    def test_reads_the_game_table(self):
        data = bytearray(M.CLASS_MASKS_OFF + M.CLASS_SIZE * M.CLASS_COUNT)
        struct.pack_into("<I", data, 3 * 4, 1 << 24)  # kind 3: a special touch
        data[M.KIND_CLASS_OFF + 3] = 11
        struct.pack_into("<2H", data, M.CLASS_MASKS_OFF + 11 * M.CLASS_SIZE, 0x38, 0xB200)
        data[M.CLASS_PERCENTS_OFF + 11 * M.CLASS_SIZE:M.CLASS_PERCENTS_OFF + 11 * M.CLASS_SIZE + 2] = bytes([0, 100])
        tables = M.MonsterTables(lambda addr, n: bytes(data[:n]), 0)
        d = tables.defences(3, False)
        self.assertEqual((d.weapon_plus, d.special), (1, ["a special touch"]))
        self.assertEqual(tables.defences(99, False).weapon_plus, 0)


class ReasonTests(unittest.TestCase):
    def test_weapon_reason(self):
        """What a monster's defences say about a weapon hit that did less than its dice."""
        def d(**kw):
            base = dict(weapon_plus=0, weapons_immune=[], weapons_half=False, immune=[], half=[], notes=[],
                        special=[], undead=False)
            base.update(kw)
            return M.Defences(**base)
        self.assertEqual(M.weapon_reason(d(weapon_plus=1)), "only +1 or better weapons hurt it")
        self.assertEqual(M.weapon_reason(d(weapon_plus=4)), "weapons can't hurt it")
        self.assertEqual(M.weapon_reason(d(weapons_immune=["crushing"])), "crushing weapons can't hurt it")
        self.assertEqual(M.weapon_reason(d(weapons_half=True)), "non-magical weapons do half")
        self.assertIsNone(M.weapon_reason(d()))


if __name__ == "__main__":
    unittest.main()
