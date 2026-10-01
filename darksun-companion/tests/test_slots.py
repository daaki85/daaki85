"""Spell slots: what's left, and the most the game gives (its tables, as the game holds them)."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game
from test_dicelog import DS, LOAD_SEG, SHEETS, make_game

# The game's own tables (read from a running game): the rule numbers for each class number
# (clerics and druids 1-8: rules 3 then 4, preserver 11: rule 1, rangers 13-16: rule 2) and the
# rule words, and which classes cast which magic (bit 1 wizard, bit 2 priest)
CLASS_RULES = bytes([0] + [0x43] * 8 + [0, 0, 0x01, 0, 0x02, 0x02, 0x02, 0x02, 0])
RULES = (0x0000, 0x0500, 0x0331, 0x0900, 0x0360)
MAGIC = {c: 2 for c in list(range(1, 9)) + [13, 14, 15, 16]}
MAGIC[11] = 1
DRUID, FIGHTER, PRESERVER, PSIONICIST = 5, 9, 11, 12


def with_tables():
    log = make_game()
    m = log.guest.mem
    m[DS * 16 + game.SLOT_CLASS_RULES:DS * 16 + game.SLOT_CLASS_RULES + len(CLASS_RULES)] = CLASS_RULES
    struct.pack_into(f"<{len(RULES)}H", m, DS * 16 + game.SLOT_RULES, *RULES)
    magic = (LOAD_SEG + game.CLASS_MAGIC_SEG) * 16 + game.CLASS_MAGIC_OFF
    for cls, bits in MAGIC.items():
        m[magic + cls * 4] = bits
    return log


def set_character(log, member, classes, levels, wis, race=2):
    m = log.guest.mem
    sheet = SHEETS + member * game.SHEET_SIZE
    m[sheet + game.SHEET_CLASSES:sheet + game.SHEET_CLASSES + 3] = bytes(classes)
    m[sheet + game.SHEET_LEVELS:sheet + game.SHEET_LEVELS + 3] = bytes(levels)
    m[sheet + game.SHEET_RACE] = race
    creature = game.far_pointer(log.guest, DS, game.CREATURES_PTR) + member * game.CREATURE_SIZE
    m[creature + game.CREATURE_ABILITIES + 4] = wis


class SlotTests(unittest.TestCase):
    def test_seen_in_play(self):
        """Two characters fresh from the start of a game: the game had filled their slots
        with exactly these."""
        log = with_tables()
        g = game.GameData(log.guest, DS)
        # K'ratchek, thri-kreen fighter/druid/psionicist 2/2/2 with WIS 19: druid's 1 first-level
        # slot plus WIS 19's bonus, which counts at spell levels the druid can't cast yet
        set_character(log, 1, (FIGHTER, DRUID, PSIONICIST), (2, 2, 2), 19, race=8)
        self.assertEqual([g.max_spell_slots(1, 2, level) for level in range(1, 6)], [5, 3, 2, 1, 0])
        self.assertEqual([g.max_spell_slots(1, 1, level) for level in range(1, 3)], [0, 0])
        # ... but the druid casts only first-level spells yet: only those are shown
        self.assertEqual([g.max_spell_slots(1, 2, level, wis=False) for level in range(1, 3)], [2, 0])
        self.assertEqual(g.spell_slots(1), [("Priest", [(1, 0, 5)])])
        # Cermak, preserver/gladiator 1/3: one first-level wizard slot (WIS doesn't count)
        set_character(log, 2, (PRESERVER, 10, 0), (1, 3, 0), 17)
        self.assertEqual([g.max_spell_slots(2, 1, level) for level in range(1, 3)], [1, 0])

    def test_left_and_most(self):
        log = with_tables()
        g = game.GameData(log.guest, DS)
        set_character(log, 2, (PRESERVER, 10, 0), (1, 3, 0), 17)
        log.guest.mem[DS * 16 + game.SLOTS_LEFT["Wizard"] + 2 * game.SLOTS_STRIDE + 1] = 0  # cast it
        self.assertEqual(g.spell_slots(2), [("Wizard", [(1, 0, 1)])])
        set_character(log, 0, (FIGHTER, 0, 0), (5, 0, 0), 18)
        self.assertEqual(g.spell_slots(0), [])

    def test_human_dual_class(self):
        """A human's second class counts only while its level is below the first's."""
        log = with_tables()
        g = game.GameData(log.guest, DS)
        set_character(log, 0, (FIGHTER, PRESERVER, 0), (5, 3, 0), 10, race=game.HUMAN)
        self.assertEqual(g.max_spell_slots(0, 1, 1), 2)
        set_character(log, 0, (FIGHTER, PRESERVER, 0), (5, 5, 0), 10, race=game.HUMAN)
        self.assertEqual(g.max_spell_slots(0, 1, 1), 0)

    def test_levels_reached(self):
        """A 7th level cleric with WIS 18 casts spells up to the 4th level: the game's 5th-level
        bonus slot isn't shown."""
        log = with_tables()
        g = game.GameData(log.guest, DS)
        set_character(log, 0, (1, 0, 0), (7, 0, 0), 18)
        self.assertEqual([level for level, _, _ in g.spell_slots(0)[0][1]],
                         [n for n in range(1, 8) if g.max_spell_slots(0, 2, n, wis=False)])
        self.assertEqual(max(level for level, _, _ in g.spell_slots(0)[0][1]), 4)

    def test_text(self):
        self.assertEqual(game.slots_text([(1, 3, 5), (2, 0, 2)]), "1st 3/5, 2nd 0/2")


if __name__ == "__main__":
    unittest.main()
