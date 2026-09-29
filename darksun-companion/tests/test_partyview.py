"""The character cards' text, from the layout's displayed values."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game

try:
    from dscompanion import partyview
except ImportError:  # no tkinter in this Python
    partyview = None


@unittest.skipIf(partyview is None, "needs tkinter")
class CardTextTests(unittest.TestCase):
    def test_plain_and_number(self):
        self.assertEqual(partyview.plain("Half-giant (5)"), "Half-giant")
        self.assertEqual(partyview.number("Half-giant (5)"), 5)
        self.assertEqual(partyview.number("12"), 12)
        self.assertIsNone(partyview.number(""))

    def test_classes(self):
        fields = {"Class 1": "Fighter (9)", "Level 1": "2", "Class 2": "Druid (7)", "Level 2": "2",
                  "Class 3": "0", "Level 3": "0"}
        self.assertEqual(partyview.classes_text(fields), "Fighter 2 / Druid 2")

    def test_status_names(self):
        self.assertEqual(game.STATUS_NAMES[1], "Okay")
        self.assertEqual(game.STATUS_NAMES[5], "Dead")


if __name__ == "__main__":
    unittest.main()
