"""The game's own portraits and font, read from the installed game at run time.

Nothing of the game's is copied into Templar's Ledger: the pictures come from
the player's own install (GOG release), and when it can't be found the window
simply does without them.

  * Portraits: GPLDATA.GFF, PORT chunks (the number the dialogue window shows,
    1 to 120; and Kalzith's, which the companion makes from one of them), in the
    colours of GPLDATA's first palette (PAL 1: 256 VGA colours, 6 bits a channel).
  * Font: RESOURCE.GFF, FONT 100: the game's 9-pixel font with a shadow.
  * Figures: RESOURCE.GFF, BMP 20000-20013: the full-length figure the
    character creation screen shows for each race and sex (male then female
    for human, dwarf, elf, half-elf, half-giant and halfling; then mul and
    thri-kreen, one each).

Picture chunks ("BMP" in the game's terms): u32 size, u16 frame count, u32
offset of each frame. A frame is u16 width, u16 height, then rows until a
0xFF: u8 y, then the row's spans: u8 x, u8 flags (0x80: the row's last
span), u8 pixel count, u8 byte count, then that many bytes of runs: a byte c,
then (c >> 1) + 1 pixels, as that many literal bytes (c even) or one byte
repeated (c odd). Pixels outside the spans are clear.

Font chunk: u16 character count, u8 height, 6 bytes, a 256-byte character
map, then a u16 offset per character; at each offset u8 width, u8 (0), then
height rows of width bytes: 0 is clear, 254 the letter and 20 its shadow.
"""

import os
import struct
from typing import Dict, List, Optional, Tuple

from .gff import GffError, read_gff

Pixels = List[List[Optional[Tuple[int, int, int]]]]  # rows of RGB, None where clear

FONT_ID = 100
FONT_INK, FONT_SHADOW = 254, 20
PORTRAIT_PALETTE = 1
FIGURE_FIRST = 20000
FIGURE_RACES_WITH_SEXES = 6  # human to halfling have a figure for each sex


def figure_id(race: int, sex: int) -> Optional[int]:
    """The creation screen's figure for a race (1 human ... 8 thri-kreen) and sex (1 male, 2 female)."""
    if 1 <= race <= FIGURE_RACES_WITH_SEXES:
        return FIGURE_FIRST + (race - 1) * 2 + (1 if sex == 2 else 0)
    if race in (7, 8):
        return FIGURE_FIRST + 2 * FIGURE_RACES_WITH_SEXES + (race - 7)
    return None


def _find(folder: str, name: str) -> Optional[str]:
    try:
        for entry in os.listdir(folder):
            if entry.lower() == name.lower():
                return os.path.join(folder, entry)
    except OSError:
        pass
    return None


def decode_frame(chunk: bytes, index: int = 0) -> Tuple[int, int, List[List[Optional[int]]]]:
    """(width, height, rows of palette indexes or None) for one frame of a picture chunk."""
    count, = struct.unpack_from("<H", chunk, 4)
    if not 0 <= index < count:
        raise ValueError(f"no frame {index}")
    offset, = struct.unpack_from("<I", chunk, 6 + 4 * index)
    width, height = struct.unpack_from("<HH", chunk, offset)
    rows: List[List[Optional[int]]] = [[None] * width for _ in range(height)]
    pos = offset + 4
    while pos < len(chunk) and chunk[pos] != 0xFF:
        y = chunk[pos]
        pos += 1
        while True:
            x, flags, _, length = struct.unpack_from("<BBBB", chunk, pos)
            pos += 4
            end, row = pos + length, []
            while pos < end:
                c = chunk[pos]
                n = (c >> 1) + 1
                if c & 1:
                    row += [chunk[pos + 1]] * n
                    pos += 2
                else:
                    row += chunk[pos + 1:pos + 1 + n]
                    pos += 1 + n
            if y < height and x < width:
                row = row[:width - x]
                rows[y][x:x + len(row)] = row
            if flags & 0x80:
                break
    return width, height, rows


def palette_colours(chunk: bytes) -> List[Tuple[int, int, int]]:
    """A VGA palette chunk (6 bits a channel) as 256 RGB colours."""
    scale = lambda v: (v & 0x3F) * 255 // 63
    return [(scale(chunk[i]), scale(chunk[i + 1]), scale(chunk[i + 2])) for i in range(0, 768, 3)]


class Font:
    """The game's bitmap font."""

    def __init__(self, chunk: bytes):
        self.chunk = chunk
        self.height = chunk[2]
        self.offsets = struct.unpack_from("<256H", chunk, 0x108)

    def glyph(self, ch: str) -> Tuple[int, bytes]:
        code = ord(ch) if ord(ch) < 256 else ord("?")
        offset = self.offsets[code]
        width = self.chunk[offset]
        return width, self.chunk[offset + 2:offset + 2 + width * self.height]

    def render(self, text: str, ink: Tuple[int, int, int], shadow: Tuple[int, int, int]) -> Pixels:
        """`text` in the game's font (one line), clear where nothing is drawn."""
        rows: Pixels = [[] for _ in range(self.height)]
        colours = {FONT_INK: ink, FONT_SHADOW: shadow}
        for ch in text:
            width, data = self.glyph(ch)
            for y in range(self.height):
                rows[y] += [colours.get(b) for b in data[y * width:(y + 1) * width]]
        return rows


class GameArt:
    """Portraits and the font from a Shattered Lands install (each piece is None if missing)."""

    def __init__(self, game_dir: Optional[str]):
        self.portraits: Dict[int, bytes] = {}
        self.figures: Dict[int, bytes] = {}
        self.colours: Optional[List[Tuple[int, int, int]]] = None
        self.font: Optional[Font] = None
        self._cache: Dict[Tuple[str, int], Optional[Pixels]] = {}
        if not game_dir:
            return
        for name, load in (("GPLDATA.GFF", self._load_gpl), ("RESOURCE.GFF", self._load_resource)):
            path = _find(game_dir, name)
            if not path:
                continue
            try:
                with open(path, "rb") as f:
                    load(read_gff(f.read()))
            except (OSError, GffError, struct.error, IndexError):
                pass  # an odd install: do without

    def _load_gpl(self, chunks) -> None:
        self.portraits = {cid: data for (kind, cid), data in chunks.items() if kind == "PORT"}
        from . import kalzith  # the companion's own: Kalzith's face, made from one of the game's
        face = kalzith.portrait_chunk(chunks)
        if face:
            self.portraits.setdefault(kalzith.PORTRAIT, face)
        palette = chunks.get(("PAL ", PORTRAIT_PALETTE))
        if palette and len(palette) >= 768:
            self.colours = palette_colours(palette)

    def _load_resource(self, chunks) -> None:
        chunk = chunks.get(("FONT", FONT_ID))
        if chunk and len(chunk) > 0x308:
            self.font = Font(chunk)
        for n in range(FIGURE_FIRST, FIGURE_FIRST + 2 * FIGURE_RACES_WITH_SEXES + 2):
            if ("BMP ", n) in chunks:
                self.figures[n] = chunks[("BMP ", n)]

    def _picture(self, kind: str, number: int, chunks: Dict[int, bytes]) -> Optional[Pixels]:
        key = (kind, number)
        if key not in self._cache:
            pixels = None
            if number in chunks and self.colours:
                try:
                    _, _, rows = decode_frame(chunks[number])
                    pixels = [[None if i is None else self.colours[i] for i in row] for row in rows]
                except (ValueError, struct.error, IndexError):
                    pixels = None
            self._cache[key] = pixels
        return self._cache[key]

    def portrait(self, number: int) -> Optional[Pixels]:
        """Portrait `number` (as the dialogue window names it) in RGB, or None."""
        return self._picture("portrait", number, self.portraits)

    def figure(self, race: int, sex: int) -> Optional[Pixels]:
        """The creation screen's full-length figure for a race and sex, or None."""
        number = figure_id(race, sex)
        return None if number is None else self._picture("figure", number, self.figures)


def photo(master, pixels: Pixels, zoom: int = 1, background: Optional[str] = None):
    """A tk.PhotoImage of `pixels`, `zoom` times its size (whole pixels, so it stays sharp).
    Clear pixels stay transparent, or take `background`."""
    import tkinter as tk
    height = len(pixels)
    width = max((len(r) for r in pixels), default=0)
    image = tk.PhotoImage(master=master, width=max(width, 1), height=max(height, 1))
    rows = []
    for row in pixels:
        cells = [background if c is None else "#%02x%02x%02x" % c for c in row] + [background] * (width - len(row))
        rows.append(cells)
    if background is not None or all(c is not None for row in pixels for c in row):
        image.put(" ".join("{" + " ".join(r) + "}" for r in rows))
    else:
        for y, row in enumerate(rows):  # leave the clear pixels transparent
            x = 0
            while x < width:
                if row[x] is None:
                    x += 1
                    continue
                start = x
                while x < width and row[x] is not None:
                    x += 1
                image.put("{" + " ".join(row[start:x]) + "}", to=(start, y))
    if zoom > 1:
        image = image.zoom(zoom, zoom)
    return image
