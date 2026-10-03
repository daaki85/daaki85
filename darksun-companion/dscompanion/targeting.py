"""Choosing an enemy with Tab in a fight, and attacking it with Enter (DSCLOG's TARGETING).

DSCLOG counts Tab and Shift+Tab (taking them from the game) while the Ledger has it on: during a
party member's turn in a fight. The Ledger steps through the enemies (rings.enemies), the nearest
to whoever's turn it is first, and tells DSCLOG which is chosen: its ring is drawn brighter, and
Enter then has DSCLOG click on it for the game, the routine finding what is under the pointer
answering with it whatever stands in front.
"""

import math
import struct
from typing import List, Optional

from . import game

TSR_TARGET_ON, TSR_TAB, TSR_BACK, TSR_TARGET, TSR_ATTACK = 250, 252, 254, 256, 258  # DSCLOG's header
NONE = 0xFFFF
MAP_THINGS, MAP_THING_SIZE, MAP_FEET = 0x6694, 32, 9  # DS: things on the map, their feet (x, y)
CAMERA = 0x1178  # DS: the view's top left on the map
TSR_PAN = 230  # DSCLOG's PAN_X, PAN_Y (scrolling.py)
VIEW_W, VIEW_H, VIEW_TOP, VIEW_MARGIN = 320, 200, 30, 24  # (the view; its top has the name box)


def feet(gd, thing: int):
    return struct.unpack("<HH", gd.guest.read(gd.ds * 16 + MAP_THINGS + thing * MAP_THING_SIZE + MAP_FEET, 4))


def by_distance(gd, me: int, enemies: List[int]) -> List[int]:
    """The enemies, the nearest to ME first."""
    mx, my = feet(gd, me)
    return sorted(enemies, key=lambda e: (math.hypot(feet(gd, e)[0] - mx, feet(gd, e)[1] - my), e))


class Targeting:
    def __init__(self):
        self.chosen: Optional[int] = None
        self._seqs: Optional[tuple] = None
        self._on: Optional[bool] = None
        self._turn: Optional[int] = None

    def forget(self) -> None:
        self.__init__()

    @staticmethod
    def _show(gd, tsr_hdr: int, thing: int) -> bool:
        """The view scrolled (by DSCLOG's PAN) to the chosen enemy, when it is out of it (Enter
        clicks on it, so it must be on screen)."""
        x, y = feet(gd, thing)
        cx, cy = struct.unpack("<HH", gd.guest.read(gd.ds * 16 + CAMERA, 4))
        sx, sy = x - cx, y - cy
        if VIEW_MARGIN <= sx <= VIEW_W - VIEW_MARGIN and VIEW_MARGIN + VIEW_TOP <= sy <= VIEW_H - VIEW_MARGIN:
            return False
        dx, dy = sx - VIEW_W // 2, sy - VIEW_H // 2
        px, py = struct.unpack("<HH", gd.guest.read(tsr_hdr + TSR_PAN, 4))
        gd.guest.write(tsr_hdr + TSR_PAN, struct.pack("<HH", (px + dx) & 0xFFFF, (py + dy) & 0xFFFF))
        return True

    def update(self, gd, tsr_hdr: int, on: bool, enemies: List[int]) -> List[str]:
        """Keep DSCLOG's targeting up; returns lines for the log (an enemy chosen)."""
        guest = gd.guest
        turn = gd.whose_turn() if gd.in_combat() else None
        active = bool(on and turn is not None and turn < game.PARTY_SIZE and enemies)
        if active != self._on:
            guest.write(tsr_hdr + TSR_TARGET_ON, struct.pack("<H", int(active)))
            self._on = active
        seqs = struct.unpack("<HH", guest.read(tsr_hdr + TSR_TAB, 4))
        steps = 0
        if self._seqs is not None:
            steps = ((seqs[0] - self._seqs[0]) & 0xFFFF) - ((seqs[1] - self._seqs[1]) & 0xFFFF)
        self._seqs = seqs
        out = []
        if not active or turn != self._turn:
            self.chosen = None  # (a new turn: chosen again)
        self._turn = turn
        if active and steps:
            order = by_distance(gd, turn, enemies)
            if self.chosen in order:
                self.chosen = order[(order.index(self.chosen) + steps) % len(order)]
            else:
                self.chosen = order[0] if steps > 0 else order[-1]
            out_of_view = self._show(gd, tsr_hdr, self.chosen)
            index = gd.combatant_creature(self.chosen)
            if index is not None:
                rec = gd.creature(index)
                hp = struct.unpack_from("<h", rec, 0)[0] if len(rec) >= 2 else None
                out.append(f"Chosen with Tab: {gd.creature_name(index)}" + (f" ({hp} HP)" if hp is not None else "")
                           + " - Enter attacks it")
        if self.chosen is not None and self.chosen not in enemies:
            self.chosen = None
        guest.write(tsr_hdr + TSR_TARGET, struct.pack("<H", NONE if self.chosen is None else self.chosen))
        return out
