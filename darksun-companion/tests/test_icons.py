"""The companion's item icons: pictures made from the game's own, and SEGOBJEX's copy with them."""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import game, gff, icons, npcitems, ring


def ranged_gff(types):
    """A GFF as the game's resource files are: TYPES {type: {id: chunk}}, each type's ids listed
    as runs and its chunks' places in a GFFI index chunk of its own (numbered in order)."""
    out = bytearray(28)
    gffi, listed = [], []
    for number, (kind, chunks) in enumerate(types.items()):
        table = bytearray(struct.pack("<I", len(chunks)))
        runs = []
        for cid in sorted(chunks):
            table += struct.pack("<II", len(out), len(chunks[cid]))
            out += chunks[cid]
            if runs and runs[-1][0] + runs[-1][1] == cid:
                runs[-1][1] += 1
            else:
                runs.append([cid, 1])
        gffi.append((number, len(out), len(table)))
        out += table
        listed.append((kind, len(chunks), number, runs))
    toc = bytearray(8) + struct.pack("<H", len(listed) + 1)
    toc += struct.pack("<4sI", b"GFFI", len(gffi)) + b"".join(struct.pack("<III", *e) for e in gffi)
    for kind, total, number, runs in listed:
        toc += struct.pack("<4sIIII", kind.encode("latin1"), 0x80000000 | len(runs), total, number, len(runs))
        toc += b"".join(struct.pack("<II", *r) for r in runs)
    struct.pack_into("<I", toc, 4, len(toc) - 2)
    struct.pack_into("<4sIIII", out, 0, b"GFFI", 0x30000, 28, len(out), len(toc))
    return bytes(out + toc + b"trailing bytes the game's file has")


class PictureTests(unittest.TestCase):
    ROWS = [[None, 1, 2, None], [None] * 4, [3] * 4, [None, None, None, 4]]

    def test_round_trip(self):
        chunk = icons.encode(self.ROWS)
        self.assertEqual(icons.decode(chunk), self.ROWS)
        self.assertEqual(struct.unpack_from("<I", chunk, 0)[0], len(chunk))
        self.assertEqual(chunk[-1], 0xFF)

    def test_long_runs(self):
        rows = [list(range(200))]
        self.assertEqual(icons.decode(icons.encode(rows)), rows)

    def test_shorter_blade_centred(self):
        """A diagonal of 12 on 16x16: 4 steps gone, the 8 left centred (4-11 each way)."""
        rows = [[7 if x == y and 2 <= x < 14 else None for x in range(16)] for y in range(16)]
        out = icons.shorter_blade(rows)
        points = [(x, y) for y, r in enumerate(out) for x, p in enumerate(r) if p is not None]
        self.assertEqual(points, [(i, i) for i in range(4, 12)])

    def test_glow(self):
        rows = [[1, 2, None]]
        self.assertEqual(icons.glow(rows, lambda p, x, y: p == 2, icons.FIRE), [[1, icons.FIRE[1], None]])


class CopyTests(unittest.TestCase):
    def setUp(self):
        self.data = ranged_gff({
            "OJFF": {5: b"o5", 6: b"o6", 900: b"o900"},
            "BMP ": {1: b"b1", 2: b"b2", 7: b"b7"},
        })

    def test_added_in_order(self):
        """New ids between and after the old ones: every old chunk where it was, the new ones
        found, the runs sorted by id (the game's lookup needs them so)."""
        added = {("OJFF", 100): b"new100", ("OJFF", 7): b"new7", ("BMP ", 3): b"nb3", ("BMP ", 50): b"nb50"}
        out = icons.with_chunks(self.data, added)
        # appended only: the header's TOC offset and length aside, the file as it was
        self.assertEqual((out[:12], out[20:len(self.data)]), (self.data[:12], self.data[20:]))
        chunks = gff.read_gff(out)
        for key, chunk in {**gff.read_gff(self.data), **added}.items():
            if key[0] != "GFFI":  # (the index chunks grown by the new ones)
                self.assertEqual(chunks[key], chunk)
        toc_offset, toc_length = struct.unpack_from("<II", out, 12)
        self.assertEqual(toc_offset + toc_length, len(out))
        self.assertEqual(struct.unpack_from("<I", out, toc_offset + 4)[0], toc_length - 2)
        pos, runs = toc_offset + 10 + 8 + 2 * 12, {}
        for _ in range(2):
            kind, n, total, _, count = struct.unpack_from("<4sIIII", out, pos)
            runs[kind] = [struct.unpack_from("<II", out, pos + 20 + 8 * i) for i in range(count)]
            pos += 20 + 8 * count
        self.assertEqual(runs[b"OJFF"], [(5, 3), (100, 1), (900, 1)])
        self.assertEqual(runs[b"BMP "], [(1, 3), (7, 1), (50, 1)])

    def test_new_chunks(self):
        """Each icon's object: the plain one's with the new icon named; its map picture the plain
        one's; its icon made from the plain one's."""
        plain = icons.encode([[0x3A if x == y else None for x in range(16)] for y in range(16)])
        chunks = {}
        for _, number, _, _, _ in icons.ICONS:
            base = 0x10000 - number
            chunks[("OJFF", base)] = bytes(12) + struct.pack("<H", 40) + b"rest"
            chunks[("BMP ", base)] = b"map " + bytes([base & 0xFF])
        chunks[("BMP ", 40)] = plain
        new = icons.new_chunks(chunks)
        self.assertEqual(len(new), 3 * len(icons.ICONS))
        for name, number, obj, icon, _ in icons.ICONS:
            self.assertEqual(struct.unpack_from("<H", new[("OJFF", obj)], icons.OJFF_ICON)[0], icon)
            self.assertEqual(new[("BMP ", obj)], chunks[("BMP ", 0x10000 - number)])
            self.assertEqual(icons.PICTURES[name], 0x10000 - obj)
        rings = [{p for r in icons.decode(new[("BMP ", icon)]) for p in r} - {None}
                 for name, _, _, icon, _ in icons.ICONS if "Ring" in name]
        self.assertLessEqual(rings[0], set(icons.VIOLET))  # Pehtucl's
        self.assertLessEqual(rings[1], set(icons.FIRE))  # the arena's
        ids = [k for k in new if k[0] == "BMP "]
        self.assertEqual(len(ids), len(set(ids)))  # no icon numbered as another's map picture


class WhichTests(unittest.TestCase):
    def test_items(self):
        self.assertEqual(icons.which(npcitems.SWORD), "Short Sword")
        self.assertEqual(icons.which(npcitems.CHEST_ARMOR), "Leather Chest Armor +1")
        self.assertEqual(icons.which(npcitems.CLOAK_ITEM), "Cloak of Protection +1")
        self.assertEqual(icons.which(ring.RING), "Ring of Protection +1")
        self.assertEqual(icons.which(npcitems.RING_ITEM), "Pehtucl's Ring of Protection +1")
        self.assertIsNone(icons.which(npcitems.HELM))
        plain = bytearray(npcitems.CHEST_ARMOR)
        plain[game.ITEM_PLUS] = 0
        self.assertIsNone(icons.which(bytes(plain)))

    def test_plain_without_the_copy(self):
        for name, number, _, _, _ in icons.ICONS:
            self.assertEqual(icons.picture(name, False), number)
            self.assertEqual(icons.picture(name, True), icons.PICTURES[name])


if __name__ == "__main__":
    unittest.main()
