"""Cat's Grace in Flaming Sphere's place: the spell's record and name (game.set_cats_grace), the
dice log's line for its 1d6, and DSCLOG's three hooks."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import dicelog, game
from test_dicelog import DS, LOAD_SEG, entry, make_game, raw_for, words

NAME_AT = 0x2000  # DS: where the test puts Flaming Sphere's name
STRENGTH = bytes(range(0x40, 0x60))  # a stand-in for Strength's record


def records(log):
    return (LOAD_SEG + game.SPELLS_SEG) * 16 + game.SPELLS_OFF - 0x10


def setup(log):
    m = log.guest.mem
    info = LOAD_SEG * 16 + game.SPELL_INFO_OFF + (game.FLAMING_SPHERE - 1) * game.SPELL_INFO_SIZE
    m[info] = 2
    struct.pack_into("<H", m, info + 5, NAME_AT)
    m[DS * 16 + NAME_AT:DS * 16 + NAME_AT + 15] = game.SPHERE_NAME + b"\0"
    base = records(log)
    m[base + game.FLAMING_SPHERE * 32:base + game.FLAMING_SPHERE * 32 + 32] = game.SPHERE_RECORD
    m[base + game.STRENGTH_SPELL * 32:base + game.STRENGTH_SPELL * 32 + 32] = STRENGTH


class RecordTests(unittest.TestCase):
    def test_on_and_off(self):
        log = make_game()
        setup(log)
        m, base = log.guest.mem, records(log)
        sphere = slice(base + game.FLAMING_SPHERE * 32, base + game.FLAMING_SPHERE * 32 + 32)
        self.assertTrue(log.game.set_cats_grace(True))
        self.assertEqual(bytes(m[sphere]), STRENGTH)
        self.assertEqual(bytes(m[DS * 16 + NAME_AT:DS * 16 + NAME_AT + 15]), b"CAT'S GRACE\0\0\0\0")
        self.assertEqual(self.effect_entry(log), (NAME_AT, DS, game.GRACE_ICON))  # (its icon on the Effects screen)
        self.assertTrue(log.game.set_cats_grace(False))
        self.assertEqual(bytes(m[sphere]), game.SPHERE_RECORD)
        self.assertEqual(bytes(m[DS * 16 + NAME_AT:DS * 16 + NAME_AT + 15]), b"FLAMING SPHERE\0")
        self.assertEqual(self.effect_entry(log), (game.NO_NAME, DS, 0))  # (as the game has it)

    @staticmethod
    def effect_entry(log):
        at = (LOAD_SEG + game.EFFECT_TABLE_SEG) * 16 + (game.GRACE_EFFECT - 1) * game.EFFECT_ENTRY
        return struct.unpack_from("<HHH", log.guest.mem, at)

    def test_leaves_other_names_alone(self):
        log = make_game()
        setup(log)
        m = log.guest.mem
        m[DS * 16 + NAME_AT:DS * 16 + NAME_AT + 15] = b"SOMETHING ELSE\0"
        self.assertFalse(log.game.set_cats_grace(True))
        self.assertEqual(bytes(m[DS * 16 + NAME_AT:DS * 16 + NAME_AT + 14]), b"SOMETHING ELSE")


class LogTests(unittest.TestCase):
    def roll(self, log, spell, face):
        # Strength's code rolls 1d6; its caller's arguments: target at +6, spell at +0Eh
        return log.describe(entry(raw_for(face, 6), dicelog.DICE_SITE, words(0, 0, 1, 6),
                                  words(0, 0, 0, 0, 0, 0, spell), parent_code=dicelog.STRENGTH_ROLL_RETURN),
                            now=1.0)

    def test_dex_with_the_rule(self):
        log = make_game()
        log.rules = game.RULE_CATS_GRACE
        line = self.roll(log, game.FLAMING_SPHERE, 4)[-1]
        self.assertTrue(line.endswith("'s DEX +4 while it lasts (at most 24)"), line)
        line = self.roll(log, game.STRENGTH_SPELL, 5)[-1]
        self.assertTrue(line.endswith("'s STR +5 while it lasts (at most 24)"), line)


if __name__ == "__main__":
    unittest.main()
