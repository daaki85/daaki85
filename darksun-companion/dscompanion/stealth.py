"""Hiding in shadows and moving silently in a fight (RULE_STEALTH): a way to backstab.

The game never rolls hide in shadows, and a backstab needs the thief to stand behind a target
that has turned to face someone else. With the rule on, a thief whose turn comes with no enemy
next to them tries to hide in shadows (the chance halved in daylight: on open ground under
Athas's sun), and if they do, to move silently up to someone. Both succeeding, the thief's next
attack this turn counts as one from behind (DSCLOG's PROBE_STEALTH), and so as a backstab with
a weapon that can backstab; attacking gives them away, and the turn ending ends the hiding.

Rangers do it too, with AD&D's chances for a ranger (the game gives them no thief skills;
game.ranger_skill_parts), but the other way round for the light: outdoorsmen, they hide with
the full chance under the open sky and half of it indoors. Their attack from behind is no
backstab (DSCLOG's own check keeps that to thieves). Someone with thief levels hides as a thief.

Daylight goes by the region (the map) the party is in: open desert, rock and the arena are
outdoors; the slave pens, the sewers, the caverns and the other underground or roofed places
are not. A few maps have both: buildings with floors of their own on open ground. There, it
goes by the floor under the thief: the game's map of the region (its RMAP, one tile number a
square) says which, and the tile numbers of those maps' indoor floors are below.
"""

import struct
from typing import Callable, List, Optional, Tuple

from . import game
from .game import GameData

HIDE, MOVE = 4, 3  # thief skill numbers (game.THIEF_SKILLS)
# Regions (RGNxx.GFF) by their maps: open ground, and maps with buildings on open ground (each
# with the tile numbers of its indoor floors); every other map is underground or roofed
OUTDOORS = frozenset((0x02, 0x04, 0x05, 0x07, 0x08, 0x09, 0x0A, 0x0F, 0x12, 0x14, 0x1A, 0x1D, 0x1F,
                      0x21, 0x22, 0x23, 0x2A, 0xFF))
INDOOR_TILES = {
    0x03: frozenset((163, 164, 165, 166, 168, 169, 170, 171, 179, 182, 183, 185, 186, 187, 188, 190, 191,
                     192, 193, 194, 195, 198, 199, 200, 201, 202, 204, 205, 206, 207)),
    0x0B: frozenset((66, 70, 71, 72, 73, 74, 75, 76, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91,
                     92, 93, 97, 98, 99, 100, 101, 105, 106, 107, 108, 109, 110, 112, 113, 121, 122, 123,
                     125, 139, 140, 162, 168, 189, 190, 191, 192, 193, 194)),
    0x0D: frozenset((13, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 45, 46, 47,
                     48, 54, 55, 57, 58, 60, 61, 62, 63, 64, 65, 66, 67, 69, 76, 77, 78, 79, 81, 87, 143,
                     144, 145, 146, 147)),
}
MAP_PTR = 0x2F4A  # DS: far pointer to the region's map: a tile number a square, MAP_WIDTH to a row
MAP_WIDTH, MAP_HEIGHT = 128, 98
POSITIONS, POSITION_SIZE = 0x669D, 32  # DS: each object's x, y, in 16ths of a square
TSR_STEALTH, TSR_STEALTH_USED = 204, 206  # in DSCLOG's header
STATUS_GONE = (4, 5)  # Dying, Dead: no threat


def square(gd: GameData, combatant: int) -> Tuple[int, int]:
    x, y = struct.unpack("<HH", gd.guest.read(gd.ds * 16 + POSITIONS + combatant * POSITION_SIZE, 4))
    return x >> 4, y >> 4


def daylight(gd: GameData, combatant: int) -> bool:
    """The thief stands under the open sky: an outdoor map, or open ground on a map with
    buildings."""
    region = gd.region()
    if region in OUTDOORS:
        return True
    floors = INDOOR_TILES.get(region)
    if floors is None:
        return False
    x, y = square(gd, combatant)
    if not (0 <= x < MAP_WIDTH and 0 <= y < MAP_HEIGHT):
        return True
    tile = gd.guest.read(game.far_pointer(gd.guest, gd.ds, MAP_PTR) + y * MAP_WIDTH + x, 1)[0]
    return tile not in floors


def enemy_beside(gd: GameData, combatant: int) -> Optional[str]:
    """The name of an enemy standing next to the combatant (any of the eight squares around),
    if one is: someone up and about on another side."""
    me = gd.combatant_creature(combatant)
    if me is None:
        return None
    side = gd.creature(me)[game.CREATURE_SIDE]
    x, y = square(gd, combatant)
    for other, index in gd.combatants().items():
        if other == combatant:
            continue
        rec = gd.creature(index)
        if len(rec) < game.CREATURE_SIZE or rec[game.CREATURE_SIDE] == side:
            continue
        if struct.unpack_from("<h", rec, 0)[0] <= 0 or rec[game.CREATURE_STATUS] in STATUS_GONE:
            continue
        ox, oy = square(gd, other)
        if max(abs(ox - x), abs(oy - y)) <= 1:
            return gd.creature_name(index)
    return None


def chance(gd: GameData, creature: int, skill: int) -> Optional[int]:
    skills = gd.thief_skills_now(creature, (skill,))
    return skills[0][1] if skills else None


def ranger_chance(gd: GameData, creature: int, skill: int) -> Optional[int]:
    return gd.ranger_skill_now(creature, skill)


def turn(gd: GameData, combatant: int, roll: Callable[[], int]) -> Tuple[List[str], bool]:
    """A party member's turn has come in a fight: if a thief or a ranger, the hiding and moving
    silently. (log lines, whether their next attack is from behind)."""
    creature = gd.combatant_creature(combatant)
    if creature is None or creature >= game.PARTY_SIZE:
        return [], False
    hide = chance(gd, creature, HIDE)
    of = chance
    ranger = hide is None
    if ranger:
        hide, of = ranger_chance(gd, creature, HIDE), ranger_chance
    if hide is None:
        return [], False
    who = gd.creature_name(creature)
    enemy = enemy_beside(gd, combatant)
    if enemy:
        return [f"{who} can't hide in shadows: {enemy} is right beside them"], False
    sun = daylight(gd, combatant)
    if ranger:  # at home under the open sky
        need = hide if sun else hide // 2
        why = f"{hide}, a ranger under the open sky" if sun else f"{hide}, halved indoors for a ranger"
    else:
        need = hide // 2 if sun else hide
        why = f"{hide}, halved in daylight" if sun else f"{hide}, out of the sun"
    d100 = roll()
    hidden = d100 <= need
    lines = [f"{who} hides in shadows: d100 = {d100}, needs {need} or less ({why}) -> "
             + ("hidden" if hidden else "seen")]
    if not hidden:
        return lines, False
    quiet = of(gd, creature, MOVE) or 0
    d100 = roll()
    unheard = d100 <= quiet
    behind = "from behind" if ranger else "from behind (a backstab with a weapon that can)"
    lines.append(f"  {who} moves silently: d100 = {d100}, needs {quiet} or less -> "
                 + (f"unheard: their next attack this turn is {behind}" if unheard else "heard"))
    return lines, unheard
