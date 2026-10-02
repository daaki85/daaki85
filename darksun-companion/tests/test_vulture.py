"""The cooked vulture: Dinos's spices, then a meal as good as a full rest."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import dicelog, game, tools, vulture
from test_dicelog import CREATURES, DS, HDR, ITEMS, LOAD_SEG, SHEETS, STALKER, set_clock
from test_slots import set_character, with_tables

DINOS, ITEM = 6, 70


def cooked():
    return bytes.fromhex("b4f501000000010000003c000000000006ff010100")  # the game's own template


class VultureTests(unittest.TestCase):
    def setUp(self):
        """Dag, Daaki and Jellybelly (the party, Jellybelly a 7th level cleric with WIS 18), and
        Dinos (creature 6); the cooked vulture is item 70."""
        self.log = with_tables()
        self.gd = self.log.game
        self.m = self.log.guest.mem
        rec = CREATURES + DINOS * game.CREATURE_SIZE
        self.m[rec + game.CREATURE_NAME:rec + game.CREATURE_NAME + 5] = b"Dinos"
        struct.pack_into("<H", self.m, rec + game.CREATURE_SHEET_INDEX, DINOS)
        for member in range(3):
            self.m[CREATURES + member * game.CREATURE_SIZE + game.CREATURE_STATUS] = game.STATUS_OKAY
            struct.pack_into("<I", self.m, SHEETS + member * game.SHEET_SIZE + game.SHEET_XP, 1000 * (member + 1))
        set_character(self.log, 2, (1, 0, 0), (7, 0, 0), 18)
        self.put(cooked())

    def put(self, rec):
        self.m[ITEMS + ITEM * game.ITEM_SIZE:ITEMS + (ITEM + 1) * game.ITEM_SIZE] = rec

    def item(self):
        return bytes(self.m[ITEMS + ITEM * game.ITEM_SIZE:ITEMS + (ITEM + 1) * game.ITEM_SIZE])

    def use(self, target, fighting=False):
        return vulture.use(self.gd, self.item(), target, fighting)

    def xp(self):
        return [struct.unpack_from("<I", self.m, SHEETS + member * game.SHEET_SIZE)[0] for member in range(3)]

    def test_kinds(self):
        self.assertTrue(vulture.is_vulture(self.item()))
        self.assertFalse(vulture.is_vulture(bytes(game.ITEM_SIZE)))

    def test_dinos(self):
        """Dinos cooks it and the party eats with him: XP, a full rest, and the vulture used up."""
        jelly = CREATURES + 2 * game.CREATURE_SIZE
        sheet = SHEETS + 2 * game.SHEET_SIZE
        struct.pack_into("<hh", self.m, sheet + game.SHEET_MAX_HP, 40, 0)
        struct.pack_into("<h", self.m, sheet + vulture.SHEET_MAX_PSP, 30)
        struct.pack_into("<hh", self.m, jelly, 3, 4)
        self.m[jelly + game.CREATURE_STATUS] = 3  # Out Cold
        priest = DS * 16 + game.SLOTS_LEFT["Priest"] + 2 * game.SLOTS_STRIDE
        self.m[priest:priest + 10] = bytes(10)
        used = self.use(DINOS)
        self.assertEqual(used.text, vulture.MEAL)
        self.assertIn("+100 XP each", used.log[0])
        self.assertEqual(self.xp(), [1100, 2100, 3100])
        self.assertEqual(struct.unpack_from("<hh", self.m, jelly), (40, 30))
        self.assertEqual(self.m[jelly + game.CREATURE_STATUS], game.STATUS_OKAY)
        self.assertEqual(list(self.m[priest + 1:priest + 6]),
                         [self.gd.max_spell_slots(2, 2, level) for level in range(1, 6)])
        self.assertGreater(self.m[priest + 1], 0)
        self.assertTrue(used.used_up)

    def test_the_dead_get_none(self):
        self.m[CREATURES + game.CREATURE_STATUS] = vulture.STATUS_DEAD
        self.use(DINOS)
        self.assertEqual(self.xp(), [1000, 2100, 3100])

    def test_bland(self):
        """Eaten by the party themselves: no use."""
        used = self.use(0)
        self.assertIn("tough and bland", used.text)
        self.assertFalse(used.used_up)

    def test_not_in_a_fight(self):
        used = self.use(DINOS, fighting=True)
        self.assertIn("when the fighting's done", used.text)
        self.assertFalse(used.used_up)
        self.assertEqual(self.xp(), [1000, 2000, 3000])

    def test_others(self):
        """On anyone else, or not the vulture: the game's own doing."""
        self.assertIsNone(self.use(STALKER))
        self.put(bytes(game.ITEM_SIZE))
        self.assertIsNone(self.use(DINOS))

    def test_in_the_log(self):
        """DSCLOG asks: the cooked vulture (item 70) used on object 0x30, Dinos."""
        log = self.log
        table = (LOAD_SEG + game.COMBATANTS_SEG) * 16 + game.COMBATANTS_OFF
        struct.pack_into("<Bh", self.m, table + 0x30 * 3, 2, DINOS)
        struct.pack_into("<H", self.m, HDR + dicelog.TSR_USE_ITEM, ITEM)
        struct.pack_into("<H", self.m, HDR + dicelog.TSR_USE_WHO, 0x30)
        struct.pack_into("<H", self.m, HDR + dicelog.TSR_USE_SEQ, 1)
        struct.pack_into("<H", self.m, HDR + dicelog.TSR_HDR_OFF, 0)
        struct.pack_into("<H", self.m, HDR + dicelog.TSR_PICK_OFF, 0x600)
        set_clock(log, 5000)
        lines = log._answer_use()
        self.assertTrue(lines[0].startswith("Dinos cooks the vulture"))
        self.assertEqual(struct.unpack_from("<H", self.m, HDR + dicelog.TSR_USE_TAKEN)[0], 2)  # used up
        self.assertTrue(bytes(self.m[HDR + 0x600:HDR + 0x600 + 12]).startswith(b'Dinos: "A vu'))


    def ask(self, item, rec):
        """DSCLOG asks about ITEM (REC) used on object 0x30, Dinos: the lines, and the reply's text."""
        log = self.log
        self.m[ITEMS + item * game.ITEM_SIZE:ITEMS + (item + 1) * game.ITEM_SIZE] = rec
        table = (LOAD_SEG + game.COMBATANTS_SEG) * 16 + game.COMBATANTS_OFF
        struct.pack_into("<Bh", self.m, table + 0x30 * 3, 2, DINOS)
        struct.pack_into("<H", self.m, HDR + dicelog.TSR_USE_ITEM, item)
        struct.pack_into("<H", self.m, HDR + dicelog.TSR_USE_WHO, 0x30)
        seq = struct.unpack_from("<H", self.m, HDR + dicelog.TSR_USE_SEQ)[0] + 1
        struct.pack_into("<H", self.m, HDR + dicelog.TSR_USE_SEQ, seq)
        struct.pack_into("<H", self.m, HDR + dicelog.TSR_HDR_OFF, 0)
        struct.pack_into("<H", self.m, HDR + dicelog.TSR_PICK_OFF, 0x600)
        lines = log._answer_use()
        return lines, bytes(self.m[HDR + 0x600:HDR + 0x700]).split(b"\0")[0].decode("cp437")

    def test_fighting_is_the_games_flag(self):
        """A fight is on while the game's flag (DS:1168h) says so: not for the minutes after it,
        as when only the game clock was looked at (it hardly moves outside fights: Dinos wouldn't
        take the vulture until the party rested)."""
        log = self.log
        set_clock(log, 5000)
        log._round_time = 4990  # (a round a moment ago, by the clock)
        struct.pack_into("<H", self.m, DS * 16 + game.IN_COMBAT, 0)
        self.assertFalse(log._fighting())
        struct.pack_into("<H", self.m, DS * 16 + game.IN_COMBAT, 1)
        self.assertTrue(log._fighting())

    def test_no_pockets_picked_in_a_fight(self):
        """The thieves' tools do nothing in a fight (they stay on the pointer); out of one, they try."""
        struct.pack_into("<H", self.m, DS * 16 + game.IN_COMBAT, 1)
        lines, text = self.ask(71, tools.ITEM)
        self.assertEqual((lines, text), ([tools.NOT_IN_A_FIGHT], tools.NOT_IN_A_FIGHT))
        self.assertEqual(struct.unpack_from("<H", self.m, HDR + dicelog.TSR_USE_TAKEN)[0], 1)
        struct.pack_into("<H", self.m, DS * 16 + game.IN_COMBAT, 0)
        lines, text = self.ask(71, tools.ITEM)
        self.assertNotEqual(text, tools.NOT_IN_A_FIGHT)


if __name__ == "__main__":
    unittest.main()
