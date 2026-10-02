"""The party's own sprites in the Ledger's SEGOBJEX copy, and dressing them in what they wear."""

import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import art, sprites, spritegear as sg
from test_spriteparts import rows

SWORD, METAL = 63, 4


def game_chunks():
    """A SEGOBJEX's pieces: object 300 the human man, its walking and combat pictures (the test
    figure in each frame), and the cloak's model's."""
    walk = sprites.encode_frames([rows()] * 15)
    fight = sprites.encode_frames([rows()] * 14)
    ojff = bytes(12) + struct.pack("<H", 2095) + b"\0\0"
    return {("OJFF", 300): ojff, ("BMP ", 2095): walk, ("BMP ", 2096): fight,
            ("BMP ", sg.CLOAK_MODEL): walk, ("BMP ", sg.CLOAK_MODEL + 1): fight}


class SpriteTests(unittest.TestCase):
    def test_encode_round_trip(self):
        chunk = sprites.encode_frames([rows(), rows()])
        self.assertEqual(struct.unpack_from("<H", chunk, 4)[0], 2)
        self.assertEqual(art.decode_frame(chunk, 1)[2], rows())

    def test_new_chunks(self):
        """The object points at a pair of its own: the game's frames with room round them, at a
        fixed size with room to spare, its marker at the end."""
        new = sprites.new_chunks(game_chunks())
        walk, fight = sprites.picture_ids(300)
        self.assertEqual((walk, fight), (2450, 2451))
        self.assertEqual(struct.unpack_from("<H", new[("OJFF", 300)], sprites.OJFF_PICTURE)[0], walk)
        chunk = new[("BMP ", walk)]
        self.assertEqual(struct.unpack_from("<I", chunk, 0)[0], len(chunk))
        self.assertTrue(chunk.endswith(sprites.MARKER + bytes([0, 0])))
        self.assertTrue(new[("BMP ", fight)].endswith(sprites.MARKER + bytes([0, 1])))
        self.assertEqual(struct.unpack_from("<H", chunk, 4)[0], 15)
        self.assertEqual(art.decode_frame(chunk, 0)[2], sg.padded(rows(), sprites.PAD))

    def test_dressed_fits(self):
        """A picture in an outfit is the same size as the plain one (it goes where that was)."""
        pics = sprites.Pictures(game_chunks())
        plain = pics.build(300, False, {}, ())
        dressed = pics.build(300, False, {"right": (SWORD, METAL), "cloak": (65, 5), "boots": (68, 5)}, (57,))
        self.assertEqual(len(plain), len(dressed))
        self.assertNotEqual(plain, dressed)
        self.assertNotEqual(art.decode_frame(dressed, 0)[2], art.decode_frame(plain, 0)[2])

    def test_too_big(self):
        with self.assertRaises(ValueError):
            sprites.sized(bytes(100), 50, 300, False)

    def test_written_to_the_copy(self):
        """The Ledger's copy of SEGOBJEX: each picture's place found by its marker, and a dressed
        one written over the plain one there."""
        pics = sprites.Pictures(game_chunks())
        plain = pics.build(300, True, {}, ())
        dressed = pics.build(300, True, {"right": (SWORD, METAL)}, ())
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "SEGOBJEX.GFF")
            with open(path, "wb") as f:
                f.write(b"head" * 10 + plain + b"rest")
            dresser = sprites.Dresser.__new__(sprites.Dresser)
            dresser.copy_file = path
            with open(path, "rb") as f:
                dresser.in_file = sprites.places(f.read())
            self.assertEqual(dresser.in_file, {(300, True): (40, len(plain))})
            dresser._to_file((300, True), dressed)
            data = open(path, "rb").read()
            self.assertEqual(data[40:40 + len(dressed)], dressed)
            self.assertTrue(data.endswith(b"rest"))

    def test_spares(self):
        """A spare pair for each party place, with room for any model, marked after the 14."""
        new = sprites.new_chunks(game_chunks())
        for k, obj in enumerate(sprites.SPARES):
            walk, fight = sprites.picture_ids(obj)
            self.assertEqual(walk, 2478 + 2 * k)
            self.assertTrue(new[("BMP ", walk)].endswith(sprites.MARKER + bytes([14 + k, 0])))
            self.assertTrue(new[("BMP ", fight)].endswith(sprites.MARKER + bytes([14 + k, 1])))
            self.assertNotIn(("OJFF", obj), new)
        pics = sprites.Pictures(game_chunks())
        self.assertEqual(len(pics.build(sprites.SPARES[1], False, {"right": (SWORD, METAL)}, (), 2095)),
                         pics.spare_capacity(False))

    def test_same_figure_a_spare(self):
        """The second member of a figure is dressed in their place's spare pair."""
        dresser = sprites.Dresser.__new__(sprites.Dresser)
        dresser.pics = sprites.Pictures(game_chunks())
        dresser.gd = FakeGame(figures=[0, 0, 0])
        self.assertEqual(dresser.objects(), {300: (0, 300), 315: (1, 300), 316: (2, 300)})

    def test_pointed_at_the_spare(self):
        """On the map: the member's picture named the spare, and their slot moved to it where the
        game has it loaded; the first member left as they were."""
        gd = FakeGame(figures=[0, 0])
        shared, spare = sprites.picture_ids(300), sprites.picture_ids(315)
        gd.cache([shared[0], shared[1], spare[0]])
        gd.entry(0, shared[0], 0)
        gd.entry(1, shared[0], 0)
        dresser = sprites.Dresser.__new__(sprites.Dresser)
        dresser.gd = gd
        self.assertTrue(dresser._point(1, 300, 315))
        self.assertFalse(dresser._point(0, 300, 300))
        self.assertEqual(gd.entry_fields(1), (spare[0], 2))
        self.assertEqual(gd.entry_fields(0), (shared[0], 0))
        gd.entry(1, spare[0], 1)  # (in a fight: the combat picture, the spare's not loaded yet)
        self.assertFalse(dresser._point(1, 300, 315))
        self.assertEqual(gd.entry_fields(1), (spare[0], 1))
        self.assertTrue(dresser._point(1, 300, 300))  # (no longer sharing: back to their own)
        self.assertEqual(gd.entry_fields(1), (shared[0], 1))


class FakeGuest:
    def __init__(self):
        self.mem = bytearray(0x100000)
        self.size = len(self.mem)

    def read(self, at, n):
        return bytes(self.mem[at:at + n])

    def write(self, at, data):
        self.mem[at:at + len(data)] = data


class FakeGame:
    """Party members of these FIGURES, each its own combatant; a picture cache; the map table."""
    def __init__(self, figures):
        self.guest = FakeGuest()
        self.ds, self.load_seg = 0x4000, 0x100
        self.figures = figures

    def creature(self, member):
        rec = bytearray(sprites.game.CREATURE_SIZE)
        if member < len(self.figures):
            rec[sprites.game.CREATURE_NAME] = ord("A")
            struct.pack_into("<H", rec, sprites.CREATURE_FIGURE, self.figures[member])
        return bytes(rec)

    def combatants(self):
        return {c: c for c in range(len(self.figures))}

    def cache(self, pictures):
        self.guest.write(self.ds * 16 + sprites.PICTURE_CACHE_COUNT, struct.pack("<H", len(pictures)))
        for slot, picture in enumerate(pictures):
            self.guest.write((self.load_seg + sprites.PICTURE_CACHE_SEG) * 16 + slot * 16, struct.pack("<H", picture))

    def entry(self, combatant, picture, slot):
        at = self.ds * 16 + sprites.MAP_ENTRIES + combatant * sprites.MAP_ENTRY_SIZE
        self.guest.write(at + sprites.MAP_PICTURE, struct.pack("<H", picture))
        self.guest.write(at + sprites.MAP_SLOT, struct.pack("<H", slot))

    def entry_fields(self, combatant):
        at = self.ds * 16 + sprites.MAP_ENTRIES + combatant * sprites.MAP_ENTRY_SIZE
        return (struct.unpack("<H", self.guest.read(at + sprites.MAP_PICTURE, 2))[0],
                struct.unpack("<H", self.guest.read(at + sprites.MAP_SLOT, 2))[0])


if __name__ == "__main__":
    unittest.main()
