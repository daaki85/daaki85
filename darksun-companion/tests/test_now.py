"""THAC0 with each weapon and the saves as they stand now (the game's screens and the Ledger's)."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import dicelog, game
from test_dicelog import CREATURES, DS, ITEM_TYPES, ITEMS, LOAD_SEG, SHEETS, make_game, set_effects

THINGS = (LOAD_SEG + game.COMBATANTS_SEG) * 16 + game.COMBATANTS_OFF


def dag():
    """Dag (THAC0 16, STR 24, DEX 16, CON 21): a metal long sword +1 in his right hand (item 5)
    and a wooden bow (item 6, type 11) ready as his missile weapon; saves 13 14 12 15 16."""
    log = make_game()
    m = log.guest.mem
    rec = CREATURES
    m[rec + game.CREATURE_ABILITIES:rec + game.CREATURE_ABILITIES + 3] = bytes((24, 16, 21))
    struct.pack_into("<hhh", m, rec + 8, 40, game.NO_ITEM, game.NO_ITEM)
    struct.pack_into("<Bh", m, THINGS + 40 * 3, game.THING_ITEM, 5)
    struct.pack_into("<h", m, ITEMS + 5 * game.ITEM_SIZE + game.ITEM_NEXT, 6)
    struct.pack_into("<h", m, ITEMS + 6 * game.ITEM_SIZE + game.ITEM_NEXT, game.NO_ITEM)
    struct.pack_into("<H", m, ITEMS + 6 * game.ITEM_SIZE + game.ITEM_TYPE, 11)
    m[ITEMS + 5 * game.ITEM_SIZE + game.ITEM_SLOT] = game.WEAPON_HANDS[0]
    m[ITEMS + 6 * game.ITEM_SIZE + game.ITEM_SLOT] = game.MISSILE_SLOT
    bow = ITEM_TYPES + 11 * game.ITEM_TYPE_SIZE
    m[bow + 0x08], m[bow + 0x0C], m[bow + 0x0D] = 0, 6, 1  # wooden, 1d6
    ds = DS * 16
    m[ds + game.STR_TO_HIT + 24], m[ds + game.DEX_MISSILE + 16] = 6, 1
    m[ds + game.SAVE_CON + 21] = 2
    m[SHEETS + game.SHEET_SAVES:SHEETS + game.SHEET_SAVES + 5] = bytes((13, 14, 12, 15, 16))
    return log


class HitTests(unittest.TestCase):
    def test_each_weapon(self):
        g = dag().game
        self.assertEqual([(h.item, h.thac0, h.parts) for h in g.weapon_hits(0)], [
            (5, 9, [("STR", 6), ("weapon", 1)]),  # 16 - 6 - 1
            (6, 18, [("DEX", 1), ("wooden", -3)])])  # 16 - 1 + 3

    def test_blessed_and_cursed(self):
        log = dag()
        set_effects(log, [(0, 0, 7)])
        self.assertEqual(log.game.weapon_hits(0)[0].thac0, 8)
        set_effects(log, [(0, 0, 7), (0, 0, 12)])  # +1, -1
        self.assertEqual(log.game.weapon_hits(0)[0].thac0, 9)

    def test_unarmed(self):
        log = dag()
        struct.pack_into("<h", log.guest.mem, CREATURES + 8, game.NO_ITEM)
        self.assertEqual([(h.item, h.name, h.thac0) for h in log.game.weapon_hits(0)], [(-1, "unarmed", 10)])


class SaveTests(unittest.TestCase):
    def test_con_on_paralysis_poison_death(self):
        """Dag, a half-giant: CON 21 is +2 on his first save only."""
        self.assertEqual([s.needs for s in dag().game.saves_now(0)], [11, 14, 12, 15, 16])

    def test_blessed_and_spirit_armor(self):
        log = dag()
        set_effects(log, [(0, 0, 7), (0, 0, game.EFFECT_SPIRIT_ARMOR)])
        saves = log.game.saves_now(0)
        self.assertEqual([s.needs for s in saves], [10, 10, 8, 11, 12])  # Spirit Armor: not the first
        self.assertEqual(saves[0].parts, [(1, "Blessed"), (2, "CON 21")])

    def test_never_below_2(self):
        log = dag()
        log.guest.mem[SHEETS + game.SHEET_SAVES] = 3
        self.assertEqual(log.game.saves_now(0)[0].needs, 2)  # a 1 always fails


class RuleTests(unittest.TestCase):
    def test_boots(self):
        log = dag()
        self.assertFalse(log.game.wears_boots(0))
        log.guest.mem[ITEMS + 6 * game.ITEM_SIZE + game.ITEM_SLOT] = game.FOOT
        self.assertTrue(log.game.wears_boots(0))

    def test_rules_for_dsclog(self):
        log = dag()
        log.set_rules(dicelog.RULE_HELMS | dicelog.RULE_BOOTS)
        self.assertEqual(struct.unpack_from("<H", log.guest.mem, log.tsr_hdr + dicelog.TSR_RULES)[0], 3)


class ThiefTests(unittest.TestCase):
    def setUp(self):
        """Dag as a 4th level thief (DEX 16), his long sword in his right hand; the game's tables
        made simple: open locks 18 and +5 for DEX 16, the other skills 0; an equipment penalty
        of 5 on picking pockets and 10 on climbing."""
        self.log = log = dag()
        m = log.guest.mem
        table = (LOAD_SEG + game.THIEF_TABLE_SEG) * 16
        for skill in range(8):
            m[table + game.THIEF_DEX_HIGH + skill] = m[table + game.THIEF_DEX_TOP + skill] = 25
        m[table + game.THIEF_BASE + 1] = 18
        m[table + game.THIEF_DEX_LOW + 1], m[table + game.THIEF_DEX_HIGH + 1], m[table + game.THIEF_DEX_TOP + 1] = 11, 15, 20
        m[table + game.THIEF_ARMOUR + 0], m[table + game.THIEF_ARMOUR + 6] = 5, 10
        m[SHEETS + game.SHEET_CLASSES + 1], m[SHEETS + game.SHEET_LEVELS + 1] = game.THIEF, 4
        m[CREATURES + game.CREATURE_STATUS] = game.STATUS_OKAY

    def now(self):
        return [n for _, n in self.log.game.thief_skills_now(0)]

    def test_equipment(self):
        self.assertEqual(self.now(), [11, 39, 16, 16, 6])
        self.log.guest.mem[ITEMS + 5 * game.ITEM_SIZE + game.ITEM_SLOT] = 0xFF  # put away
        self.log.guest.mem[ITEMS + 6 * game.ITEM_SIZE + game.ITEM_SLOT] = 0xFF
        self.assertEqual(self.now(), [16, 39, 16, 16, 16])

    def test_effects(self):
        set_effects(self.log, [(0, 0, 47)])  # Slowed: all but picking pockets
        self.assertEqual(self.now(), [11, 0, 0, 0, 0])
        set_effects(self.log, [(0, 0, 14)])  # Detect Traps
        self.assertEqual(self.now()[2], 100)

    def test_in_stats(self):
        self.assertEqual(struct.unpack_from("<B5B", self.log.stats_entry(0), 17), (1, 11, 39, 16, 16, 6))


class SettingsTests(unittest.TestCase):
    def test_saved_options(self):
        log = dag()
        log.use_settings({"helm_ac": False, "arena_ring": False})
        self.assertEqual((log.rules, log.arena_ring, log.monster_info), (dicelog.RULE_BOOTS, False, True))


class SpeakerTests(unittest.TestCase):
    def test_announcer_not_relearned(self):
        """A name learned for the Announcer mid-fight (from a Slig) doesn't stick."""
        log = dag()
        log.learned_speakers = {119: "Slig"}
        self.assertEqual(log.speaker(119), "The Announcer")


class StatsTests(unittest.TestCase):
    def test_entry_for_dsclog(self):
        log = dag()
        entry = log.stats_entry(0)
        self.assertEqual(len(entry), dicelog.STATS_SIZE)
        self.assertEqual(struct.unpack_from("<Bb5B", entry), (1, 9, 11, 14, 12, 15, 16))
        self.assertEqual(struct.unpack_from("<3H3b", entry, 8), (5, 6, game.NO_ITEM, 9, 18, 0))

    def test_empty_slot(self):
        self.assertEqual(dag().stats_entry(3), bytes(dicelog.STATS_SIZE))


if __name__ == "__main__":
    unittest.main()
