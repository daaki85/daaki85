"""Weapons drawn in a party member's hands on their map sprite."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import spritegear as sg
from dscompanion import spriteparts as sp
import test_spriteparts
from test_spriteparts import rows

SWORD, CLUB, SHIELD, POLEARM, BOW = 63, 18, 4, 19, 1
METAL, WOOD, BONE = 4, 0, 1
PAD = 10


def drawn(before, after):
    """The pixels ARMED added: {(x, y): colour}."""
    old = sg.padded(before, PAD)
    return {(x, y): q for y, r in enumerate(after) for x, q in enumerate(r) if q != old[y][x]}


class WeaponTests(unittest.TestCase):
    def test_sword_in_the_right_hand(self):
        """Facing the viewer: from the hand on the left of the picture, down and outward, in metal."""
        before = rows()
        new = drawn(before, sg.armed(before, 2095, 0, False, {"right": (SWORD, METAL)}, PAD))
        hx, hy = sp.find(before, 2095, 0).hands["right"]
        self.assertTrue(new)
        self.assertTrue(set(new.values()) <= set(sg.MATERIAL_COLOURS[METAL]))
        self.assertTrue(all(y >= hy + PAD - 1 for _, y in new))  # (it hangs down: the guard across the hand)
        self.assertLess(min(x for x, _ in new), hx + PAD)  # (and out, to the left)

    def test_material(self):
        before = rows()
        new = drawn(before, sg.armed(before, 2095, 0, False, {"right": (CLUB, WOOD)}, PAD))
        self.assertTrue(set(new.values()) <= set(sg.MATERIAL_COLOURS[WOOD]))

    def test_two_handed_upright(self):
        """A polearm is carried upright: most of it above the hand."""
        before = rows()
        new = drawn(before, sg.armed(before, 2095, 0, False, {"right": (POLEARM, BONE)}, PAD))
        hy = sp.find(before, 2095, 0).hands["right"][1] + PAD
        self.assertGreater(sum(1 for _, y in new if y < hy), sum(1 for _, y in new if y > hy))

    def test_shield_on_the_other_arm(self):
        before = rows()
        new = drawn(before, sg.armed(before, 2095, 0, False, {"left": (SHIELD, 5)}, PAD))
        hx, _ = sp.find(before, 2095, 0).hands["left"]
        self.assertTrue(new)
        self.assertTrue(all(abs(x - (hx + PAD)) <= 4 for x, _ in new))  # (about 7 wide, on the forearm)
        self.assertGreaterEqual(len(new), 40)

    def test_nothing_in_the_bow_frames(self):
        """The game draws the bow there itself."""
        before = rows()
        for frame in sp.BOW_FRAMES:
            self.assertEqual(drawn(before, sg.armed(before, 2095, frame, True, {"right": (SWORD, METAL)}, PAD)), {})

    def test_missile_weapons_not_drawn_in_hand(self):
        before = rows()
        self.assertEqual(drawn(before, sg.armed(before, 2095, 0, False, {"right": (BOW, WOOD)}, PAD)), {})

    def test_behind_the_body(self):
        """A grip marked behind leaves the body's pixels alone."""
        before = rows()
        sg.MODEL_GRIPS[(2095, False, 0)] = {"right": (0, True)}  # (pointing right, across the body)
        try:
            new = drawn(before, sg.armed(before, 2095, 0, False, {"right": (SWORD, METAL)}, PAD))
        finally:
            del sg.MODEL_GRIPS[(2095, False, 0)]
        old = sg.padded(before, PAD)
        self.assertTrue(new)
        self.assertTrue(all(old[y][x] is None for x, y in new))

    def test_bow_and_quiver_on_the_back(self):
        """From behind, over the back; from the front, behind the body but for the strap across the
        chest; in the bow frames (the game's bow in the hands) only the quiver."""
        before = rows()
        old = sg.padded(before, PAD)
        carried = {"missile": (BOW, WOOD), "ammo": (62, WOOD)}
        back = drawn(before, sg.armed(before, 2095, 1, False, carried, PAD))
        self.assertTrue(set(sg.STAVE) & set(back.values()))
        self.assertTrue(any(old[y][x] is not None for x, y in back))  # (over the back)
        front = drawn(before, sg.armed(before, 2095, 0, False, carried, PAD))
        on_body = {p: c for p, c in front.items() if old[p[1]][p[0]] is not None}
        self.assertTrue(on_body)
        self.assertEqual(set(on_body.values()), {sg.QUIVER[0]})  # (only the strap)
        shooting = drawn(before, sg.armed(before, 2095, sp.BOW_FRAMES[1], True, carried, PAD))
        self.assertTrue(shooting)
        self.assertFalse(set(sg.STAVE[1:]) & set(shooting.values()) - set(sg.QUIVER))

    def test_armour_recolours_the_clothes(self):
        """Body armour draws nothing: the model's own clothing changes colour, the rest as it was.
        The chest piece: clothing above the waist; the black outline stays."""
        before = rows()
        new = drawn(before, sg.armed(before, 2095, 0, False, {}, PAD, armour=(88,)))
        p = sp.find(before, 2095, 0)
        old = sg.padded(before, PAD)
        self.assertTrue(new)
        self.assertTrue(set(new.values()) <= set(sg.METAL_SHADES))
        self.assertTrue(all(old[y][x] in sg.CLOTHES[2095] for x, y in new))  # (only clothing)
        self.assertTrue(all(y <= p.waist + PAD for _, y in new))
        for x, y in new:  # (black only inside the outline)
            self.assertTrue(all(old[y + dy][x + dx] is not None for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))))

    def test_each_piece_its_part(self):
        """Leg armour: the clothing below the waist only; arm armour: by the hands only."""
        before = rows()
        p = sp.find(before, 2095, 0)
        legs = drawn(before, sg.armed(before, 2095, 0, False, {}, PAD, armour=(26,)))
        self.assertTrue(legs)
        self.assertTrue(all(y > p.waist + PAD for _, y in legs))
        arms = drawn(before, sg.armed(before, 2095, 0, False, {}, PAD, armour=(25,)))
        for x, y in arms:
            self.assertTrue(any(abs(x - PAD - hx) <= 2 and hy - 4 <= y - PAD <= hy + 1 for hx, hy in p.hands.values()))

    def test_never_the_hair(self):
        """Dark strands in the hair, in the clothes' own colours, stay as they are."""
        strands = list(test_spriteparts.FIGURE)
        strands[1] = ".....hhkhhh....."
        strands[2] = ".....hkkssh....."
        before = rows(strands)
        new = drawn(before, sg.armed(before, 2095, 0, False, {}, PAD, armour=(88,)))
        self.assertNotIn((7 + PAD, 1 + PAD), new)
        self.assertNotIn((6 + PAD, 2 + PAD), new)

    def test_armour_keeps_a_models_own_cloak(self):
        cloak = [line.replace("k", "c") for line in test_spriteparts.FIGURE]
        colours = dict(test_spriteparts.COLOURS, c=55)
        before = [[colours[ch] for ch in line] for line in cloak]
        self.assertEqual(drawn(before, sg.armed(before, 2099, 0, False, {}, PAD, armour=(6,))), {})

    def test_tables(self):
        self.assertEqual(len(sg.WALK_GRIPS), sp.WALK_FRAMES)
        self.assertEqual(len(sg.COMBAT_POSES), sp.COMBAT_FRAMES)
        for frame in sp.BOW_FRAMES + (sp.DEAD_FRAME,):
            self.assertIsNone(sg.COMBAT_POSES[frame])
        stable = lambda c: c == 254 or 16 <= c <= 79 or 128 <= c <= 222  # (only colours no region changes)
        for colours in sg.MATERIAL_COLOURS.values():
            self.assertTrue(all(map(stable, colours)))
        for _, shades, _ in sg.ARMOUR.values():
            self.assertTrue(all(map(stable, shades)))
        self.assertEqual(sorted(sg.CLOTHES), sorted(m for m in sp.MODELS if m != sp.KREEN))


if __name__ == "__main__":
    unittest.main()
