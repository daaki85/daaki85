import unittest

from dscompanion import gamepatch, gpl, kalzith, pensasks, semyon
from dscompanion.kalzith import _Script


def _game_like() -> bytes:
    """A talk laid out as Dinos's: a part (a subroutine) clearing the menu's local and showing a
    question, the menu in a loop while the local is 0, the answers as subroutines."""
    s = _Script()
    s.op(kalzith.BEGIN)
    s.op(0x13, ("label", "part"))
    s.op(0x31)
    s.label("part")
    s.op(0x16, ("n", 0), ("var", 14, 18))
    s.op(0x16, ("n", 1), ("var", 14, 19))
    s.label("loop")
    s.op(0x18, ("expr", [("var", 0x8E, 18), "==", ("n", 0)]))
    s.op(0x63, ("label", "out"))
    s.op(0x48, {"before": [], "title": ("var", 0x86, 1), "replies": [
        {"text": ("str", "  What do you know about Gilal?"), "goto": ("label", "gilal"),
         "if": ("var", 0x8E, 19), "before": [], "after": []},
        {"text": ("str", "  Let's change the subject."), "goto": ("label", "bye"), "if": ("n", 1), "before": [], "after": []},
        {"text": ("str", "Goodbye."), "goto": ("label", "bye"), "if": ("n", 1), "before": [], "after": []}]})
    s.op(0x64, ("label", "loop"))
    s.label("out")
    s.op(0x15)
    s.label("gilal")
    s.op(0x4F, ("n", 115), ("str", "Gilal was a gladiator. "))
    s.op(0x16, ("n", 0), ("var", 14, 19))
    s.op(0x15)
    s.label("bye")
    s.op(0x16, ("n", 1), ("var", 14, 18))
    s.op(0x15)
    return s.bytes(end=False)


def _ifs_closed(ops) -> bool:
    depth = 0
    for o in ops:
        depth += o.code == 0x3E
        depth -= o.code == 0x67
        if depth < 0:
            return False
    return depth == 0


class PensAsksTests(unittest.TestCase):
    FIRST = "  What do you know about Gilal?"

    def setUp(self):
        self.script = _game_like()
        self.ops = gpl.decode(self.script, b"")
        self.out = pensasks.with_asks(self.script, b"", self.FIRST, pensasks.DINOS_ASKS)
        self.start = next(o for o in self.ops if o.code == 0x16 and o.args == [("n", 0), ("var", 14, 18)])
        self.menu = next(o for o in self.ops if o.code == 0x48)

    def _op_at(self, at):
        r = gpl._Reader(self.out, b"")
        r.i = at
        return gpl._op(r)

    def _ops_from(self, at):
        return [gpl.Op(o.at + at, o.code, o.args) for o in gpl.decode(self.out[at:], b"")]

    def test_game_bytes_kept(self):
        """Only two of the game's commands change, each to a jump (64h) as long as or shorter than
        itself; everything else of the game's is where it was, the new code after it."""
        n = len(self.script)
        self.assertGreater(len(self.out), n)
        changed = {i for i in range(n) if self.out[i] != self.script[i]}
        self.assertLessEqual(changed, {*range(self.start.at, self.start.at + 3), *range(self.menu.at, self.menu.at + 3)})
        for at in (self.start.at, self.menu.at):
            self.assertEqual(self._op_at(at).code, pensasks.GOTO)
            self.assertGreaterEqual(self._op_at(at).args[0][1], n)

    def test_start(self):
        """The menu's part, as before (its local cleared), then the questions' flags, then back to
        the game's next command."""
        ops = self._ops_from(self._op_at(self.start.at).args[0][1])
        self.assertEqual((ops[0].code, ops[0].args), (self.start.code, self.start.args))
        back = next(o for o in ops if o.code == pensasks.GOTO)
        nxt = self.ops[self.ops.index(self.start) + 1]
        self.assertEqual(back.args, [("n", nxt.at)])
        part = ops[:ops.index(back)]
        self.assertTrue(_ifs_closed(part))
        for ask in pensasks.DINOS_ASKS:
            self.assertIn((0x16, [("n", 0), ("var", 13, ask.flag)]), [(o.code, o.args) for o in part])
            self.assertIn((0x16, [("n", 1), ("var", 13, ask.flag)]), [(o.code, o.args) for o in part])
        tests = " ".join(str(o.args) for o in part if o.code == 0x18)
        self.assertIn(str(kalzith.STOCKED), tests)
        self.assertIn(str(-semyon.SEMYON), tests)
        self.assertIn(str(semyon.PLACED), tests)

    def test_menu(self):
        """The game's questions as they were, the new ones after the last about someone (before
        "Let's change the subject." and "Goodbye."), each shown by its flag; after the menu, on to
        what followed the game's."""
        at = self._op_at(self.menu.at).args[0][1]
        ops = self._ops_from(at)
        menu = ops[0]
        self.assertEqual(menu.code, 0x48)
        old, new = self.menu.args[0]["replies"], menu.args[0]["replies"]
        asks = pensasks.DINOS_ASKS
        added = new[1:1 + len(asks)]
        self.assertEqual(new[:1] + new[1 + len(asks):], old)
        self.assertEqual([r["text"] for r in added], [("str", a.text) for a in asks])
        self.assertEqual([r["if"] for r in added], [("var", 0x8D, a.flag) for a in asks])
        self.assertEqual(menu.args[0]["title"], self.menu.args[0]["title"])
        after = self.ops[self.ops.index(self.menu) + 1]
        self.assertEqual((ops[1].code, ops[1].args), (pensasks.GOTO, [("n", after.at)]))
        for reply, ask in zip(added, asks):
            body = self._ops_from(reply["goto"][1])
            body = body[:next(i for i, o in enumerate(body) if o.code == 0x15) + 1]
            said = "".join(t for t in gpl.strings(body)).replace("  ", " ")
            self.assertEqual(said.split(), ask.answer.split())
            self.assertIn((0x16, [("n", 0), ("var", 13, ask.flag)]), [(o.code, o.args) for o in body])

    def test_once(self):
        self.assertEqual(pensasks.with_asks(self.out, b"", self.FIRST, pensasks.DINOS_ASKS), self.out)

    def test_other_menus_untouched(self):
        self.assertEqual(pensasks.with_asks(self.script, b"", "  Something else?", pensasks.DINOS_ASKS), self.script)

    def test_text_sizes(self):
        """Questions fit the reply window; no narration (the speakers' own words)."""
        for ask in pensasks.DINOS_ASKS + pensasks.TRUSTEE_ASKS:
            self.assertLessEqual(len(ask.text), kalzith.REPLY)
            self.assertTrue(ask.text.startswith("  "))

    def test_flags(self):
        """Flags of their own: past Kalzith's and Semyon's (760-765), within what a save keeps."""
        flags = [a.flag for a in pensasks.DINOS_ASKS + pensasks.TRUSTEE_ASKS]
        self.assertEqual(len(set(flags)), len(flags))
        self.assertTrue(all(semyon.MET < f < 808 for f in flags))

    def test_too_long(self):
        """Unchanged if it would be longer than the (bigger) buffer runs."""
        long = self.script + b"\x31" * (pensasks.LONGEST - len(self.script) - 10)
        self.assertEqual(pensasks.with_asks(long, b"", self.FIRST, pensasks.DINOS_ASKS), long)

    def test_buffer(self):
        """The Ledger's game has room for the Trustee's script with the questions (10540 bytes)."""
        self.assertGreaterEqual(pensasks.LONGEST, 10540)
        self.assertGreater(gamepatch.SCRIPT_BUFFER, 10000)

    def test_script_chunks(self):
        """Only the two talks, and only where their menus are."""
        chunks = {("GPL ", pensasks.DINOS_SCRIPT): self.script, ("GPL ", 5): self.script}
        out = pensasks.script_chunks(chunks, b"")
        self.assertEqual(set(out), {("GPL ", pensasks.DINOS_SCRIPT)})


if __name__ == "__main__":
    unittest.main()
