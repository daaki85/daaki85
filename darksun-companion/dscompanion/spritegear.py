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
    3: (24, 18, 26),  # obsidian: near-black, its edges a lighter grey (to show on dark clothes)
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
                behind: bool, scale: float = 1.0) -> None:
    """A round shield on the forearm (about 7 by 9 pixels on a human): its face, rim and boss from
    the front, its strapped back from behind, edge on from the side."""
    outline, fill, light = colours
    hx, hy = hand
    rx, ry = 3.4 * scale, 4.4 * scale
    cx, cy = hx, hy - 2 * scale  # (on the forearm, above the hand)
    if facing == sp.SIDE:
        rx = 1.2 * scale
    for dy in range(-int(ry) - 1, int(ry) + 2):
        for dx in range(-int(rx) - 1, int(rx) + 2):
            d = (dx / rx) ** 2 + (dy / ry) ** 2
            if d > 1.0:
                continue
            edge = d > 0.6 if facing != sp.SIDE else abs(dx) >= rx - 0.6
            if edge:
                c = outline
            elif facing == sp.FRONT and abs(dx) <= 0 and abs(dy) <= 0:
                c = light  # the boss
            elif facing == sp.FRONT and dx < 0 and dy < 0 and d < 0.35:
                c = light  # light on the upper left, as the game's pictures have it
            elif facing == sp.BACK and dy in (-1, 1):
                c = outline  # the straps on its back
            else:
                c = fill
            _put(rows, cx + dx, cy + dy, c, behind, body)


# On the back: the bow's stave and string, the quiver's leather and the arrows' fletching
STAVE, STRING = (207, 205), 213
QUIVER, FLETCHING = (207, 205, 194), (215, 196)


def _line(a: Tuple[float, float], b: Tuple[float, float]) -> List[Tuple[float, float]]:
    n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1]))) + 1
    return [(a[0] + (b[0] - a[0]) * i / max(1, n - 1), a[1] + (b[1] - a[1]) * i / max(1, n - 1)) for i in range(n)]


def draw_back_gear(rows: Rows, body: Rows, parts: sp.Parts, pad: int, bow: bool, quiver: bool,
                   at_hip: Optional[Tuple[int, int]] = None) -> None:
    """A bow and a quiver on the back (across it from behind; their tops past the shoulders and a
    strap across the chest from the front; hanging behind the back from the side), and a sling or
    chatkcha at the hip (AT_HIP: its colours)."""
    if not parts.shoulders or parts.waist is None:
        return
    sy, sa, sb = parts.shoulders
    sy, sa, sb, waist = sy + pad, sa + pad, sb + pad, parts.waist + pad
    behind = parts.facing != sp.BACK
    if parts.facing == sp.SIDE:  # (facing right: the back is on the left)
        bow_line = _line((sa + 1, sy - 4), (sa - 1, waist + 4))
        quiver_at = (sa, sy - 3)
    else:
        bow_line = _line((sb - 1, sy - 4), (sa + 1, waist + 4)) if parts.facing == sp.BACK else             _line((sa + 1, sy - 4), (sb - 1, waist + 4))
        quiver_at = (sa + 2, sy - 3) if parts.facing == sp.BACK else (sb - 2, sy - 3)
    if bow:
        n = len(bow_line)
        for i, (x, y) in enumerate(bow_line):  # the stave bowed out, the string straight
            bulge = math.sin(math.pi * i / max(1, n - 1)) * 1.5
            _put(rows, x - bulge, y - bulge * 0.5, STAVE[i % 2], behind, body)
            _put(rows, x + 1, y, STRING, behind, body)
    if quiver:
        qx, qy = quiver_at
        for dy in range(0, 8):
            _put(rows, qx, qy + dy, QUIVER[0], behind, body)
            _put(rows, qx + 1, qy + dy, QUIVER[1 if dy % 3 else 2], behind, body)
        for dx in (0, 1):  # the fletching standing out of it
            _put(rows, qx + dx, qy - 1, FLETCHING[dx], behind, body)
            _put(rows, qx + dx, qy - 2, FLETCHING[0], behind, body)
    if (bow or quiver) and parts.facing == sp.FRONT:  # the strap across the chest
        for x, y in _line((sb - 1, sy), (sa + 1, waist)):
            _put(rows, x, y, QUIVER[0], False, body)
    if at_hip:
        side = sa if parts.facing != sp.BACK else sb
        for dx, dy, c in ((0, 0, 0), (0, 1, 1), (0, 2, 1), (-1, 2, 0), (1, 2, 0), (0, 3, 0)):
            _put(rows, side + dx, waist + dy, at_hip[c], False, body)
    # long hair falls over what is on the back
    for x, y in parts.hair:
        if 0 <= y + pad < len(rows) and 0 <= x + pad < len(rows[y + pad]):
            rows[y + pad][x + pad] = body[y + pad][x + pad]


def armed(rows: Rows, model: int, frame: int, combat: bool, weapons: Dict[str, Tuple[int, int]],
          pad: int = 10, armour: Tuple[int, ...] = ()) -> Rows:
    """One frame of MODEL with WEAPONS ({"right"/"left": (item type, material)} drawn in the hands;
    "missile": the bow, sling or chatkcha carried, "ammo": arrows, on the back or at the hip),
    padded by PAD, in ARMOUR (item types: under all the rest). Nothing in the hands in the bow
    frames (the game draws the bow)."""
    out = padded(rows, pad)
    parts = sp.parts(rows, model, frame, combat)
    if parts.facing is not None:
        for item_type in armour:
            if item_type in ARMOUR:
                draw_armour(out, model, parts, item_type, pad)
    body = [list(r) for r in out]
    missile = weapons.get("missile")
    if missile or "ammo" in weapons:  # (the bow, quiver, sling or chatkcha carried)
        shape = WEAPON_SHAPES.get(missile[0]) if missile else None
        bow = shape == BOW and not (combat and frame in sp.BOW_FRAMES)
        hip = MATERIAL_COLOURS.get(missile[1], MATERIAL_COLOURS[5]) if shape in (SLING, CHATKCHA) else None
        draw_back_gear(out, body, parts, pad, bow, "ammo" in weapons or shape == BOW, hip)
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
    if combat and frame in sp.BOW_FRAMES:
        return out  # (the game draws the bow in the hands)
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
            draw_shield(out, body, (hx + pad, hy + pad), parts.facing, colours, g[1], MODEL_SCALE.get(model, 1.0))
        else:
            draw_weapon(out, body, (hx + pad, hy + pad), g[0], shape, colours, g[1], MODEL_SCALE.get(model, 1.0))
    return out


# Body armour: the chest, arms and legs of the picture recoloured by brightness into the material's
# shades (the picture's own shading becoming the armour's), with the armour's pattern over them.
ARMOUR_CHEST, ARMOUR_ARMS, ARMOUR_LEGS = "chest", "arms", "legs"
PLAIN, RINGS, STUDS, SCALES, CHAIN, PLATE = "plain", "rings", "studs", "scales", "chain", "plate"
# shades, dark to light (muted, from the colours no region changes)
LEATHER_SHADES = (204, 207, 205, 206, 60)
BONE_SHADES = (207, 194, 206, 213, 214, 215)
METAL_SHADES = (18, 22, 23, 25, 27, 28)  # plate: blue-grey iron
CHAIN_SHADES = (209, 210, 211, 212, 213, 214)  # mail: plain grey
SILK_SHADES = (194, 206, 213, 214, 215, 216)
DRAKE_SHADES = (210, 53, 54, 55, 56)
SHIMMER_SHADES = (22, 24, 26, 28, 30, 31)
# item type: (which piece, shades, pattern)
ARMOUR: Dict[int, Tuple[str, Tuple[int, ...], str]] = {
    6: (ARMOUR_CHEST, LEATHER_SHADES, PLAIN), 7: (ARMOUR_ARMS, LEATHER_SHADES, PLAIN), 8: (ARMOUR_LEGS, LEATHER_SHADES, PLAIN),
    9: (ARMOUR_CHEST, BONE_SHADES, RINGS), 10: (ARMOUR_ARMS, BONE_SHADES, RINGS), 11: (ARMOUR_LEGS, BONE_SHADES, RINGS),
    12: (ARMOUR_CHEST, BONE_SHADES, STUDS), 13: (ARMOUR_ARMS, BONE_SHADES, STUDS), 14: (ARMOUR_LEGS, BONE_SHADES, STUDS),
    15: (ARMOUR_CHEST, BONE_SHADES, SCALES), 55: (ARMOUR_ARMS, BONE_SHADES, SCALES), 56: (ARMOUR_LEGS, BONE_SHADES, SCALES),
    57: (ARMOUR_CHEST, CHAIN_SHADES, CHAIN), 58: (ARMOUR_ARMS, CHAIN_SHADES, CHAIN), 59: (ARMOUR_LEGS, CHAIN_SHADES, CHAIN),
    54: (ARMOUR_ARMS, METAL_SHADES, SCALES), 24: (ARMOUR_LEGS, METAL_SHADES, SCALES),  # Grey's Scale
    88: (ARMOUR_CHEST, METAL_SHADES, PLATE), 25: (ARMOUR_ARMS, METAL_SHADES, PLATE), 26: (ARMOUR_LEGS, METAL_SHADES, PLATE),
    79: (ARMOUR_CHEST, DRAKE_SHADES, SCALES), 82: (ARMOUR_CHEST, SHIMMER_SHADES, PLAIN), 90: (ARMOUR_CHEST, SILK_SHADES, PLAIN),
}
# Colours each model keeps under armour: its own cloak (the elf woman's), boots
KEEP: Dict[int, frozenset] = {2099: frozenset((53, 54, 55, 56, 188, 189, 190, 191, 69, 70, 158, 159, 160))}

_PALETTE_LIGHT: Dict[int, float] = {}


def set_palette(colours: List[Tuple[int, int, int]]) -> None:
    """The palette's colours (art.palette_colours), for the brightness of each pixel."""
    _PALETTE_LIGHT.clear()
    for i, (r, g, b) in enumerate(colours):
        _PALETTE_LIGHT[i] = (0.3 * r + 0.59 * g + 0.11 * b) / 255


def _torso_run(rows: Rows, y: int, middle: float, sa: int, sb: int) -> Optional[Tuple[int, int]]:
    """The run of the picture's row Y through the body's middle, inside the shoulders."""
    x = int(round(middle))
    if not (0 <= y < len(rows)) or not (0 <= x < len(rows[y])) or rows[y][x] is None:
        near = [i for i in range(sa, sb + 1) if 0 <= i < len(rows[y]) and rows[y][i] is not None] if 0 <= y < len(rows) else []
        if not near:
            return None
        x = min(near, key=lambda i: abs(i - middle))
    a = b = x
    while a - 1 >= max(0, sa) and rows[y][a - 1] is not None:
        a -= 1
    while b + 1 <= min(len(rows[y]) - 1, sb) and rows[y][b + 1] is not None:
        b += 1
    return a, b


def armour_cells(rows: Rows, parts: sp.Parts, piece: str) -> List[sp.Point]:
    """The picture's pixels a PIECE of armour covers, as Athas's armour is worn, in pieces with the
    skin between: the chest (a cuirass: the body's middle, shoulders to waist), the arms (a guard
    on the shoulder and a bracer on the forearm, the elbow bare; not the hands) or the legs (thigh
    pieces and greaves, the knee bare). Not the hair."""
    if not parts.shoulders or parts.waist is None or not parts.head:
        return []
    sy, sa, sb = parts.shoulders
    middle = (parts.head.left + parts.head.right) / 2 if parts.facing != sp.SIDE else (sa + sb) / 2
    feet_top = min((y for y, _, _ in parts.feet), default=parts.bottom) - 2
    knee = parts.waist + (feet_top - parts.waist) // 2
    # the torso: the run through the body's middle, no wider than a third of the shoulders each way
    # (where the upper arms touch the body, they are not the chest)
    reach = max(2, round((sb - sa) * (0.4 if parts.facing == sp.SIDE else 0.33)))
    torso = {}
    for y in range(sy, parts.waist + 1):
        run = _torso_run(rows, y, middle, sa, sb)
        if run:
            torso[y] = (max(run[0], int(middle) - reach), min(run[1], int(middle + 0.5) + reach))
    hands = list(parts.hands.values())
    cells: List[sp.Point] = []
    for y, row in enumerate(rows):
        for x, p in enumerate(row):
            if p is None or (x, y) in parts.hair:
                continue
            run = torso.get(y)
            in_torso = run is not None and run[0] <= x <= run[1]
            if piece == ARMOUR_CHEST:
                if sy <= y <= parts.waist and in_torso:
                    cells.append((x, y))
            elif piece == ARMOUR_ARMS:
                if in_torso or y < sy:
                    continue
                if any(abs(x - hx) <= 1 and abs(y - hy) <= 1 for hx, hy in hands):
                    continue  # (the hand itself)
                bracer = any(abs(x - hx) <= 2 and hy - 3 <= y <= hy - 2 for hx, hy in hands)
                guard = y <= sy + 1
                if bracer or guard:
                    cells.append((x, y))
            elif piece == ARMOUR_LEGS:
                if not (parts.waist < y <= feet_top) or abs(y - knee) <= 0:
                    continue  # (the knee)
                if any(abs(x - hx) <= 2 and hy - 4 <= y <= hy + 1 for hx, hy in hands):
                    continue  # (a hand hanging by the thigh)
                cells.append((x, y))
    return cells


def _pattern(pattern: str, x: int, y: int, shade: int, top: int) -> int:
    """The shade (0 the darkest) with the armour's pattern on it."""
    if pattern == RINGS and y % 2 == 0 and (x + y // 2) % 2 == 0:
        return max(0, shade - 2)  # (the rings' holes)
    if pattern == CHAIN and (x + y) % 2 == 0:
        return max(0, shade - 1)
    if pattern == SCALES and y % 2 == 1 and (x + (y // 2) % 2) % 2 == 0:
        return max(0, shade - 2)  # (the scales' lower edges, offset row to row)
    if pattern == STUDS and y % 3 == 1 and x % 3 == 1:
        return top  # (a stud)
    if pattern == PLATE and y % 4 == 0:
        return max(0, shade - 1)  # (the plates' edges)
    return shade


def draw_armour(rows: Rows, model: int, parts: sp.Parts, item_type: int, pad: int) -> None:
    """One piece of armour recoloured over the (padded) picture ROWS."""
    piece, shades, pattern = ARMOUR[item_type]
    keep = KEEP.get(model, frozenset())
    unpadded = [r[pad:-pad] if pad else r for r in rows[pad:]]
    top = len(shades) - 1
    cells = [(x, y) for x, y in armour_cells(unpadded, parts, piece) if unpadded[y][x] not in keep]
    lights = [_PALETTE_LIGHT.get(unpadded[y][x], 0.5) for x, y in cells]
    low, high = (min(lights), max(lights)) if lights else (0.0, 1.0)
    for x, y in cells:
        p = unpadded[y][x]
        light = (_PALETTE_LIGHT.get(p, 0.5) - low) / max(0.05, high - low)  # (the piece's own range)
        edge = any(not (0 <= y + dy < len(unpadded) and 0 <= x + dx < len(unpadded[y + dy]))
                   or unpadded[y + dy][x + dx] is None for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        shade = 0 if edge else min(top, max(1, int(light * top + 0.5)))
        rows[y + pad][x + pad] = shades[_pattern(pattern, x, y, shade, top) if not edge else 0]
