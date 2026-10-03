"""The downloaded mark taken off the Ledger's own files on Windows (unblock.py)."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import unblock


class UnblockTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        for rel in ("Start Templar's Ledger.bat", os.path.join("dos", "DSCLOG.EXE"),
                    os.path.join("__pycache__", "x.pyc")):
            os.makedirs(os.path.dirname(os.path.join(self.dir, rel)), exist_ok=True)
            open(os.path.join(self.dir, rel), "w").close()
        self.marked = {os.path.join(self.dir, "Start Templar's Ledger.bat") + unblock.MARK}
        self.removed = []

    def remove(self, path):
        if path not in self.marked:
            raise FileNotFoundError(path)
        self.removed.append(path)

    def test_windows(self):
        """Only marked files, inside the folder; __pycache__ not looked in."""
        done = unblock.unblock(self.dir, self.remove, windows=True)
        self.assertEqual(done, [os.path.join(self.dir, "Start Templar's Ledger.bat")])
        self.assertEqual(self.removed, sorted(self.marked))

    def test_elsewhere(self):
        self.assertEqual(unblock.unblock(self.dir, self.remove, windows=False), [])
        self.assertEqual(self.removed, [])

    def test_failure_kept(self):
        def denied(path):
            raise PermissionError(path)
        self.assertEqual(unblock.unblock(self.dir, denied, windows=True), [])

    def test_own_folder(self):
        self.assertTrue(os.path.isdir(os.path.join(unblock.FOLDER, "dscompanion")))


if __name__ == "__main__":
    unittest.main()
