"""Rings on the ground under the enemies in a fight (DSCLOG's RINGS), and the one chosen.

DSCLOG draws them in the floor pass, as the shadows, so the figures stand in them: an ellipse at
each marked thing's feet, the ground reddened through RED, which the Ledger makes from the area's
palette (each colour's nearest redder one). The Ledger marks the enemies while the party is in a
fight (the creatures standing on another side than the party's), and the chosen one (targeting.py)
brighter; when the marks change, the view is drawn again.
"""

import struct
from typing import Optional

from . import game, shadows

TSR_RINGS_ON, TSR_RING_TAB, TSR_RED = 244, 246, 248  # DSCLOG's header
TSR_HDR_OFF = 20
THINGS = 520
FIRST, LAST = 16, 223  # the colours the game doesn't animate
RED = (230, 40, 30)
TOWARD = 0.6  # how far toward RED a colour is wanted
HUE_WEIGHT = 2
STATUS_DEAD = 5
SIDE_NEUTRAL = 4  # (the arena's Tied-up Prisoner: on no one's side)
RING, CHOSEN = 1, 2


def red_table(dac: bytes) -> bytes:
    """Each colour's redder one among the palette's (0: none redder enough). DAC: 0-63 values."""
    pal = [tuple(min(255, dac[i * 3 + k] * 4) for k in range(3)) for i in range(256)]
    out = bytearray(256)
    for i in range(FIRST, LAST + 1):
        c = pal[i]
        want = tuple(v + (r - v) * TOWARD for v, r in zip(c, RED))
        best, score = 0, None
        for j in range(FIRST, LAST + 1):
            p = pal[j]
            if j == i or p[0] - (p[1] + p[2]) / 2 <= c[0] - (c[1] + c[2]) / 2 + 8:
                continue  # (redder, clearly)
            d = sum((a - b) ** 2 for a, b in zip(p, want))
            d += HUE_WEIGHT * (((p[0] - p[1]) - (want[0] - want[1])) ** 2)
            if score is None or d < score:
                best, score = j, d
        out[i] = best
    return bytes(out)


def enemies(gd) -> list:
    """The things (combatants) standing on another side than the party's leader (not a neutral
    one's), in a fight."""
    if not gd.in_combat():
        return []
    leader = gd.creature(0)
    if len(leader) < game.CREATURE_SIZE:
        return []
    out = []
    for combatant, index in sorted(gd.combatants().items()):
        if combatant >= THINGS or index < game.PARTY_SIZE:
            continue
        rec = gd.creature(index)
        if len(rec) < game.CREATURE_SIZE or not rec[game.CREATURE_NAME]:
            continue
        hp = struct.unpack_from("<h", rec, 0)[0]
        side = rec[game.CREATURE_SIDE]
        if hp > 0 and rec[game.CREATURE_STATUS] != STATUS_DEAD and side not in (leader[game.CREATURE_SIDE], SIDE_NEUTRAL):
            out.append(combatant)
    return out


def ring_table(marked, chosen: Optional[int]) -> bytes:
    out = bytearray(THINGS)
    for thing in marked:
        out[thing] = RING
    if chosen is not None and 0 <= chosen < THINGS:
        out[chosen] = CHOSEN
    return bytes(out)


class Rings:
    def __init__(self):
        self._palettes = -1
        self._table: Optional[bytes] = None
        self._on: Optional[bool] = None

    def update(self, gd, tsr_hdr: int, on: bool, palettes: int, chosen: Optional[int] = None) -> list:
        """Keep DSCLOG's rings up; returns the enemies marked (for Tab)."""
        guest = gd.guest
        base = tsr_hdr - struct.unpack("<H", guest.read(tsr_hdr + TSR_HDR_OFF, 2))[0]
        if not on:
            if self._on is not False:
                guest.write(tsr_hdr + TSR_RINGS_ON, struct.pack("<H", 0))
                if self._table and any(self._table):
                    shadows.redraw(gd, tsr_hdr)
            self._on, self._table, self._palettes = False, None, -1
            return []
        if palettes != self._palettes and palettes:
            red_off, = struct.unpack("<H", guest.read(tsr_hdr + TSR_RED, 2))
            dac_off, = struct.unpack("<H", guest.read(tsr_hdr + 238, 2))  # (DSCLOG's DAC, as dust.py)
            guest.write(base + red_off, red_table(guest.read(base + dac_off, 768)))
            guest.write(tsr_hdr + TSR_RINGS_ON, struct.pack("<H", 1))
            self._palettes, self._on = palettes, True
        marked = enemies(gd)
        table = ring_table(marked, chosen if chosen in marked else None)
        if table != self._table:
            off, = struct.unpack("<H", guest.read(tsr_hdr + TSR_RING_TAB, 2))
            guest.write(base + off, table)
            self._table = table
            shadows.redraw(gd, tsr_hdr)
        return marked
