"""Worn equipment drawn on a party member's map sprite: weapons in the hands (this module's start),
from where spriteparts finds the hands, with each frame's grip set by hand.

A weapon is drawn along a line from the hand at the frame's angle: its shape (a dagger's short
blade, a sword's long one, a club widening to its end, ...) in its material's colours. The colours
are muted ones from the parts of the palette no region changes (30-79 and 128-222), so the gear
sits in the picture the way the game's own colours do.
"""

import math
from typing import Dict, List, Optional, Tuple

from . import spriteparts as sp

Rows = sp.Rows

# Materials (the item type's +8h, low nibble, as game.MATERIALS): (outline, body, light)
MATERIAL_COLOURS = {
    0: (207, 205, 206),  # wood: dark faded brown
    1: (194, 214, 215),  # bone: weathered grey
    2: (210, 212, 213),  # stone: grey
    3: (254, 18, 23),  # obsidian: near-black, a blue-grey sheen
    4: (22, 25, 27),  # metal: dull blue-grey iron
    5: (207, 205, 194),  # leather
}
FLAME = (248, 241, 242)  # the Flame Blade: the fire colours the game cycles

# Shapes, by item type (the game's item type numbers)
DAGGER, SWORD, CLUB, MACE, AXE, GREAT_AXE, POLEARM, GYTHKA, CAHULAKS, STAFF, SHIELD, SLING, BOW, \
    CHATKCHA = ("dagger", "sword", "club", "mace", "axe", "great axe", "polearm", "gythka", "cahulaks",
                "staff", "shield", "sling", "bow", "chatkcha")
WEAPON_SHAPES: Dict[int, str] = {
    17: DAGGER, 33: DAGGER, 84: DAGGER, 94: DAGGER, 97: DAGGER,
    45: SWORD, 63: SWORD, 81: SWORD, 85: SWORD, 98: SWORD, 41: SWORD, 50: SWORD, 29: SWORD,
    18: CLUB, 28: CLUB,
    20: MACE, 46: MACE, 30: MACE,
    22: AXE, 2: GREAT_AXE,
    19: POLEARM, 111: POLEARM, 112: POLEARM,
    44: GYTHKA, 21: CAHULAKS,
    3: STAFF, 80: STAFF,
    4: SHIELD, 16: SHIELD, 34: SHIELD, 83: SHIELD,
    0: SLING, 64: SLING, 1: BOW, 69: BOW, 48: CHATKCHA,
}
FLAME_BLADE = 29
TWO_HANDED = frozenset((GREAT_AXE, POLEARM, GYTHKA, STAFF, BOW))

# Each pose's grip, by hand: the angle the weapon points (degrees, 0 to the right of the picture,
# 90 straight down) and whether it is behind the body. Set by hand from the walking and combat
# frames (the same poses for every model); MODEL_GRIPS changes one for one model.
Grip = Tuple[float, bool]
WALK_GRIPS: List[Dict[str, Grip]] = [
    {"right": (112, False), "left": (68, False)},  # 0 front, standing: hanging down and outward
    {"right": (72, False), "left": (108, False)},  # 1 back
    {"right": (58, False), "left": (122, True)},  # 2 side: the near hand forward and down
] + [{"right": (112, False), "left": (68, False)}] * 4 \
  + [{"right": (72, False), "left": (108, False)}] * 4 \
  + [{"right": (58, False), "left": (122, True)}] * 4
# Two-handed weapons (staffs, polearms, the gythka, the great axe) are carried upright in the right
# hand, the butt by the feet: their angle, by facing, in place of the hand's own
UPRIGHT: Dict[Optional[str], Grip] = {sp.FRONT: (262, False), sp.BACK: (278, False), sp.SIDE: (285, False)}
# The combat poses (the same for every model): which hand swings (the highest, lowest, leftmost or
# rightmost of the hands found) and at what angle, then the other hand's angle (a shield or a
# second weapon). Three frames each way: the wind-up, the strike, the follow-through; then the
# hit (12). Set by hand from the frames.
CombatGrip = Tuple[str, float, float]
COMBAT_POSES: List[Optional[CombatGrip]] = [
    ("highest", 285, 100),  # 0 toward the viewer: raised over the head
    ("highest", 200, 80),  # 1 the swing across
    ("highest", 215, 90),  # 2 followed through, low and out
    ("highest", 275, 100),  # 3 away: raised
    ("highest", 320, 100),  # 4 the swing
    ("lowest", 120, 80),  # 5 followed through
    ("highest", 250, 110),  # 6 to the side: raised behind
    ("rightmost", 10, 120),  # 7 thrust forward
    ("rightmost", 55, 120),  # 8 followed through, down and forward
    None, None, None,  # 9-11 the bow
    ("lowest", 100, 80),  # 12 hit
    None,  # 13 dead
]
COMBAT_GRIPS: List[Optional[Dict[str, Grip]]] = [None] * sp.COMBAT_FRAMES  # (by hand, per model, where needed)
MODEL_GRIPS: Dict[Tuple[int, bool, int], Dict[str, Grip]] = {}


# Weapons in proportion to the body: a half-giant's bigger, a dwarf's and a halfling's smaller
MODEL_SCALE = {2072: 1.35, 2074: 1.35, 2068: 0.85, 2070: 0.85}


def grip(model: int, frame: int, combat: bool, hand: str) -> Optional[Grip]:
    own = MODEL_GRIPS.get((model, combat, frame), {})
    if hand in own:
        return own[hand]
    table = COMBAT_GRIPS if combat else WALK_GRIPS
    poses = table[frame] if 0 <= frame < len(table) else None
    return poses.get(hand) if poses else None


def padded(rows: Rows, pad: int) -> Rows:
    """ROWS with PAD clear pixels on the left, right and top (room for what is drawn)."""
    width = len(rows[0]) if rows else 0
    return [[None] * (width + 2 * pad) for _ in range(pad)] + [[None] * pad + list(r) + [None] * pad for r in rows]


def _put(rows: Rows, x: float, y: float, colour: int, behind: bool, body: Rows) -> None:
    x, y = int(round(x)), int(round(y))
    if 0 <= y < len(rows) and 0 <= x < len(rows[y]):
        if behind and body[y][x] is not None:
            return  # (the body is in front)
        rows[y][x] = colour


# Each shape along its line: (from, to) steps from the hand, and the half-width at each step, with
# which colour, as a list of (step, offsets across, colour index: 0 outline, 1 body, 2 light)
def _shape(shape: str) -> List[Tuple[int, List[Tuple[int, int]]]]:
    if shape == DAGGER:
        return [(0, [(-1, 0), (0, 0), (1, 0)])] + [(s, [(0, 2), (1, 0)]) for s in range(1, 4)] + [(4, [(0, 1)])]
    if shape == SWORD:
        return [(0, [(-1, 0), (0, 0), (1, 0), (2, 0)])] + [(s, [(0, 2), (1, 1)]) for s in range(1, 7)] \
            + [(7, [(0, 1), (1, 0)]), (8, [(0, 0)])]
    if shape == CLUB:
        return [(s, [(0, 1), (1, 0)]) for s in range(-1, 3)] + [(s, [(-1, 0), (0, 2), (1, 1), (2, 0)]) for s in range(3, 6)] \
            + [(6, [(0, 0), (1, 0)])]
    if shape == MACE:
        return [(s, [(0, 1)]) for s in range(-1, 4)] + [(4, [(-1, 0), (0, 1), (1, 0)]), (5, [(-1, 1), (0, 2), (1, 1)]),
                                                        (6, [(-1, 0), (0, 1), (1, 0)])]
    if shape == AXE:
        return [(s, [(0, 1)]) for s in range(-1, 6)] + [(4, [(1, 0), (2, 0)]), (5, [(1, 2), (2, 1), (3, 0)]),
                                                        (6, [(0, 0), (1, 1), (2, 0)])]
    if shape == GREAT_AXE:
        return [(s, [(0, 1)]) for s in range(-4, 8)] + [(5, [(1, 0), (2, 0), (-1, 0)]), (6, [(1, 2), (2, 1), (3, 0), (-1, 2), (-2, 0)]),
                                                        (7, [(1, 1), (2, 0), (-1, 1), (-2, 0)])]
    if shape == POLEARM:
        return [(s, [(0, 1)]) for s in range(-5, 9)] + [(9, [(0, 2), (1, 0)]), (10, [(0, 2), (1, 0)]), (11, [(0, 0)])]
    if shape == GYTHKA:
        return [(s, [(0, 1)]) for s in range(-5, 6)] + [(6, [(0, 2), (1, 0)]), (7, [(0, 0)]),
                                                        (-6, [(0, 2), (-1, 0)]), (-7, [(0, 0)])]
    if shape == CAHULAKS:
        return [(0, [(0, 1)]), (1, [(0, 2), (1, 0)]), (2, [(0, 2), (1, 0)]), (3, [(0, 0)])]
    if shape == STAFF:
        return [(s, [(0, 1)]) for s in range(-6, 9)] + [(9, [(0, 0)]), (-7, [(0, 0)])]
    return []


def draw_weapon(rows: Rows, body: Rows, hand: sp.Point, angle: float, shape: str, colours: Tuple[int, int, int],
                behind: bool, scale: float = 1.0) -> None:
    """SHAPE drawn on ROWS (BODY: the picture without it, for what is in front) from HAND, pointing
    at ANGLE, SCALE times its length."""
    dx, dy = math.cos(math.radians(angle)) * scale, math.sin(math.radians(angle)) * scale
    across = (-dy, dx)
    hx, hy = hand
    across = (across[0] / scale, across[1] / scale)  # (only the length scales)
    steps = sorted(_shape(shape), key=lambda c: c[0])
    for step, cells in steps:
        for offset, colour in cells:
            for sub in ((0.0, 0.5) if scale > 1 else (0.0,)):  # (no gaps in a longer one)
                x = hx + dx * (step + sub) + across[0] * offset
                y = hy + dy * (step + sub) + across[1] * offset
                _put(rows, x, y, colours[colour], behind, body)


def draw_shield(rows: Rows, body: Rows, hand: sp.Point, facing: Optional[str], colours: Tuple[int, int, int],
                behind: bool) -> None:
    """A round shield on the arm: face on from the front, its back from behind, edge on from the side."""
    hx, hy = hand
    if facing == sp.SIDE:
        cells = [(0, dy, 0) for dy in range(-4, 2)] + [(1, dy, 1) for dy in range(-3, 1)]
    else:
        cells = []
        for dy in range(-4, 2):
            half = (1, 2, 2, 2, 2, 1)[dy + 4]
            for dx in range(-half, half + 1):
                edge = abs(dx) == half or dy in (-4, 1)
                cells.append((dx, dy, 0 if edge else (2 if (dx, dy) == (0, -1) and facing == sp.FRONT else 1)))
    for dx, dy, colour in cells:
        _put(rows, hx + dx, hy + dy, colours[colour], behind, body)


def armed(rows: Rows, model: int, frame: int, combat: bool, weapons: Dict[str, Tuple[int, int]],
          pad: int = 10) -> Rows:
    """One frame of MODEL with WEAPONS ({hand: (item type, material)}) drawn in its hands, padded
    by PAD. Nothing in the bow frames (the game draws the bow)."""
    out = padded(rows, pad)
    if combat and frame in sp.BOW_FRAMES:
        return out
    body = [list(r) for r in out]
    parts = sp.parts(rows, model, frame, combat)
    hands = dict(parts.hands)
    pose = COMBAT_POSES[frame] if combat and 0 <= frame < len(COMBAT_POSES) else None
    if pose and hands:  # (in a fight, the swinging hand is the pose's, not by side)
        pick, swing, other = pose
        points = list(hands.values())
        key = {"highest": lambda p: p[1], "lowest": lambda p: -p[1], "leftmost": lambda p: p[0],
               "rightmost": lambda p: -p[0]}[pick]
        points.sort(key=key)
        hands = {"right": points[0]}
        if len(points) > 1:
            hands["left"] = points[1]
    for hand in ("left", "right"):  # (the right drawn last, over the left)
        if hand not in weapons or hand not in hands:
            continue
        item_type, material = weapons[hand]
        shape = WEAPON_SHAPES.get(item_type)
        g = grip(model, frame, combat, hand)
        if g is None and pose:
            g = (pose[1] if hand == "right" else pose[2], False)
        if shape is None or g is None or shape in (SLING, BOW, CHATKCHA):
            continue
        colours = FLAME if item_type == FLAME_BLADE else MATERIAL_COLOURS.get(material, MATERIAL_COLOURS[4])
        hx, hy = hands[hand]
        if shape in TWO_HANDED and not combat and hand == "right":
            g = UPRIGHT.get(parts.facing, g)
        if shape == SHIELD:
            draw_shield(out, body, (hx + pad, hy + pad), parts.facing, colours, g[1])
        else:
            draw_weapon(out, body, (hx + pad, hy + pad), g[0], shape, colours, g[1], MODEL_SCALE.get(model, 1.0))
    return out
