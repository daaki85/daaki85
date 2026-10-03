"""Finding the parts of a party member's map sprite: head, hair, shoulders, hands, waist, feet."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import spriteparts as sp

# A figure drawn as the human man's (model 2095): h his hair, s skin, k his black clothes, g the
# green wristbands, b boots
COLOURS = {"h": 69, "s": 146, "k": 254, "g": 249, "b": 210, ".": None}
FIGURE = (
    "......hhhh......",  # 0
    ".....hhhhhh.....",
    ".....hssssh.....",
    ".....hssssh.....",
    "......ssss......",
    "..sssskkkkssss..",  # 5: the shoulders
    ".ss..kkkkkk..ss.",
    ".ss..kkkkkk..ss.",
    ".ss..kkkkkk..ss.",
    ".gg..kkkkkk..gg.",
    ".ss..kkkkkk..ss.",
    "......kkkk......",
    "......k..k......",
    "......s..s......",
    "......s..s......",
    ".....bb..bb.....",
)


def rows(picture=FIGURE):
    return [[COLOURS[ch] for ch in line] for line in picture]


class PartsTests(unittest.TestCase):
    def test_front(self):
        p = sp.find(rows(), 2095, 0)
        self.assertEqual(p.facing, sp.FRONT)
        self.assertEqual((p.head.top, p.head.left, p.head.right), (0, 5, 10))
        self.assertLess(p.head.brow, 5)
        self.assertEqual(p.shoulders, (5, 2, 13))
        # facing the viewer, their right hand is on the left of the picture
        self.assertEqual(p.hands, {"right": (1, 11), "left": (14, 11)})
        self.assertTrue(5 < p.waist < 15)
        self.assertEqual([(y, a, b) for y, a, b in p.feet], [(15, 5, 6), (15, 9, 10)])
        self.assertEqual(p.bottom, 15)

    def test_hair_is_only_the_hair(self):
        p = sp.find(rows(), 2095, 0)
        self.assertIn((6, 0), p.hair)
        self.assertIn((5, 2), p.hair)
        self.assertFalse(any(y >= 5 for _, y in p.hair))  # (not his black clothes)

    def test_back(self):
        """From behind, their right hand is on the right."""
        p = sp.find(rows(), 2095, 1)
        self.assertEqual(p.facing, sp.BACK)
        self.assertEqual(p.hands, {"left": (1, 11), "right": (14, 11)})

    def test_one_hand(self):
        """One wristband: named by the side of the body it is on."""
        one = [line[:8] + line[8:].replace("g", "s") for line in FIGURE]
        self.assertEqual(sp.find(rows(one), 2095, 0).hands, {"right": (1, 11)})
        self.assertEqual(sp.find(rows(one), 2095, 1).hands, {"left": (1, 11)})

    def test_knee_bands_are_not_hands(self):
        """Grey bands below the hips (a half-giant's knees and boots) are not wristbands."""
        knees = list(FIGURE)
        knees[13] = "......g..g......"
        p = sp.find(rows(knees), 2095, 0)
        self.assertEqual(set(p.hands.values()), {(1, 11), (14, 11)})

    def test_frames(self):
        self.assertEqual(len(sp.WALK_FACING), sp.WALK_FRAMES)
        self.assertEqual(len(sp.COMBAT_FACING), sp.COMBAT_FRAMES)
        self.assertEqual(sp.WALK_FACING[7:11], [sp.BACK] * 4)
        self.assertEqual(sp.COMBAT_FACING[sp.BOW_FRAMES[0]], sp.FRONT)
        self.assertEqual(sorted(sp.MODELS), sorted(sp.HEAD_ROWS))

    def test_dead(self):
        p = sp.find(rows(), 2095, sp.DEAD_FRAME, combat=True)
        self.assertIsNone(p.head)
        self.assertEqual(p.hands, {})

    def test_corrections(self):
        sp.CORRECTIONS[(2095, False, 0)] = {"waist": 7}
        try:
            self.assertEqual(sp.parts(rows(), 2095, 0).waist, 7)
        finally:
            del sp.CORRECTIONS[(2095, False, 0)]
        self.assertNotEqual(sp.parts(rows(), 2095, 0).waist, 7)


if __name__ == "__main__":
    unittest.main()
