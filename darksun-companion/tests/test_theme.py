"""Accessibility checks on the window's colours (AODA: WCAG 2.0 level AA)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import palette


class ContrastTests(unittest.TestCase):
    def test_contrast_formula(self):
        self.assertAlmostEqual(palette.contrast("#000000", "#FFFFFF"), 21.0, places=3)
        self.assertAlmostEqual(palette.contrast("#777777", "#FFFFFF"), 4.48, places=2)

    def test_every_text_colour_meets_aa(self):
        for use, (text, background) in palette.TEXT_PAIRS.items():
            with self.subTest(use):
                self.assertGreaterEqual(palette.contrast(text, background), 4.5,
                                        f"{use}: {text} on {background}")

    def test_the_rock_behind_the_title_is_dark_enough_everywhere(self):
        for rock in palette.ROCK:
            self.assertGreaterEqual(palette.contrast(palette.AMBER, rock), 4.5, rock)
            self.assertGreaterEqual(palette.contrast(palette.SAND, rock), 4.5, rock)


if __name__ == "__main__":
    unittest.main()
