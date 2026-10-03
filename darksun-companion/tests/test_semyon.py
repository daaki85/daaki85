import struct
import unittest

from dscompanion import game, gpl, kalzith, semyon


def _ifs_closed(ops) -> bool:
    depth = 0
    for o in ops:
        depth += o.code == 0x3E
        depth -= o.code == 0x67
        if depth < 0:
            return False
    return depth == 0


class SemyonTests(unittest.TestCase):
    MASTER = gpl.encode([(0x18, [("expr", [("var", 0x8D, 503), "==", ("n", 1)])]), (0x3E, [("n", 21)]),
                         (0x6F, [("n", 38), ("n", 145), ("n", -37)]), (0x67, []),
                         (0x6E, [("n", 1), ("n", 218), ("n", -1000)]), (0x31, [])])

    def test_placement(self):
        """In the pens' master script, just before its end: the game's bytes unmoved (its "if"
        skips to a fixed offset); him made in his pen once he has gone there, once; his talk."""
        out = semyon.with_semyon(self.MASTER)
        self.assertEqual(out[:len(self.MASTER) - 1], self.MASTER[:-1])
        ops = gpl.decode(out, b"")
        self.assertEqual(ops[-1].code, 0x31)
        self.assertTrue(_ifs_closed(ops))
        made = [o for o in ops if o.code == 0x25]
        self.assertEqual(made[0].args[:4], [("n", -semyon.SEMYON), ("n", 1), ("n", semyon.CELL[0]), ("n", semyon.CELL[1])])
        test = next(o for o in ops if o.code == 0x18 and o.at >= len(self.MASTER) - 1)
        self.assertIn(("var", 0x8D, semyon.LEFT), test.args[0][1])  # (left after the fight only)
        self.assertNotIn(("var", 0x8D, semyon.GONE), test.args[0][1])
        self.assertIn(("var", 0x8D, semyon.DIED), test.args[0][1])
        self.assertIn(("var", 0x8D, semyon.PLACED), test.args[0][1])
        skip = next(o for o in ops if o.code == 0x3E and o.at > test.at)
        end_if = next(o for o in ops if o.code == 0x67 and o.at > skip.at)
        self.assertEqual(skip.args[0], ("n", end_if.at))  # (onto its own end, in the whole script)
        self.assertIn((0x6E, [("n", kalzith.START), ("n", semyon.SCRIPT), ("n", -semyon.SEMYON)]),
                      [(o.code, o.args) for o in ops])
        self.assertEqual(semyon.with_semyon(out), out)

    def test_conversation(self):
        """His own portrait; every "if" closed; a greeting for the first meeting and after; a
        menu whose last reply ends the talk."""
        ops = gpl.decode(semyon.conversation(), b"")
        self.assertEqual(ops[0].code, kalzith.BEGIN)
        self.assertEqual((ops[1].code, ops[1].args), (0x54, [("n", semyon.PORTRAIT)]))
        self.assertTrue(_ifs_closed(ops))
        menu = next(o for o in ops if o.code == 0x48)
        self.assertEqual(menu.args[0]["replies"][-1]["text"][1].strip(), "Farewell.")
        text = " ".join(gpl.strings(ops))
        self.assertIn("holding pens", text)

    def test_numbers(self):
        """None of the game's: script past 217 (Kalzith's 218), flags past 755 (Kalzith's
        760-763), his own entry point in the game's table after Kalzith's."""
        self.assertGreater(semyon.SCRIPT, kalzith.SCRIPT)
        self.assertTrue(all(f > 763 for f in (semyon.PLACED, semyon.MET)))
        e = kalzith.ENTRY
        table = kalzith.with_entry(kalzith.with_entry(e.pack(0, 0, 0)), semyon.SCRIPT)
        rows = [e.unpack_from(table, i) for i in range(0, len(table), e.size)]
        self.assertEqual(rows[-1], (2, kalzith.START, semyon.SCRIPT))

    def _arena(self) -> bytes:
        """A script laid out as his arena talk: the command taking him off the map at EXIT."""
        sets, ends = divmod(semyon.EXIT - 1, 5)  # (5-byte commands, then 1-byte ones)
        pad = gpl.encode([(kalzith.BEGIN, [])] + [(0x16, [("n", 0), ("var", 14, 1)])] * sets + [(0x31, [])] * ends)
        self.assertEqual(len(pad), semyon.EXIT)
        return pad + gpl.encode([(semyon.REMOVE, [("n", -semyon.SEMYON), ("n", 255), ("n", 30), ("n", 30), ("n", 0)]),
                                 (0x31, [])])

    def test_exit(self):
        """Where he is taken off the map after the fight: a jump to LEFT set, the same command,
        and back; nothing of the game's moves; once only; other scripts unchanged."""
        arena = self._arena()
        out = semyon.with_exit(arena)
        self.assertEqual(out[:semyon.EXIT], arena[:semyon.EXIT])
        self.assertEqual(out[semyon.EXIT + 3:len(arena)], arena[semyon.EXIT + 3:])
        r = gpl._Reader(out, b"")
        r.i = semyon.EXIT
        jump = gpl._op(r)
        self.assertEqual((jump.code, jump.args), (semyon.GOTO, [("n", len(arena))]))
        added = gpl.decode(out[len(arena):], b"")
        self.assertEqual((added[0].code, added[0].args), (0x16, [("n", 1), ("var", 13, semyon.LEFT)]))
        self.assertEqual(added[1].code, semyon.REMOVE)
        self.assertEqual((added[2].code, added[2].args), (semyon.GOTO, [("n", semyon.EXIT + 12)]))
        self.assertEqual(semyon.with_exit(out), out)
        other = arena[:semyon.EXIT] + gpl.encode([(0x31, [])] * 13)
        self.assertEqual(semyon.with_exit(other), other)

    def test_watch(self):
        """DIED once a creature named Semyon is dead; not for a living one."""
        size = game.CREATURE_SIZE

        class GD:
            def __init__(self, hp):
                rec = bytearray(size)
                struct.pack_into("<h", rec, 0, hp)
                rec[game.CREATURE_NAME:game.CREATURE_NAME + 7] = b"Semyon\0"
                self.table, self.flags = bytes(size * 3) + bytes(rec), set()

            def creatures(self, count):
                return self.table

            def flag(self, n):
                return n in self.flags

            def set_flag(self, n, on=True):
                self.flags.add(n)

        alive, dead = GD(20), GD(0)
        self.assertFalse(semyon.watch(alive))
        self.assertNotIn(semyon.DIED, alive.flags)
        self.assertTrue(semyon.watch(dead))
        self.assertIn(semyon.DIED, dead.flags)
        self.assertFalse(semyon.watch(dead))  # (once)

    def test_flags(self):
        self.assertTrue(all(765 < f < 808 for f in (semyon.LEFT, semyon.DIED)))


if __name__ == "__main__":
    unittest.main()
