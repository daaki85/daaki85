"""Tests for spellbook.py: the Spells tab's text, from hand-made spell records."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import spellbook
from dscompanion.game import SpellDamage, SpellRules


class StubGame:
    def __init__(self, damage=None, rules=None, negates=False, name="Spell"):
        self.damage, self.rules, self.negates, self.name = damage, rules, negates, name

    def spell_damage(self, spell):
        return self.damage

    def spell_rules(self, spell):
        return self.rules

    def save_negates_damage(self, spell):
        return self.negates

    def spell_name(self, spell):
        return self.name


def record(dice=0, per_level=0, unit=0, effect=0, kinds=0, save=0):
    rec = bytearray(32)
    rec[4] = dice
    struct.pack_into("<Hh", rec, 5, per_level, unit)
    struct.pack_into("b", rec, 0x19, effect)
    struct.pack_into("<H", rec, 0x1A, kinds)
    rec[0x1F] = save
    return bytes(rec)


class TextTests(unittest.TestCase):
    def test_fireball(self):
        gd = StubGame(SpellDamage(0, 1, 0, 1, 0, 6), SpellRules(True, 0, "fire"))
        rec = record(kinds=0x202, save=(4 << 5) | 1)
        self.assertEqual(spellbook.damage_text(gd, 27, rec),
                         "1d6 for each caster level, counting at most level 10 [fire]")
        self.assertEqual(spellbook.save_text(gd, 27, rec, True),
                         "petrification/polymorph, d20 doubled (against fire); saving halves the damage")
        self.assertEqual(spellbook.lasts_text(gd, 27, rec), "")  # instant

    def test_durations_and_charges(self):
        gd = StubGame(SpellDamage(0, 0, 0, 1, 0, 0))
        self.assertEqual(spellbook.lasts_text(gd, 1, record(per_level=5, unit=60)), "5 rounds for each caster level")
        self.assertEqual(spellbook.lasts_text(gd, 1, record(dice=0x42, unit=60)), "2d4 rounds")
        self.assertEqual(spellbook.lasts_text(gd, 1, record(per_level=1, dice=0x41, unit=-1)),
                         "1 charge for each caster level + 1d4 charges")
        self.assertEqual(spellbook.lasts_text(gd, 1, record(per_level=1, unit=600)),
                         "(1 for each caster level) x 10 rounds")
        self.assertEqual(spellbook.lasts_text(gd, 1, record(unit=-9999)), "until removed")

    def test_effects_and_no_save(self):
        self.assertEqual(spellbook.effect_text(record(effect=7)), "Blessed: +1 to hit, +1 on saves")
        self.assertEqual(spellbook.effect_text(record(effect=-17)), "removes Afraid")
        self.assertEqual(spellbook.save_text(StubGame(), 1, record(save=(6 << 5) | 1), False), "none")

    def test_own_dice_noted(self):
        gd = StubGame(SpellDamage(1, 1, 1, 2, 0, 4), name="Magic Missile")
        self.assertIn("its own code", spellbook.damage_text(gd, 3, record(kinds=0x200)))


if __name__ == "__main__":
    unittest.main()
