"""Shadows under the figures on the map (DSCLOG's SHADOWS), kept up by the Ledger.

DSCLOG draws them: after the game draws the floor of the map's view (or of a rectangle of it), each
figure marked in its table casts a see-through shadow on it, its outline laid down toward the lower
left (the light on the game's maps comes from the upper right, as the walls' shadows show), before
the walls and figures are drawn, so everything stands on the shadows. A shadow darkens the floor
through a table of each colour's darker one, which DSCLOG makes from the palette when asked.

The Ledger keeps its table of who casts one (the living creatures among the game's 520 things: the
party, the people, the monsters; not the dead, nor items) and asks for the darker colours again
when the area, so the palette, changes (once its fade-in is over) and now and then.
"""

import struct
from typing import Optional

from . import game

TSR_ON, TSR_TABLE, TSR_BUILD = 220, 222, 224  # DSCLOG's header: shadows on, the table, make DARK
TSR_HDR_OFF = 20
THINGS = 520
STATUS_DEAD = 5
CREATURE = 2  # (a thing's kind)
REFRESH = 0.5  # seconds between looks at who casts a shadow
REDRAW_AFTER = 0.6  # seconds after the darker colours are asked for (or who casts one changes)
# to have those figures drawn again (with the floor round them, so with their shadows): one
# standing still is otherwise drawn again only when the whole view is
MAP_THINGS, MAP_THING_SIZE, MAP_CHANGED = 0x6694, 32, 0x01  # DS: things on the map (sprites.py)
BUILD_AFTER = (3.0, 8.0)  # seconds after an area change to have the darker colours made again
BUILD_EVERY = 30.0  # ... and anyway this often


def casting(gd) -> bytes:
    """A byte for each of the game's things: 1 for a living creature."""
    things = gd.guest.read((gd.load_seg + game.COMBATANTS_SEG) * 16 + game.COMBATANTS_OFF, THINGS * 3)
    out = bytearray(THINGS)
    for thing in range(THINGS):
        kind, index = struct.unpack_from("<Bh", things, thing * 3)
        if kind != CREATURE or not 0 <= index < 512:
            continue
        rec = gd.creature(index)
        if len(rec) >= game.CREATURE_SIZE and rec[game.CREATURE_NAME] and rec[game.CREATURE_STATUS] != STATUS_DEAD:
            out[thing] = 1
    return bytes(out)


class Shadows:
    def __init__(self):
        self._on: Optional[bool] = None
        self._table: Optional[bytes] = None
        self._looked = 0.0
        self._region: Optional[int] = None
        self._builds = []  # times to have the darker colours made again
        self._built = 0.0
        self._redraw_at: Optional[float] = None

    def update(self, gd, tsr_hdr: int, on: bool, now: float) -> None:
        guest = gd.guest
        if on != self._on:
            guest.write(tsr_hdr + TSR_ON, struct.pack("<H", int(on)))
            if on:
                self._builds = [now]
            elif self._on and self._table is not None:
                redraw(gd, self._table)  # (their shadows gone at once)
            self._on = on
        if not on:
            return
        region = gd.region()
        if region != self._region:
            self._region = region
            self._builds += [now + after for after in BUILD_AFTER]
        if now - self._built >= BUILD_EVERY:
            self._builds.append(now)
        due = [t for t in self._builds if t <= now]
        if due:
            self._builds = [t for t in self._builds if t > now]
            guest.write(tsr_hdr + TSR_BUILD, struct.pack("<H", 1))
            self._built = now
            self._redraw_at = now + REDRAW_AFTER
        if self._redraw_at is not None and now >= self._redraw_at and self._table is not None:
            self._redraw_at = None
            redraw(gd, self._table)
        if now - self._looked < REFRESH:
            return
        self._looked = now
        table = casting(gd)
        if table != self._table:
            base = tsr_hdr - struct.unpack("<H", guest.read(tsr_hdr + TSR_HDR_OFF, 2))[0]
            offset = struct.unpack("<H", guest.read(tsr_hdr + TSR_TABLE, 2))[0]
            guest.write(base + offset, table)
            self._table = table
            self._redraw_at = now + REDRAW_AFTER


def redraw(gd, table: bytes) -> None:
    """The figures that cast a shadow marked changed, so the game draws them again (and the floor
    round them, with their shadows)."""
    things = gd.guest.read(gd.ds * 16 + MAP_THINGS, THINGS * MAP_THING_SIZE)
    for thing in range(THINGS):
        if table[thing] and not things[thing * MAP_THING_SIZE] & MAP_CHANGED:
            gd.guest.write(gd.ds * 16 + MAP_THINGS + thing * MAP_THING_SIZE,
                           bytes([things[thing * MAP_THING_SIZE] | MAP_CHANGED]))
