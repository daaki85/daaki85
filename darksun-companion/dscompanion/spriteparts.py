"""Where the parts of a party member's map sprite are, frame by frame: the head (and its brow),
the hair, the shoulders, the hands, the waist and the feet. What the Ledger draws worn equipment
from (a weapon in the hand, a helm on the head, a cloak from the shoulders under the hair).

The party are objects 300-313 (SEGOBJEX's OJFF chunks), each naming one of 12 sprite models (a
BMP chunk of 15 frames, the next chunk the model's 14 combat frames). Nothing of the game's is
kept here: the pictures are read from the player's install; this module holds only how to find
the parts in them (each model's wristband and hair colours) and the corrections to what it finds,
by hand, for the frames where finding them goes wrong.

Walking frames: 0 front, 1 back, 2 side (standing); 3-6 walking toward the viewer, 7-10 away,
11-14 to the side. Combat frames: 0-2 attacking toward the viewer, 3-5 away, 6-8 to the side;
9-11 the bow (front, back, side); 12 hit; 13 dead. The side frames face right (the game mirrors
them for left).
"""

from typing import Dict, List, NamedTuple, Optional, Set, Tuple

Rows = List[List[Optional[int]]]
Point = Tuple[int, int]

PARTY_OBJECTS = range(300, 314)
WALK_FRAMES, COMBAT_FRAMES = 15, 14

FRONT, BACK, SIDE = "front", "back", "side"
WALK_FACING = [FRONT, BACK, SIDE] + [FRONT] * 4 + [BACK] * 4 + [SIDE] * 4
COMBAT_FACING = [FRONT] * 3 + [BACK] * 3 + [SIDE] * 3 + [FRONT, BACK, SIDE, FRONT, None]
BOW_FRAMES = (9, 10, 11)  # (combat frames: the game draws the bow in them)
DEAD_FRAME = 13

GREEN_BANDS = frozenset((249, 250))
GREY_BANDS = frozenset((208, 209, 210, 211, 212))

# Each model (its walking chunk): (what it is, its wristbands' colours, its hair's colours). The
# hair's are the colours of the hair only (not the face's), as the pictures have them.
MODELS: Dict[int, Tuple[str, frozenset, frozenset]] = {
    2053: ("mul", GREEN_BANDS, frozenset()),
    2055: ("mul", GREEN_BANDS, frozenset()),
    2059: ("half-elf woman", GREEN_BANDS, frozenset((64, 65, 180, 181, 182, 200, 201))),
    2061: ("half-elf man", GREEN_BANDS, frozenset((44, 45, 64, 65, 180, 181, 182, 200))),
    2068: ("dwarf", GREEN_BANDS, frozenset((128, 129, 201))),
    2070: ("halfling", GREEN_BANDS, frozenset((179, 180, 181, 182, 183, 201))),
    2072: ("half-giant man", GREY_BANDS, frozenset((128, 129, 133, 179, 180))),
    2074: ("half-giant woman", GREY_BANDS, frozenset((128, 129, 133, 179, 180))),
    2093: ("mul", GREEN_BANDS, frozenset()),
    2095: ("human man", GREEN_BANDS, frozenset((23, 29, 48, 50, 69, 70))),
    2097: ("thri-kreen", GREEN_BANDS, frozenset()),
    2099: ("elf woman", GREEN_BANDS, frozenset((128, 129, 133, 134, 179, 180, 202))),
}


# Each model's head, in rows from the crown to the shoulders (front, back, side), by hand: where the
# hair is wider than the shoulders the picture doesn't show where the neck is.
HEAD_ROWS: Dict[int, Tuple[int, int, int]] = {
    2053: (3, 5, 7), 2055: (3, 5, 7), 2059: (7, 7, 7), 2061: (7, 7, 8), 2068: (5, 6, 7), 2070: (7, 7, 7),
    2072: (8, 9, 10), 2074: (8, 9, 10), 2093: (5, 6, 8), 2095: (5, 6, 8), 2097: (3, 3, 3), 2099: (7, 7, 8),
}


# The thri-kreen's head: found by its eyes (its antennae stand above it)
KREEN = 2097
KREEN_EYES = frozenset((158, 159, 160, 161))


class Head(NamedTuple):
    top: int
    left: int
    right: int
    brow: int  # the row a helm's rim sits on (the hair line in front)


class Parts(NamedTuple):
    facing: Optional[str]
    head: Optional[Head]
    hair: Set[Point]
    shoulders: Optional[Tuple[int, int, int]]  # (row, left, right): the outside of the shoulders
    hands: Dict[str, Point]  # "right" / "left" (the character's own): where a grip would be
    waist: Optional[int]
    feet: List[Tuple[int, int, int]]  # (row, left, right) of each foot's lowest row
    bottom: int


def _runs(row: List[Optional[int]]) -> List[Tuple[int, int]]:
    out, x = [], 0
    while x < len(row):
        if row[x] is None:
            x += 1
            continue
        start = x
        while x < len(row) and row[x] is not None:
            x += 1
        out.append((start, x - 1))
    return out


def _clusters(rows: Rows, colours: frozenset, within: Optional[Set[Point]] = None) -> List[List[Point]]:
    """Groups of touching pixels in COLOURS (diagonals touch too)."""
    seen: Set[Point] = set()
    groups = []
    for y, row in enumerate(rows):
        for x, p in enumerate(row):
            if p not in colours or (x, y) in seen or (within is not None and (x, y) not in within):
                continue
            group, stack = [], [(x, y)]
            seen.add((x, y))
            while stack:
                a, b = stack.pop()
                group.append((a, b))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        n = (a + dx, b + dy)
                        if 0 <= n[1] < len(rows) and 0 <= n[0] < len(rows[n[1]]) and n not in seen \
                                and rows[n[1]][n[0]] in colours:
                            seen.add(n)
                            stack.append(n)
            groups.append(group)
    return groups


def _head(rows: Rows, height: Optional[int] = None) -> Tuple[Optional[Head], int]:
    """The head, and the row the shoulders start on: HEIGHT rows down from the crown, or where the
    picture widens out of the neck."""
    filled = [y for y, r in enumerate(rows) if any(p is not None for p in r)]
    if not filled:
        return None, 0
    top = filled[0]
    crown = _runs(rows[top])
    middle = (crown[0][0] + crown[-1][1]) // 2
    left = right = middle
    neck = None
    widths = []
    for y in range(top, min(top + 12, len(rows))):
        run = next(((a, b) for a, b in _runs(rows[y]) if a - 1 <= middle <= b + 1), None)
        if run is None:
            break
        width = run[1] - run[0] + 1
        if height is not None:
            if y - top >= height:
                neck = y
                break
            widths.append(width)
            left, right = min(left, run[0]), max(right, run[1])
            continue
        # the neck: where the run widens into the shoulders (or meets an arm), and no lower than
        # a third of the way down the picture
        if len(widths) >= 3 and (width > max(widths[-3:]) + 3 or width > sorted(widths)[len(widths) // 2] * 3 // 2 + 1) \
                or y - top > (len(rows) - top) // 3:
            neck = y
            break
        widths.append(width)
        left, right = min(left, run[0]), max(right, run[1])
    if neck is None:
        neck = top + len(widths)
    brow = top + max(1, (neck - top) * 2 // 5)
    return Head(top, left, right, brow), neck


def find(rows: Rows, model: int, frame: int, combat: bool = False) -> Parts:
    """The parts of one frame of MODEL's walking (or COMBAT) pictures, before corrections."""
    facing = (COMBAT_FACING if combat else WALK_FACING)[frame]
    filled = [y for y, r in enumerate(rows) if any(p is not None for p in r)]
    bottom = filled[-1] if filled else 0
    _, bands, hair_colours = MODELS[model]
    heights = HEAD_ROWS.get(model)
    head, neck = _head(rows, heights[(FRONT, BACK, SIDE).index(facing)] if heights and facing else None)
    if model == KREEN:
        eyes = [(x, y) for y, r in enumerate(rows) for x, p in enumerate(r) if p in KREEN_EYES]
        if eyes:
            ex, ey = [x for x, _ in eyes], [y for _, y in eyes]
            head = Head(min(ey) - 2, min(ex) - 1, max(ex) + 1, min(ey) - 1)
            neck = max(ey) + 2
    if combat and frame == DEAD_FRAME:
        return Parts(None, None, set(), None, {}, None, [], bottom)

    # the shoulders: the widest the picture is just below the neck
    shoulders = None
    if head:
        spans = [_runs(rows[y]) for y in range(neck, min(neck + 3, len(rows)))]
        middle = (head.left + head.right) // 2
        body = [next(((a, b) for a, b in s if a - 2 <= middle <= b + 2), None) for s in spans]
        body = [r for r in body if r]
        if body:
            shoulders = (neck, min(a for a, _ in body), max(b for _, b in body))

    # the hair: hair-coloured pixels around the head joined to the crown's: down to the shoulders,
    # and from behind (where long hair falls over the back) to the waist
    hair: Set[Point] = set()
    waist = neck + round((bottom - neck) * 0.42) if head else None
    if head and hair_colours:
        lowest = waist if facing == BACK else neck + 1
        zone = {(x, y) for y in range(head.top, min(lowest, bottom) + 1)
                for x in range(head.left - 3, head.right + 4)}
        if facing == FRONT:  # (not the face)
            zone -= {(x, y) for y in range(head.brow + 1, neck + 1) for x in range(head.left + 2, head.right - 1)}
        for group in _clusters(rows, hair_colours, within=zone):
            if any(y <= head.brow for _, y in group):
                hair.update(group)

    # the hands: the wristbands farthest out from the body, below the shoulders
    hands: Dict[str, Point] = {}
    if head:
        middle = (head.left + head.right) / 2
        found = []
        lowest = waist + 3 if waist is not None else bottom - 3  # (the hands hang no lower than the hips)
        for group in _clusters(rows, bands):
            gx = sum(x for x, _ in group) / len(group)
            gy = sum(y for _, y in group) / len(group)
            if gy < head.brow or gy > lowest:
                continue  # (knee and boot bands, and the like)
            reach = abs(gx - middle) + max(0, gy - neck) / 2  # out from the body, and down the arm
            outer = max((x for x, _ in group), key=lambda x: abs(x - middle))  # (the band's outer edge)
            found.append((reach, outer, max(y for _, y in group), group))
        found.sort(reverse=True)
        sides: Dict[bool, tuple] = {}
        for f in found:  # the farthest band on each side of the body (not an elbow's)
            sides.setdefault(f[1] < middle, f)
        found = sorted(sides.values(), key=lambda f: f[1])  # left of the picture first
        for i, (_, gx, gy, _) in enumerate(found):
            on_left = gx < middle
            if facing == FRONT:
                name = "right" if on_left else "left"  # (facing the viewer: their right is on the left)
            elif facing == BACK:
                name = "left" if on_left else "right"
            else:
                name = "left" if on_left else "right"  # facing right: the forward hand, the near one
            hands[name] = (gx, gy + 1)  # (just below the band: the hand)

    # the feet: the lowest row of each leg (runs in the last rows not over one already found)
    feet: List[Tuple[int, int, int]] = []
    for y in range(bottom, max(bottom - 5, -1), -1):
        for a, b in _runs(rows[y]):
            if not any(a <= fb and fa <= b for _, fa, fb in feet):
                feet.append((y, a, b))
    return Parts(facing, head, hair, shoulders, hands, waist, sorted(feet[:2], key=lambda f: f[1]), bottom)


# Corrections by hand: (model, combat, frame) -> {part: value}. The half-giants' grey bands are on
# their shoulders, elbows and knees too: from behind and from the side their hands are set here.
CORRECTIONS: Dict[Tuple[int, bool, int], dict] = {
    (2072, False, 1): {"hands": {"left": (1, 19), "right": (25, 18)}},
    (2072, False, 2): {"hands": {"left": (1, 24), "right": (18, 21)}},
    (2072, False, 11): {"hands": {"left": (1, 23), "right": (17, 22)}},
    (2072, False, 12): {"hands": {"right": (24, 12)}},
    (2072, False, 13): {"hands": {"left": (2, 25), "right": (17, 15)}},
    (2072, False, 14): {"hands": {"left": (5, 17), "right": (24, 18)}},
    (2074, False, 1): {"hands": {"left": (1, 18), "right": (25, 17)}},
    (2074, False, 2): {"hands": {"left": (2, 23), "right": (18, 22)}},
    (2074, False, 11): {"hands": {"left": (2, 21), "right": (17, 22)}},
    (2074, False, 12): {"hands": {"right": (24, 13)}},
    (2074, False, 13): {"hands": {"left": (2, 25), "right": (16, 16)}},
    (2074, False, 14): {"hands": {"left": (5, 17), "right": (24, 18)}},
}


def parts(rows: Rows, model: int, frame: int, combat: bool = False) -> Parts:
    """The parts of one frame, found and corrected."""
    found = find(rows, model, frame, combat)
    fix = CORRECTIONS.get((model, combat, frame))
    return found._replace(**fix) if fix else found
