import struct
import unittest

from dscompanion import gpl, kalzith, semyon


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
        self.assertIn(("var", 0x8D, semyon.GONE), test.args[0][1])
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


if __name__ == "__main__":
    unittest.main()
