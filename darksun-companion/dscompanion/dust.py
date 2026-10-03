"""Dust raised by walking figures (DSCLOG's DUST), on sand and dirt.

DSCLOG raises the puffs and draws them on the floor (lightening its colours, as the shadows darken
them); which colours are ground that dust shows on, and how much lighter it makes each, is the
Ledger's to work out from the area's palette, each time DSCLOG has read it (shadows.py asks for
that): LIGHT, a byte for each colour, its lighter one among the palette's, or 0.
"""

import colorsys
import struct
from typing import Optional

TSR_DUST_ON, TSR_LIGHT, TSR_DAC = 234, 236, 238  # DSCLOG's header
TSR_HDR_OFF = 20
FIRST, LAST = 16, 223  # the colours the game doesn't animate (as DARK's)
LIGHTER = 0.45  # how far toward white a colour is wanted
HUE_WEIGHT = 3


def is_ground(rgb) -> bool:
    """Sand and dirt: warm, not too grey or too strong, neither dark nor white."""
    r, g, b = (v / 255 for v in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return 0.02 <= h <= 0.15 and 0.12 <= s <= 0.65 and 0.4 <= v <= 0.97


def _lum(c) -> float:
    return 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]


def light_table(dac: bytes) -> bytes:
    """Each colour's lighter one (keeping its hue) for the ground's colours, 0 for the rest.
    DAC: the palette as the VGA has it, 3 bytes of 0-63 for each colour."""
    pal = [tuple(min(255, dac[i * 3 + k] * 4) for k in range(3)) for i in range(256)]
    out = bytearray(256)
    for i in range(FIRST, LAST + 1):
        c = pal[i]
        if not is_ground(c):
            continue
        want = tuple(v + (255 - v) * LIGHTER for v in c)
        best, score = 0, None
        for j in range(FIRST, LAST + 1):
            p = pal[j]
            if _lum(p) <= _lum(c) * 1.06:
                continue
            d = sum((a - b) ** 2 for a, b in zip(p, want))
            d += HUE_WEIGHT * (((p[0] - p[1]) - (want[0] - want[1])) ** 2 + ((p[1] - p[2]) - (want[1] - want[2])) ** 2)
            if score is None or d < score:
                best, score = j, d
        out[i] = best
    return bytes(out)


class Dust:
    def __init__(self):
        self._on: Optional[bool] = None
        self._palettes = -1

    def update(self, gd, tsr_hdr: int, on: bool, palettes: int) -> None:
        """ON: dust raised; PALETTES: shadows.Shadows.palettes (LIGHT made again when it counts)."""
        guest = gd.guest
        if not on:
            if self._on is not False:
                guest.write(tsr_hdr + TSR_DUST_ON, struct.pack("<H", 0))
            self._on, self._palettes = False, -1
            return
        if palettes == self._palettes or palettes == 0:
            return
        base = tsr_hdr - struct.unpack("<H", guest.read(tsr_hdr + TSR_HDR_OFF, 2))[0]
        light_off, dac_off = struct.unpack("<HH", guest.read(tsr_hdr + TSR_LIGHT, 4))
        guest.write(base + light_off, light_table(guest.read(base + dac_off, 768)))
        guest.write(tsr_hdr + TSR_DUST_ON, struct.pack("<H", 1))
        self._on, self._palettes = True, palettes
