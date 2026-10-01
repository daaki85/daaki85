"""Hiding in shadows and moving silently to backstab (RULE_STEALTH)."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game, stealth
from test_dicelog import CREATURES, DS, HDR, SHEETS, STALKER, far, set_clock


def game_sheet():
    return SHEETS
from test_now import ThiefTests

MAP = 0x60000


def rolls(*faces):
    it = iter(faces)
    return lambda: next(it)


class StealthTests(unittest.TestCase):
    def setUp(self):
        """Dag (combatant 0), a 4th level thief: hide in shadows and move silently 16 each.
        The Mountain Stalker (combatant 0x29) is on the other side, three squares away. In the
        arena unless a test says otherwise."""
        thief = ThiefTests()
        thief.setUp()
        self.log = thief.log
        self.gd = self.log.game
        self.m = self.log.guest.mem
        self.place(0, 10, 10)
        self.place(0x29, 13, 10)
        self.m[CREATURES + STALKER * game.CREATURE_SIZE + game.CREATURE_STATUS] = game.STATUS_OKAY
        struct.pack_into("<h", self.m, CREATURES + STALKER * game.CREATURE_SIZE, 30)
        self.region(0x2A)
        self.m[DS * 16 + stealth.MAP_PTR:DS * 16 + stealth.MAP_PTR + 4] = far(MAP)

    def place(self, combatant, x, y):
        struct.pack_into("<HH", self.m, DS * 16 + stealth.POSITIONS + combatant * stealth.POSITION_SIZE,
                         x * 16 + 8, y * 16 + 8)

    def region(self, number):
        struct.pack_into("<H", self.m, DS * 16 + 0x117C, number)

    def test_outdoors_halved(self):
        lines, hidden = stealth.turn(self.gd, 0, rolls(8, 16))
        self.assertTrue(hidden)
        self.assertEqual(lines[0], "Dag hides in shadows: d100 = 8, needs 8 or less (16, halved in daylight) -> hidden")
        self.assertTrue(lines[1].startswith("  Dag moves silently: d100 = 16, needs 16 or less -> unheard"))

    def test_seen(self):
        self.assertEqual(stealth.turn(self.gd, 0, rolls(9)),
                         (["Dag hides in shadows: d100 = 9, needs 8 or less (16, halved in daylight) -> seen"], False))

    def test_heard(self):
        lines, hidden = stealth.turn(self.gd, 0, rolls(3, 17))
        self.assertFalse(hidden)
        self.assertEqual(lines[1], "  Dag moves silently: d100 = 17, needs 16 or less -> heard")

    def test_indoors(self):
        self.region(0x29)  # the slave pens
        lines, hidden = stealth.turn(self.gd, 0, rolls(16, 1))
        self.assertTrue(hidden)
        self.assertIn("needs 16 or less (16, out of the sun)", lines[0])

    def test_by_the_floor(self):
        """On a map with buildings (0Bh), the tile under the thief: an indoor floor, or not."""
        self.region(0x0B)
        self.m[MAP + 10 * stealth.MAP_WIDTH + 10] = 66
        self.assertFalse(stealth.daylight(self.gd, 0))
        self.m[MAP + 10 * stealth.MAP_WIDTH + 10] = 1
        self.assertTrue(stealth.daylight(self.gd, 0))

    def test_enemy_beside(self):
        self.place(0x29, 11, 11)
        self.assertEqual(stealth.turn(self.gd, 0, rolls()),
                         (["Dag can't hide in shadows: Mountain Stalker is right beside them"], False))

    def test_fallen_enemy_beside(self):
        self.place(0x29, 11, 11)
        struct.pack_into("<h", self.m, CREATURES + STALKER * game.CREATURE_SIZE, 0)
        self.assertTrue(stealth.turn(self.gd, 0, rolls(1, 1))[1])

    def test_friend_beside(self):
        self.place(1, 10, 11)
        self.m[CREATURES + game.CREATURE_SIZE + game.CREATURE_SIDE] = self.m[CREATURES + game.CREATURE_SIDE]
        self.assertTrue(stealth.turn(self.gd, 0, rolls(1, 1))[1])

    def ranger(self, level=10, cls=13):
        """Dag a ranger (air) instead of a thief: AD&D's 63 to hide and 78 to move silently at
        10th level (no race or DEX adjustment in these tables)."""
        self.m[game_sheet() + game.SHEET_CLASSES + 1] = cls
        self.m[game_sheet() + game.SHEET_LEVELS + 1] = level

    def test_ranger_outdoors(self):
        """Under the open sky a ranger hides with the full chance; their attack is from behind,
        no backstab."""
        self.ranger()
        lines, hidden = stealth.turn(self.gd, 0, rolls(63, 78))
        self.assertTrue(hidden)
        self.assertEqual(lines, ["Dag hides in shadows: d100 = 63, needs 63 or less (63, a ranger under the open sky) "
                                 "-> hidden",
                                 "  Dag moves silently: d100 = 78, needs 78 or less -> unheard: their next attack "
                                 "this turn is from behind"])

    def test_ranger_indoors(self):
        self.ranger(level=1)
        self.region(0x29)
        lines, hidden = stealth.turn(self.gd, 0, rolls(6))
        self.assertEqual(lines, ["Dag hides in shadows: d100 = 6, needs 5 or less (10, halved indoors for a ranger) -> seen"])
        self.assertFalse(hidden)

    def test_ranger_effects(self):
        """Not Okay: no hiding for a ranger either."""
        self.ranger()
        self.m[CREATURES + game.CREATURE_STATUS] = 3
        self.assertEqual(self.gd.ranger_skill_now(0, stealth.HIDE), 0)

    def test_thief_and_ranger(self):
        """Thief levels too: hiding as a thief (halved outdoors, the backstab)."""
        self.m[game_sheet() + game.SHEET_CLASSES + 2] = 13
        self.m[game_sheet() + game.SHEET_LEVELS + 2] = 10
        lines, _ = stealth.turn(self.gd, 0, rolls(8, 16))
        self.assertIn("halved in daylight", lines[0])
        self.assertIn("backstab", lines[1])

    def test_not_a_thief(self):
        self.assertEqual(stealth.turn(self.gd, 1, rolls()), ([], False))
        self.assertEqual(stealth.turn(self.gd, 0x29, rolls()), ([], False))

    def test_in_the_log(self):
        """On Dag's turn in a fight: the rolls, and DSCLOG told; the next turn ends it."""
        log = self.log
        log.rules = game.RULE_STEALTH
        log.stealth_roll = rolls(2, 5)
        set_clock(log, 600)
        log._round_time = 600
        struct.pack_into("<h", self.m, DS * 16 + game.WHOSE_TURN, 0)
        lines = log.turn_lines()
        self.assertEqual(lines[0], "Dag's turn")
        self.assertIn("-> hidden", lines[1])
        self.assertEqual(struct.unpack_from("<H", self.m, HDR + stealth.TSR_STEALTH)[0], 1)
        struct.pack_into("<h", self.m, DS * 16 + game.WHOSE_TURN, 0x29)
        self.assertEqual(log.turn_lines(), ["Mountain Stalker's turn"])
        self.assertEqual(struct.unpack_from("<H", self.m, HDR + stealth.TSR_STEALTH)[0], 0)

    def test_rule_off(self):
        log = self.log
        log.rules = 0
        set_clock(log, 600)
        log._round_time = 600
        struct.pack_into("<h", self.m, DS * 16 + game.WHOSE_TURN, 0)
        self.assertEqual(log.turn_lines(), ["Dag's turn"])


if __name__ == "__main__":
    unittest.main()
