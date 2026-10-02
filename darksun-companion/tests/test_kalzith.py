"""Kalzith, the slave pens' defiler: his records, his place, his conversation and his scrolls."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game, gpl, kalzith


def labels_land(ops) -> bool:
    """Every jump in the script lands on the start of a command."""
    starts = {o.at for o in ops}
    for o in ops:
        if o.code in (0x13, 0x3E, 0x3F, 0x63, 0x64) and o.args[0][1] not in starts:
            return False
        if o.code == 0x48 and any(r["goto"][1] not in starts for r in o.args[0]["replies"]):
            return False
    return True


class KalzithTests(unittest.TestCase):
    def test_entity(self):
        """In his pen, once, the table kept in order down the map."""
        e = kalzith.ENTITY
        etab = e.pack(10, 100, 0, 11, -5) + e.pack(10, 2000, 0, 11, -6)
        out = kalzith.with_entity(etab)
        entries = [e.unpack_from(out, i) for i in range(0, len(out), e.size)]
        self.assertEqual(entries[1], (*kalzith.PEN, 0, kalzith.ENTITY_FLAGS, -kalzith.OBJECT))
        self.assertEqual([x[1] for x in entries], sorted(x[1] for x in entries))
        self.assertEqual(kalzith.with_entity(out), out)

    def test_talk(self):
        """The master script runs his conversation when he is talked to: after the other talk
        commands, before the rest, once."""
        master = gpl.encode([(0x6E, [("n", 369), ("n", 139), ("n", -183)]), (0x65, [("n", 1), ("n", 2), ("n", 3)]),
                             (0x31, [])])
        out = kalzith.with_talk(master)
        ops = gpl.decode(out, b"")
        self.assertEqual([o.code for o in ops], [0x6E, 0x6E, 0x65, 0x31])
        self.assertEqual((ops[1].code, ops[1].args), (0x6E, [("n", kalzith.START), ("n", kalzith.SCRIPT), ("n", -kalzith.OBJECT)]))
        self.assertEqual(ops[-1].code, 0x31)
        self.assertEqual(kalzith.with_talk(out), out)

    def test_entry(self):
        """His talk is in the game's table of entry points (saves keep talk commands by number),
        numbered after the game's own, once."""
        e = kalzith.ENTRY
        table = e.pack(0, 0, 0) + e.pack(1, 1, 1) + e.pack(2, 369, 139)
        out = kalzith.with_entry(table)
        self.assertEqual(out[:len(table)], table)
        self.assertEqual(e.unpack_from(out, len(table)), (3, kalzith.START, kalzith.SCRIPT))
        self.assertEqual(kalzith.with_entry(out), out)

    def test_conversation(self):
        """It reads as the game's own: every jump lands on a command, his portrait first, the shop
        his own, the lines no longer than the game's, every way out of it ends it."""
        ops = gpl.decode(kalzith.conversation(), b"")
        self.assertTrue(labels_land(ops))
        # opening as the game's scripts do, and talking starting after that, at his own portrait
        self.assertEqual(ops[0].code, kalzith.BEGIN)
        self.assertEqual(ops[1].at, kalzith.START)
        self.assertEqual((ops[1].code, ops[1].args), (0x54, [("n", kalzith.PORTRAIT)]))
        self.assertIn((0x24, [kalzith.SPEAKER]), [(o.code, o.args) for o in ops])  # (his own shop)
        texts = [s for o in ops for s in gpl.strings(o.args)]
        self.assertTrue(all(len(s) <= kalzith.LINE + 1 for s in texts if not s.startswith("  ")))
        self.assertTrue(any("Kalzith" in s for s in texts))
        replies = [r["text"][1] for o in ops if o.code == 0x48 for r in o.args[0]["replies"]]
        self.assertTrue(all(len(r) <= kalzith.REPLY for r in replies), [r for r in replies if len(r) > kalzith.REPLY])
        self.assertEqual(sum(1 for o in ops if o.code == 0x31), 1)  # (one end; parts are subroutines)
        # the friendly flag set before the shop's menu, the cold one only on the threat
        sets = [o.args for o in ops if o.code == 0x16]
        self.assertIn([("n", 1), ("var", 13, kalzith.FRIENDLY)], sets)
        self.assertIn([("n", 1), ("var", 13, kalzith.COLD)], sets)
        # (the game's global flags are bits: none set to anything but 0 or 1, none the game's own)
        flags = [a for a in sets if a[1][1] == 13]
        self.assertTrue(all(a[0][1] in (0, 1) and a[1][2] > 755 for a in flags), flags)

    def test_menus(self):
        """Each menu is the game's kind: in a loop (63h ... 64h), and each reply a subroutine
        returning to it (15h) before anything ends the talk or shows a menu."""
        ops = gpl.decode(kalzith.conversation(), b"")
        at = {o.at: k for k, o in enumerate(ops)}
        menus = [k for k, o in enumerate(ops) if o.code == 0x48]
        self.assertGreaterEqual(len(menus), 4)
        for k in menus:
            self.assertEqual((ops[k - 1].code, ops[k + 1].code), (0x63, 0x64))
            for r in ops[k].args[0]["replies"]:
                after = [o.code for o in ops[at[r["goto"][1]]:]]
                ends = [c for c in after if c in (0x15, 0x31, 0x48)]
                self.assertEqual(ends[0], 0x15, r["text"])

    def test_ifs_closed(self):
        """Structured as the game's scripts: each "if" (18h, 3Eh) ends with one 67h; 3Eh goes on
        to an "else" (3Fh) or that end; 3Fh is only an "else", going on to an end. (A 67h too
        many or too few ends the script with "BAD GPL EXIT"; a 3Fh anywhere else does nothing.)"""
        ops = gpl.decode(kalzith.conversation(), b"")
        at = {o.at: k for k, o in enumerate(ops)}
        ifs = [k for k, o in enumerate(ops) if o.code == 0x18 and ops[k + 1].code == 0x3E]
        self.assertEqual(sum(1 for o in ops if o.code == 0x67), len(ifs))
        elses = set()
        for k in ifs:
            target = ops[at[ops[k + 1].args[0][1]]]
            self.assertIn(target.code, (0x3F, 0x67))
            if target.code == 0x3F:
                elses.add(target.at)
                self.assertEqual(ops[at[target.args[0][1]]].code, 0x67)
        self.assertEqual({o.at for o in ops if o.code == 0x3F}, elses)

    def test_apology(self):
        """The 50 ceramic apology is offered only to a party with them, and takes them."""
        ops = gpl.decode(kalzith.conversation(), b"")
        menus = [r for o in ops if o.code == 0x48 for r in o.args[0]["replies"]]
        pay = next(r for r in menus if "50 ceramic" in r["text"][1])
        self.assertEqual(pay["if"], ("expr", [kalzith.MONEY, ">=", ("n", 50)]))
        self.assertIn((0x0C, [("n", -50)]), [(o.code, o.args) for o in ops])

    def test_objects(self):
        """His record a slave's (Dinos's) with his name, his own number and a defiler's class; his
        object a person's (Dinos's) with the arena Defiler's picture."""
        dinos = bytearray(159)
        dinos[kalzith.RDFF_NAME:kalzith.RDFF_NAME + 6] = b"Dinos\0"
        struct.pack_into("<h", dinos, kalzith.RDFF_SELF, -kalzith.DINOS)
        chunks = {("RDFF", kalzith.DINOS): bytes(dinos), ("OJFF", kalzith.DINOS): bytes(range(16)),
                  ("OJFF", kalzith.DEFILER): bytes(range(100, 116)), ("BMP ", kalzith.DEFILER): b"bmp"}
        out = kalzith.object_chunks(chunks)
        rec = out[("RDFF", kalzith.OBJECT)]
        self.assertEqual(rec[kalzith.RDFF_NAME:kalzith.RDFF_NAME + 8], b"Kalzith\0")
        self.assertEqual(struct.unpack_from("<h", rec, kalzith.RDFF_SELF)[0], -kalzith.OBJECT)
        self.assertEqual(rec[kalzith.RDFF_CLASS], kalzith.DEFILER_CLASS)
        p = kalzith.OJFF_PICTURE
        self.assertEqual(out[("OJFF", kalzith.OBJECT)], bytes(range(p)) + bytes(range(100 + p, 102 + p)) + bytes(range(p + 2, 16)))
        self.assertNotIn(("BMP ", kalzith.OBJECT), out)  # (his picture is the Defiler's, by number)
        self.assertGreaterEqual(kalzith.OBJECT, 520)  # (past the game's object table)
        self.assertEqual(kalzith.object_chunks({}), {})

    def test_portrait(self):
        """His own face: the game's portrait 61, branded on the brow, at a number the game leaves
        free; the rest of the picture the game's."""
        from dscompanion import icons
        face = [[150] * 32 for _ in range(32)]
        out = kalzith.portrait_chunk({("PORT", kalzith.PORTRAIT_FROM): icons.encode(face)})
        rows = icons.decode(out)
        changed = {(x, y) for y in range(32) for x in range(32) if rows[y][x] != 150}
        x0, y0 = kalzith.BRAND_AT
        self.assertEqual(changed, {(x0 + dx, y0 + dy) for dy, l in enumerate(kalzith.BRAND)
                                   for dx, c in enumerate(l) if c != "."})
        self.assertEqual(rows[y0][x0], kalzith.BRAND_GROOVE)
        self.assertEqual(rows[y0 + 1][x0], kalzith.BRAND_RIM)
        self.assertIsNone(kalzith.portrait_chunk({}))
        self.assertNotEqual(kalzith.PORTRAIT, kalzith.PORTRAIT_FROM)

    def test_scroll(self):
        """The game's own spell scroll, teaching the spell at the price."""
        rec = kalzith.scroll(32, 500, 4)
        self.assertEqual(struct.unpack_from("<h", rec, 0)[0], -1404)  # (each his own object)
        self.assertEqual(struct.unpack_from("<H", rec, kalzith.ITEM_LINK)[0], game.NO_ITEM)
        self.assertEqual(len(rec), game.ITEM_SIZE)
        self.assertEqual(struct.unpack_from("<H", rec, game.ITEM_TYPE)[0], kalzith.SCROLL_TYPE)
        self.assertEqual(struct.unpack_from("<H", rec, kalzith.ITEM_SPELL)[0], 32)
        self.assertEqual(rec[kalzith.ITEM_SPELL_AGAIN], 32)
        self.assertEqual(struct.unpack_from("<H", rec, kalzith.ITEM_VALUE)[0], 500)
        self.assertEqual(rec[game.ITEM_SLOT], 0xFF)

    def test_stock(self):
        """Once a game (the game's flag STOCKED), found by name; Cat's Grace only with its rule."""
        from unittest import mock
        from dscompanion import npcitems
        class Game:
            flags = set()
            def region(self): return kalzith.REGION
            def flag(self, n): return n in self.flags
            def set_flag(self, n, on=True): self.flags.add(n)
            def creatures(self, count):
                t = bytearray(count * game.CREATURE_SIZE)
                at = 9 * game.CREATURE_SIZE + game.CREATURE_NAME
                t[at:at + 8] = b"Kalzith\0"
                return bytes(t)
        gd, given = Game(), []
        with mock.patch.object(npcitems, "add_to", lambda g, i, rec: given.append((i, rec)) or True):
            self.assertEqual(kalzith.stock(gd, cats_grace=False),
                             [n for s, n, _ in kalzith.SCROLLS if s != game.FLAMING_SPHERE])
            self.assertEqual({i for i, _ in given}, {9})
            self.assertIn(kalzith.STOCKED, gd.flags)
            self.assertEqual(kalzith.stock(gd, cats_grace=True), [])  # (done this game)
            gd.flags.clear(); given.clear()
            self.assertEqual(len(kalzith.stock(gd, cats_grace=True)), 6)
            # each scroll its own object
            self.assertEqual(len({struct.unpack_from("<h", r, 0)[0] for _, r in given}), 6)

    def test_six_scrolls(self):
        """Two of each level 1-3, at 100, 250 and 500."""
        self.assertEqual([p for _, _, p in kalzith.SCROLLS], [100, 100, 250, 250, 500, 500])
        self.assertIn(game.FLAMING_SPHERE, [s for s, _, _ in kalzith.SCROLLS])


if __name__ == "__main__":
    unittest.main()
