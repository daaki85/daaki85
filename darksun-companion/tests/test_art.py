"""Decoding the game's picture, palette and font chunks (made-up data in the game's formats)."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import art


def picture(width, height, rows):
    """A one-frame picture chunk; `rows` maps y to its run bytes."""
    body = struct.pack("<HH", width, height)
    for y, data in rows.items():
        body += struct.pack("<HBBB", y, 0x80, width, len(data)) + bytes(data)
    body += b"\xff"
    head = struct.pack("<IHI", 10 + len(body), 1, 10)
    return head + body


class PictureTests(unittest.TestCase):
    def test_runs_and_literals(self):
        # row 0: 3 x colour 7 (c=5: odd, (5>>1)+1 = 3), then 1 literal (c=0): 9
        # row 1: 2 literals (c=2): 1, 2, then 2 x colour 3 (c=3)
        chunk = picture(4, 3, {0: [5, 7, 0, 9], 1: [2, 1, 2, 3, 3]})
        width, height, rows = art.decode_frame(chunk)
        self.assertEqual((width, height), (4, 3))
        self.assertEqual(rows[0], [7, 7, 7, 9])
        self.assertEqual(rows[1], [1, 2, 3, 3])
        self.assertEqual(rows[2], [None] * 4)  # a row the chunk leaves out stays clear

    def test_palette(self):
        pal = bytes([63, 0, 32] + [0] * 765)
        self.assertEqual(art.palette_colours(pal)[0], (255, 0, 129))


class FontTests(unittest.TestCase):
    def test_render(self):
        height = 2
        chunk = bytearray(0x308)
        chunk[0:3] = struct.pack("<HB", 256, height)
        glyph = bytes([2, 0, art.FONT_INK, 0, art.FONT_SHADOW, art.FONT_INK])  # "A": 2 wide
        struct.pack_into("<H", chunk, 0x108 + ord("A") * 2, len(chunk))
        chunk += glyph
        font = art.Font(bytes(chunk))
        ink, shadow = (1, 1, 1), (2, 2, 2)
        self.assertEqual(font.render("AA", ink, shadow), [[ink, None, ink, None], [shadow, ink, shadow, ink]])


class RangedGffTests(unittest.TestCase):
    def test_ranged_ids(self):
        """The resource files list ids as ranges, with the offsets in a GFFI index chunk."""
        from dscompanion.gff import read_gff
        data = bytearray(b"GFFI" + bytes(24))
        chunks = [b"one", b"two", b"three"]
        offsets = []
        for c in chunks:
            offsets.append((len(data), len(c)))
            data += c
        index = struct.pack("<I", 3) + b"".join(struct.pack("<II", o, n) for o, n in offsets)
        index_at = len(data)
        data += index
        toc = len(data)
        struct.pack_into("<I", data, 12, toc)
        data += bytes(8) + struct.pack("<H", 2)
        data += b"GFFI" + struct.pack("<I", 1) + struct.pack("<III", 0, index_at, len(index))
        # ids 5-6 and 20
        data += b"TEXT" + struct.pack("<IIII", 0x80000003, 3, 0, 2) + struct.pack("<IIII", 5, 2, 20, 1)
        got = read_gff(bytes(data))
        self.assertEqual((got[("TEXT", 5)], got[("TEXT", 6)], got[("TEXT", 20)]), tuple(chunks))


class GameArtTests(unittest.TestCase):
    def test_no_install(self):
        missing = art.GameArt(None)
        self.assertIsNone(missing.font)
        self.assertIsNone(missing.portrait(119))


if __name__ == "__main__":
    unittest.main()
