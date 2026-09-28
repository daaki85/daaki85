"""Decoding dice log entries into text, against a fake game memory."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import dicelog, game
from dscompanion.dicelog import DiceLog, Entry

LOAD_SEG = 0x1A2
DS = 0x44F8
CREATURES = 0x71000


class FakeGuest:
    def __init__(self):
        self.mem = bytearray(0x110000)

    def read(self, addr, size):
        return bytes(self.mem[addr:addr + size])

    def write(self, addr, data):
        self.mem[addr:addr + len(data)] = data


def make_game():
    guest = FakeGuest()
    struct.pack_into("<HH", guest.mem, DS * 16 + game.CREATURES_PTR, CREATURES & 0xF, CREATURES >> 4)
    for index, (name, strength) in enumerate([("Dag", 24), ("Daaki", 20)] + [("", 12)] * 5 + [("Mountain Stalker", 12)]):
        rec = CREATURES + index * game.CREATURE_SIZE
        guest.mem[rec + game.CREATURE_NAME:rec + game.CREATURE_NAME + len(name)] = name.encode()
        guest.mem[rec + dicelog.CREATURE_STR] = strength
    seg, off, stride = dicelog.COMBATANTS
    table = (LOAD_SEG + seg) * 16 + off
    for combatant, creature in ((1, 0), (0x29, 7)):
        struct.pack_into("<Bh", guest.mem, table + combatant * stride, 2, creature)
    log = DiceLog(guest)
    log.rand_addr = LOAD_SEG * 16 + dicelog.RAND_IP
    return log


def entry(raw, code, frame=b"", parent=b"", glob=(0, 0, 0, 0), parent_code=b"", bp=0xFE00, locals_=b""):
    data = bytearray(Entry.SIZE)
    struct.pack_into("<8H", data, 0, 1, 0x10, 0x5000, raw, bp, DS, DS, 0xFE40)
    data[16:16 + len(frame)] = frame
    data[48:48 + len(parent)] = parent
    struct.pack_into("<4H", data, 64, *glob)
    data[72:72 + len(locals_)] = locals_
    data[88:88 + len(code)] = code
    data[112:112 + len(parent_code)] = parent_code
    return Entry.parse(bytes(data))


def frame(*words_from_bp2):
    return struct.pack(f"<{len(words_from_bp2)}h", *words_from_bp2)


def raw_for(face, sides):
    """A rand() result that gives `face` (1-based) on a die with `sides` sides."""
    return (face - 1) * 0x8000 // sides + 1


class DescribeTests(unittest.TestCase):
    def attack(self, d20, thac0=10, ac=4):
        # frame from BP+2: return address (2 words), then [BP+6] dword, [BP+0Ah] THAC0, [BP+0Ch] AC, [BP+0Eh] attacker
        return entry(raw_for(d20, 20), dicelog.ATTACK_SITE, frame(0, 0, 0, 0, thac0, ac, 0), glob=(0x29, 0, 0, 0))

    def test_attack_hit_and_miss(self):
        log = make_game()
        self.assertEqual(log.describe(self.attack(18)),
                         "Dag attacks Mountain Stalker: d20 = 18, needs 6 (THAC0 10 with bonuses, target AC 4) -> HIT")
        self.assertTrue(log.describe(self.attack(5)).endswith("-> miss"))
        self.assertIn("(natural 1)", log.describe(self.attack(1, thac0=1)))
        self.assertTrue(log.describe(self.attack(20, thac0=30)).endswith("(natural 20), needs 26 "
                                                                          "(THAC0 30 with bonuses, target AC 4) -> HIT"))

    def test_weapon_damage_groups_dice_and_adds_strength(self):
        log = make_game()
        # dice frame: return address, [BP+6] count, [BP+8] sides, [BP+0Ah] bonus;
        # the attack's frame from BP+0Ah: THAC0, AC, attacker, sheet, weapon, item, mode
        parent = frame(10, 4, 0, 0, 0, 0, 1)
        dice = [entry(raw_for(face, 6), dicelog.DICE_SITE, frame(0, 0, 2, 6, 0), parent, (0x29, 0, 0, 0),
                      dicelog.WEAPON_DAMAGE_RETURN) for face in (2, 5)]
        self.assertIsNone(log.describe(dice[0]))  # waits for the second die
        self.assertEqual(log.describe(dice[1]),
                         "  Dag hits Mountain Stalker for 19: 2d6 = [2 + 5] + 12 STR 24")

    def test_missile_damage_has_no_strength_bonus(self):
        log = make_game()
        parent = frame(10, 4, 0, 0, 0, 0, 2)
        e = entry(raw_for(3, 8), dicelog.DICE_SITE, frame(0, 0, 1, 8, 1), parent, (0x29, 0, 0, 0),
                  dicelog.WEAPON_DAMAGE_RETURN)
        self.assertEqual(log.describe(e), "  Dag hits Mountain Stalker for 4: 1d8+1 = [3] + 1")

    def test_other_dice_only_when_showing_everything(self):
        log = make_game()
        e = entry(raw_for(4, 10), dicelog.DICE_SITE, frame(0, 0, 1, 10, 0))
        self.assertIsNone(log.describe(e))
        self.assertEqual(log.describe(e, show_all=True), "Dice: 1d10 = [4] = 4")

    def test_ability_check(self):
        log = make_game()
        rec = CREATURES + 1 * game.CREATURE_SIZE  # Daaki
        log.guest.mem[rec + dicelog.CREATURE_ABILITIES + 1] = 16  # DEX
        seg, off = dicelog.CHECK_MODS
        log.guest.mem[(LOAD_SEG + seg) * 16 + off + 3] = 0xFE  # -2
        # frame: return address, [BP+6] creature, [BP+8] modifier index, [BP+0Ah] ability
        e = entry(raw_for(14, 20), dicelog.CHECK_SITE, frame(0, 0, 1, 3, 1))
        self.assertEqual(log.describe(e),
                         "Daaki DEX check: d20 = 14, needs 14 or less (DEX 16 - 2) -> success")

    def test_percentile_check(self):
        log = make_game()
        locals_ = bytes(14) + struct.pack("<h", 35)  # [BP-2] = the chance
        self.assertEqual(log.describe(entry(1234, dicelog.PERCENT_SITE, locals_=locals_)),
                         "Percentile check: d100 = 35, needs 35 or less -> success")

    def test_generic_shapes_when_showing_everything(self):
        log = make_game()
        d10 = bytes.fromhex("660fbfc0666bc00a66bb00800000669966f7fb40")
        range200 = bytes.fromhex("660fbfc06669c0c800000066bb00800000669966f7fb")
        self.assertIsNone(log.describe(entry(raw_for(7, 10), d10)))
        self.assertEqual(log.describe(entry(raw_for(7, 10), d10), show_all=True), "d10 = 7  (at 5000:0010)")
        self.assertEqual(log.describe(entry(100 * 0x8000 // 200 + 1, range200), show_all=True),
                         "0-199 = 100  (at 5000:0010)")


class PollTests(unittest.TestCase):
    def test_new_entries_in_order_and_missed_ones_counted(self):
        log = make_game()
        hdr = 0xD0000
        nent, esize, ring = 4, Entry.SIZE, 0x100
        log.tsr_hdr, log.last_seq = hdr, 0
        struct.pack_into("<5H", log.guest.mem, hdr + 8, 6, 2, nent, esize, ring)
        struct.pack_into("<H", log.guest.mem, hdr + 20, 0)
        for seq in (3, 4, 5, 6):  # 1 and 2 were overwritten
            struct.pack_into("<H", log.guest.mem, hdr + ring + ((seq - 1) % nent) * esize, seq)
        self.assertEqual([e.seq for e in log.poll()], [3, 4, 5, 6])
        self.assertEqual(log.missed, 2)
        self.assertEqual(log.poll(), [])


if __name__ == "__main__":
    unittest.main()
