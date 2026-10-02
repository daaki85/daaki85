"""Worn equipment shown on a party member's map sprite, from where spriteparts finds the parts of
each frame (set by hand where finding them goes wrong). The artist's pixels are kept wherever they
can be: what is worn on the body recolours the character's own picture, what is carried is drawn
on it.

  * Weapons and shields in the hands (each walking and fighting pose's grip set by hand), a bow and
    quiver on the back, a sling or chatkcha at the hip: drawn, in their material's colours.
  * Body armour (chest, arms, legs), boots and belts: the character's own clothing, feet or waist
    recoloured toward the material, shade for shade.
  * Helms: a circlet at the brow, blended into the hair under it.
  * Cloaks: the human and half-elf woman's own cloak, frame by frame, fitted to the wearer.

The colours are muted ones from the parts of the palette no region changes (30-79 and 128-222), so
the gear sits in the picture the way the game's own colours do. A thri-kreen shows only weapons and
shields (all it can use). armed() makes one frame.
"""

import math
from typing import Dict, List, Optional, Tuple

from . import game, spriteparts as sp

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


# Weapons in proportion to the body: a half-giant's bigger, a halfling's and a dwarf's smaller
MODEL_SCALE = {2072: 1.35, 2074: 1.35, 2068: 0.85, 2070: 0.85, 2053: 0.9, 2055: 0.9}


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


# Helms, worn as circlets and headdresses (the hair and face showing): a band round the head at
# the brow, in the helm's material's faded colours, and its ornament. Item type: style.
FEATHER, STONE, SPIKES = "feather", "stone", "spikes"
HELMS: Dict[int, str] = {5: FEATHER, 109: FEATHER, 89: STONE, game.BONE_HELM_TYPE: SPIKES}
HELM_COLOURS = {  # dark to light, close in tone (the hair's own shading showing through them)
    FEATHER: (204, 207, 205, 194),  # faded leather
    STONE: (210, 211, 212, 24),  # dull iron
    SPIKES: (207, 194, 206, 213),  # weathered bone
}
FEATHER_GREYS, STONE_RED = (210, 212, 211), 195

_LIGHT: Dict[int, float] = {}


def set_palette(colours: List[Tuple[int, int, int]]) -> None:
    """The palette (art.palette_colours): each colour's brightness, for blending a helm into the
    hair under it."""
    _LIGHT.clear()
    _LIGHT.update({i: (0.3 * r + 0.59 * g + 0.11 * b) / 255 for i, (r, g, b) in enumerate(colours)})


# The circlet's half-width round each model's head (the head's own, not its hair's), by hand
CIRCLET_HALF = {2072: 4, 2074: 4}  # (3 for the rest)


def draw_helm(rows: Rows, parts: sp.Parts, item_type: int, pad: int, model: int = 0) -> None:
    """A circlet on the (padded) picture ROWS: a band round the head at the brow, as wide as the
    head itself, its ends curving round the temples (from the side, toward the back of the head),
    blended into what is under it: each pixel the helm's shade as light as the hair or skin it
    covers, no outline; and the helm's ornament: a short feather, a small stone at the front, or
    low spikes of bone over the hair."""
    style = HELMS.get(item_type)
    if style is None or not parts.head:
        return
    shades = HELM_COLOURS[style]
    h = parts.head
    half = CIRCLET_HALF.get(model, 3)
    y = h.brow + pad
    if parts.facing == sp.SIDE:  # (facing right: the forehead at the head's right)
        front = h.right + pad - 1
        a, b = front - 2 * half, front
    else:
        middle = (h.left + h.right) // 2 + pad
        a, b = middle - half, middle + half

    def blend(x, yy, lift=0.0):
        under = rows[yy][x]
        light = _LIGHT.get(under, 0.5) if under is not None else 0.5
        i = min(len(shades) - 1, max(0, int((light * 1.8 + lift) * (len(shades) - 1) + 0.5)))
        rows[yy][x] = shades[i]
    cells = []
    for x in range(a, b + 1):
        if parts.facing == sp.SIDE:
            dy = 1 if x < a + (b - a) // 3 else 0
        else:
            dy = 1 if x in (a, b) else 0
        if 0 <= y + dy < len(rows) and 0 <= x < len(rows[y + dy]) and rows[y + dy][x] is not None:
            cells.append((x, y + dy))
    if not cells:
        return
    for x, yy in cells:
        blend(x, yy, 0.1)
    xs = [x for x, _ in cells]
    first, last = min(xs), max(xs)
    centre = (first + last) // 2 if parts.facing != sp.SIDE else last - 1
    if style == SPIKES:
        for x in ([first + 1, centre, last - 1] if parts.facing != sp.SIDE else [centre - 2, centre]):
            tall = 2 if x == centre else 1
            for k in range(1, tall + 1):
                if rows[y - k][x] is None:
                    rows[y - k][x] = shades[1 if k == tall else 2]
                else:
                    blend(x, y - k, 0.15)
    elif style == STONE and parts.facing in (sp.FRONT, sp.SIDE):
        rows[y][centre] = STONE_RED
    elif style == FEATHER:
        x = centre - (2 if parts.facing == sp.SIDE else 0)
        for k, yy in enumerate(range(y - 1, y - 4, -1)):
            if rows[yy][x] is None:
                rows[yy][x] = FEATHER_GREYS[k % 2]
            else:
                blend(x, yy, 0.2)


# Cloaks: the human and half-elf woman's own cloak (the artist's, frame by frame: its folds and
# its swing as she walks and fights) fitted to the wearer's shoulders and height, in the cloak's
# colours: over the back from behind (the hair over it), behind the body from the front and side.
CLOAK_MODEL = 2099
CLOAK_GREENS = frozenset((53, 54, 55, 56, 188, 189, 190, 191, 69, 70))
CLOAK_COLOURS = {  # item type: shades, dark to light (None: her own green)
    65: (204, 207, 205, 194, 206, 60),  # Cloak, Koeatl's Cloak: faded dun
    game.CLOAK_TYPE: (17, 18, 20, 22, 24, 26),  # Cloak of Protection +1: dusk blue-grey
    38: None,  # Living Cloak
}


def _cloak_shade(p: int) -> float:
    return _LIGHT.get(p, 0.5)


def cloak_template(rows: Rows, model: int, frame: int, combat: bool) -> Optional[Tuple[sp.Parts, Dict[sp.Point, int]]]:
    """Her cloak in one of her frames: (her parts, {pixel: colour}), its dark fold lines with it."""
    parts = sp.parts(rows, CLOAK_MODEL, frame, combat)
    cloak = {}
    for y, row in enumerate(rows):
        for x, p in enumerate(row):
            if p in CLOAK_GREENS:
                cloak[(x, y)] = p
            elif p == 254:  # (a fold line or its edge: black between greens)
                near = sum(0 <= y + dy < len(rows) and 0 <= x + dx < len(rows[y + dy]) and rows[y + dy][x + dx] in CLOAK_GREENS
                           for dx in (-1, 0, 1) for dy in (-1, 0, 1))
                if near >= 3:
                    cloak[(x, y)] = p
    return (parts, cloak) if cloak and parts.shoulders and parts.head else None


def draw_cloak(rows: Rows, body: Rows, model: int, parts: sp.Parts, item_type: int, pad: int,
               template: Tuple[sp.Parts, Dict[sp.Point, int]]) -> None:
    """The cloak of TEMPLATE (cloak_template, the same frame of hers) on the (padded) picture ROWS."""
    her, cloak = template
    shades = CLOAK_COLOURS.get(item_type, CLOAK_COLOURS[65])
    if not parts.shoulders or not parts.head or parts.waist is None:
        return
    # where her shoulders' middle is, and her body's size, to the wearer's
    hm = (her.head.left + her.head.right) / 2
    wm = (parts.head.left + parts.head.right) / 2
    her_h = max(1, her.bottom - her.shoulders[0])
    own_h = max(1, parts.bottom - parts.shoulders[0])
    sy_ = own_h / her_h
    her_w = max(1, her.shoulders[2] - her.shoulders[1])
    own_w = max(1, parts.shoulders[2] - parts.shoulders[1])
    sx_ = max(0.7, min(1.6, own_w / her_w))
    ramp = sorted(CLOAK_GREENS | {254}, key=_cloak_shade)
    keep = set(parts.hair)
    if parts.head:
        keep |= {(x, y) for y in range(parts.head.top, parts.shoulders[0]) for x in range(parts.head.left, parts.head.right + 1)}
    hands = list(parts.hands.values())
    if parts.facing == sp.SIDE:  # (facing right: the cloak hangs from the back, at the left)
        hm, wm = her.shoulders[1], parts.shoulders[1]
    # each pixel of the wearer's picture takes her cloak's pixel at the same place (no gaps when
    # it is fitted to a bigger body)
    xs = [x for x, _ in cloak]
    ys = [y for _, y in cloak]
    x0 = int(wm + (min(xs) - hm) * sx_) - 1
    x1 = int(wm + (max(xs) - hm) * sx_) + 2
    y0 = int(parts.shoulders[0] + (min(ys) - her.shoulders[0]) * sy_) - 1
    y1 = int(parts.shoulders[0] + (max(ys) - her.shoulders[0]) * sy_) + 2
    placed: Dict[sp.Point, int] = {}
    for y in range(y0, y1):
        for x in range(x0, x1):
            src = (int(round(hm + (x - wm) / sx_)), int(round(her.shoulders[0] + (y - parts.shoulders[0]) / sy_)))
            if src in cloak:
                placed[(x, y)] = cloak[src]
    # no wider than the wearer (a pixel or two each side), and only what hangs from the body (no
    # scraps where her cloak billows past an arm)
    filled = [(x - pad, y - pad) for y, row in enumerate(body) for x, q in enumerate(row) if q is not None]
    if filled:
        bx0, bx1 = min(x for x, _ in filled) - 2, max(x for x, _ in filled) + 2
        placed = {k: v for k, v in placed.items() if bx0 <= k[0] <= bx1}
    # it hangs from the shoulders (from behind, draped over their tops)
    shoulder_top = parts.shoulders[0] - (2 if parts.facing == sp.BACK else 0)
    placed = {k: v for k, v in placed.items() if k[1] >= shoulder_top}
    if parts.facing == sp.BACK:  # (from behind, no wider than the back: where hers swings out, not his)
        _, sa, sb = parts.shoulders
        centre, back = (sa + sb) / 2, (sb - sa) * 0.38  # (the shoulder line runs over the arms)
        placed = {k: v for k, v in placed.items() if abs(k[0] - centre) <= back}
    on_body = {(x, y) for x, y in filled}
    seen: set = set()
    kept: Dict[sp.Point, int] = {}
    for start in list(placed):
        if start in seen:
            continue
        group, stack = [], [start]
        seen.add(start)
        while stack:
            q = stack.pop()
            group.append(q)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (q[0] + dx, q[1] + dy)
                    if n in placed and n not in seen:
                        seen.add(n)
                        stack.append(n)
        if any((q[0] + dx, q[1] + dy) in on_body for q in group for dx in (-1, 0, 1) for dy in (-1, 0, 1)) \
                and len(group) >= 4:
            kept.update({q: placed[q] for q in group})
    placed = kept
    # no holes: a pixel with cloak on both sides (along its row or its column, within two) is cloak
    for _ in range(2):
        fill = {}
        for (x, y) in list(placed):
            for dx, dy in ((1, 0), (0, 1)):
                for gap in (1, 2):
                    a, b = (x + dx, y + dy), (x + dx * (gap + 1), y + dy * (gap + 1))
                    if a not in placed and b in placed:
                        for k in range(1, gap + 1):
                            fill.setdefault((x + dx * k, y + dy * k), placed[(x, y)])
                        break
        placed.update(fill)
    if parts.facing == sp.BACK and placed:  # (from behind, up the back to the hair, as hers is worn)
        for x in {x for x, _ in placed}:
            y = min(yy for xx, yy in placed if xx == x)
            colour = placed[(x, y)]
            for up in range(1, 5):
                q = (x, y - up)
                if q not in on_body or q in keep:
                    break
                placed[q] = colour
    # a dark edge where the cloak meets the ground, as hers has (not along its top, at the shoulders)
    edge = set()
    for (x, y) in placed:
        for dx, dy in ((1, 0), (-1, 0), (0, 1)):
            n = (x + dx, y + dy)
            if n not in placed and n not in on_body and n not in keep:
                edge.add(n)
    for (x, y), p in placed.items():
        X, Y = x + pad, y + pad
        if not (0 <= Y < len(rows) and 0 <= X < len(rows[Y])):
            continue
        if (x, y) in keep or any(abs(x - hx) <= 1 and abs(y - hy) <= 1 for hx, hy in hands):
            continue
        over = parts.facing == sp.BACK
        if body[Y][X] is not None and not over:
            continue  # (behind the body)
        if shades is None or p == 254:
            colour = p if shades is None else shades[0]
        else:
            t = ramp.index(p) / max(1, len(ramp) - 1)
            colour = shades[min(len(shades) - 1, max(1, int(t * (len(shades) - 1) + 0.5)))]
        rows[Y][X] = colour
    outline = 254 if shades is None else shades[0]
    for x, y in edge:
        X, Y = x + pad, y + pad
        if 0 <= Y < len(rows) and 0 <= X < len(rows[Y]) and rows[Y][X] is None:
            rows[Y][X] = outline


# Boots and belts, recoloured like armour (the artist's pixels kept): boots the feet and lower
# shins, a belt a band at the waist across the body. Item type: shades, dark to light.
BOOTS = {68: (204, 207, 205, 194, 206)}  # Boots: faded leather
BELTS = {42: (204, 207, 205, 206), 35: (204, 207, 205, 206)}  # Belt, Belt of Might
MIGHT_BELT, BUCKLE = 35, 168


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


def _body_half_width(rows: Rows, parts: sp.Parts) -> float:
    """Half the body's own width (the run through its middle just above the waist, where the arms
    and hair seldom are), and a little for the shoulders' breadth."""
    if not parts.shoulders or parts.waist is None or not parts.head:
        return 3.0
    sy, sa, sb = parts.shoulders
    middle = (parts.head.left + parts.head.right) / 2 if parts.facing != sp.SIDE else (sa + sb) / 2
    widths = []
    for y in range(max(sy + 1, parts.waist - 3), parts.waist + 1):
        run = _torso_run(rows, y, middle, 0, len(rows[y]) - 1) if 0 <= y < len(rows) else None
        if run:
            widths.append(run[1] - run[0] + 1)
    width = sorted(widths)[len(widths) // 2] if widths else (sb - sa) * 0.6
    return width / 2 + 1.5


def _by_light(p: int, shades: Tuple[int, ...]) -> int:
    light = _LIGHT.get(p, 0.5)
    return shades[min(len(shades) - 1, max(0, int(light * 1.7 * (len(shades) - 1) + 0.5)))]


def _outline(rows: Rows, x: int, y: int) -> bool:
    return rows[y][x] == 254 and any(not (0 <= y + dy < len(rows) and 0 <= x + dx < len(rows[y + dy]))
                                     or rows[y + dy][x + dx] is None for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))


def draw_boots(rows: Rows, parts: sp.Parts, item_type: int, pad: int) -> None:
    """Boots: the lowest quarter of the legs (the feet and shins) in the boots' colours."""
    shades = BOOTS.get(item_type)
    if shades is None or parts.waist is None or not parts.feet:
        return
    top = parts.bottom - max(3, (parts.bottom - parts.waist) // 3)
    hands = list(parts.hands.values())
    for y in range(top, parts.bottom + 1):
        Y = y + pad
        for X, p in enumerate(rows[Y]):
            x = X - pad
            if p is None or _outline(rows, X, Y) or any(abs(x - hx) <= 2 and abs(y - hy) <= 2 for hx, hy in hands):
                continue
            rows[Y][X] = _by_light(p, shades)


def draw_belt(rows: Rows, parts: sp.Parts, item_type: int, pad: int) -> None:
    """A belt: a row at the waist across the body (not the arms or hands), a buckle at the front of
    the Belt of Might."""
    shades = BELTS.get(item_type)
    if shades is None or parts.waist is None or not parts.head:
        return
    unpadded = [r[pad:len(r) - pad] for r in rows[pad:]]
    middle = (parts.head.left + parts.head.right) / 2 if parts.facing != sp.SIDE else \
        (parts.shoulders[1] + parts.shoulders[2]) / 2 if parts.shoulders else parts.head.left
    half = _body_half_width(unpadded, parts) - 1.5
    hands = list(parts.hands.values())
    cells = []
    for y in (parts.waist,):
        run = _torso_run(unpadded, y, middle, 0, len(unpadded[0]) - 1) if 0 <= y < len(unpadded) else None
        if not run:
            continue
        for x in range(max(run[0], int(middle - half)), min(run[1], int(middle + half + 0.5)) + 1):
            if any(abs(x - hx) <= 1 and abs(y - hy) <= 1 for hx, hy in hands) or _outline(rows, x + pad, y + pad):
                continue
            cells.append((x, y))
    for x, y in cells:
        rows[y + pad][x + pad] = _by_light(unpadded[y][x], shades)
    if item_type == MIGHT_BELT and parts.facing == sp.FRONT and cells:
        rows[parts.waist + pad][int(round(middle)) + pad] = BUCKLE


def armed(rows: Rows, model: int, frame: int, combat: bool, weapons: Dict[str, Tuple[int, int]],
          pad: int = 10, armour: Tuple[int, ...] = (),
          cloak: Optional[Tuple[sp.Parts, Dict[sp.Point, int]]] = None) -> Rows:
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
    if parts.facing is not None and model != sp.KREEN:
        if "boots" in weapons:
            draw_boots(out, parts, weapons["boots"][0], pad)
        if "belt" in weapons:
            draw_belt(out, parts, weapons["belt"][0], pad)
    if "cloak" in weapons and parts.facing is not None and model != sp.KREEN:
        kind = weapons["cloak"][0]
        if model == CLOAK_MODEL:  # (her own cloak, in the cloak's colours: option 2)
            shades = CLOAK_COLOURS.get(kind, CLOAK_COLOURS[65])
            if shades is not None:
                ramp = sorted(CLOAK_GREENS, key=_cloak_shade)
                for y, row in enumerate(out):
                    for x, p in enumerate(row):
                        if p in CLOAK_GREENS:
                            t = ramp.index(p) / max(1, len(ramp) - 1)
                            row[x] = shades[min(len(shades) - 1, max(1, int(t * (len(shades) - 1) + 0.5)))]
        elif cloak is not None:
            draw_cloak(out, [list(r) for r in out], model, parts, kind, pad, cloak)
    if "helm" in weapons and parts.facing is not None and model != sp.KREEN:
        draw_helm(out, parts, weapons["helm"][0], pad, model)
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
            behind = g[1] or parts.facing == sp.BACK  # (from behind: held in front of the body)
            draw_shield(out, body, (hx + pad, hy + pad), parts.facing, colours, behind, MODEL_SCALE.get(model, 1.0))
        else:
            draw_weapon(out, body, (hx + pad, hy + pad), g[0], shape, colours, g[1], MODEL_SCALE.get(model, 1.0))
    return out


# Body armour: not drawn on, but the character's own clothing recoloured toward the armour's
# material, every pixel of the artist's shading kept where it was: each clothing colour, by its
# place from dark to light, the material's shade at the same place. Each piece recolours its part
# of the outfit (the chest above the waist, the arms the bands and bracers by the hands, the legs
# below the waist); never the head or the hair.
ARMOUR_CHEST, ARMOUR_ARMS, ARMOUR_LEGS = "chest", "arms", "legs"
PLAIN, RINGS, STUDS, SCALES, CHAIN, PLATE = "plain", "rings", "studs", "scales", "chain", "plate"
# shades, dark to light (muted, from the colours no region changes)
LEATHER_SHADES = (204, 207, 205, 194, 206)  # (faded browns)
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
# Each model's clothing colours, dark to light (by hand: not its skin, hair, eyes or wristbands;
# black only inside the outline). The human and half-elf woman's green cloak stays as it is.
CLOTHES: Dict[int, Tuple[int, ...]] = {
    2053: (254, 208, 209, 210, 211, 212, 50),
    2055: (254, 208, 209, 210, 211, 212, 50),
    2059: (254, 16, 174, 69, 175, 210, 176, 58, 37, 177, 36, 24, 178),
    2061: (254, 158, 16, 69, 159, 175, 48, 38, 210, 160, 37, 49, 36, 24, 71, 39, 161),
    2068: (254, 17, 18, 209, 48, 179, 210, 22, 180, 64, 181, 182, 168, 183, 184),
    2070: (254, 208, 209, 210),
    2072: (254, 208, 209, 207, 19, 210, 205, 49, 211, 212),
    2074: (254, 208, 209, 210, 211),
    2093: (254, 208, 209, 48, 210, 23, 50),
    2095: (254, 48, 20, 210, 23, 212, 50, 213, 29),
    2099: (254,),
}

def _keep_out(rows: Rows, parts: sp.Parts) -> set:
    """What armour never recolours: the head (its box down to where the shoulders start), the
    hair, and any pixel among the hair (its dark strands, in the clothes' own colours)."""
    out = set(parts.hair)
    if parts.head and parts.shoulders:
        h, neck = parts.head, parts.shoulders[0]
        out |= {(x, y) for y in range(h.top, neck) for x in range(h.left, h.right + 1)}
    for _ in range(2):
        among = set()
        for y, row in enumerate(rows):
            for x, p in enumerate(row):
                if p is None or (x, y) in out:
                    continue
                if sum((x + dx, y + dy) in parts.hair for dx in (-1, 0, 1) for dy in (-1, 0, 1)) >= 2:
                    among.add((x, y))
        out |= among
    return out


def _pattern(pattern: str, x: int, y: int, shade: int, top: int) -> int:
    """The shade (0 the darkest) with a light touch of the armour's pattern, on its lighter shades."""
    if shade < 2:
        return shade
    if pattern == CHAIN and (x + y) % 2 == 0:
        return shade - 1  # (mail's fine weave)
    if pattern == SCALES and y % 2 == 1 and (x + (y // 2) % 2) % 2 == 0:
        return shade - 1  # (the scales' lower edges, offset row to row)
    if pattern in (RINGS, STUDS) and x % 3 == 1 and y % 3 == 1:
        return min(top, shade + 1)  # (a ring's or stud's glint)
    return shade


def draw_armour(rows: Rows, model: int, parts: sp.Parts, item_type: int, pad: int) -> None:
    """One piece of armour: the model's clothing in its part of the (padded) picture ROWS
    recoloured into the armour's shades."""
    piece, shades, pattern = ARMOUR[item_type]
    clothes = CLOTHES.get(model, ())
    if not clothes or parts.waist is None:
        return
    rank = {c: i / max(1, len(clothes) - 1) for i, c in enumerate(clothes)}
    top = len(shades) - 1
    unpadded = [r[pad:len(r) - pad] for r in rows[pad:]]
    keep_out = _keep_out(unpadded, parts)
    hands = list(parts.hands.values())
    for y, row in enumerate(unpadded):
        for x, p in enumerate(row):
            if p not in rank or (x, y) in keep_out:
                continue
            if p == 254 and any(not (0 <= y + dy < len(unpadded) and 0 <= x + dx < len(row))
                                or unpadded[y + dy][x + dx] is None
                                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                continue  # (black at the edge is the outline, not clothing)
            by_hand = any(abs(x - hx) <= 2 and hy - 4 <= y <= hy + 1 for hx, hy in hands)
            part = ARMOUR_ARMS if by_hand else (ARMOUR_CHEST if y <= parts.waist else ARMOUR_LEGS)
            if part != piece:
                continue
            shade = min(top, int(rank[p] * top + 0.5))
            rows[y + pad][x + pad] = shades[_pattern(pattern, x, y, shade, top)]
