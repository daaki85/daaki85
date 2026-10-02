"""Inventory icons of the companion's own for its items, made the way the game makes its magic
items' (the Bloodwrath's is the obsidian long sword's with a few pixels in the colours the game
cycles: 240-248, fire): from the plain item's icon.

- the Short Sword: the metal long sword's, its blade four steps shorter, centred;
- Leather Chest Armor +1: the leather's brightest pixels in the fire colours;
- the Cloak of Protection +1: every other pixel of its lightest folds in the violet ones (232-239);
- the Rings of Protection +1: the gold band violet for Pehtucl's, in the fire colours for the
  arena's (the Tied-up Prisoner's), so the two can be told apart.

- the Bone Helm (bonescale.py): the leather Helm's, each shade of leather made the bone scale
  armour's of the same brightness (BONE).

Violet is 35-37 of the palette, which no region changes (232-239, violet in RESOURCE.GFF's
palette, are each region's own: red in the slave pens).

The game reads object pictures from SEGOBJEX.GFF. The game folder is never changed: the launcher
writes a copy of that file next to the patched game (the dos folder, D: in DOSBox) with six
objects added, and DSCLOG has the game open the copy instead (its INT 21h hook, PROBE_DOS_OPEN).
An object (OJFF) is an item's picture number negated; its word +0Ch names its icon (a BMP chunk),
and a BMP chunk of its own number is its picture on the map, here the plain item's.
"""

import os
import struct
from typing import Callable, Dict, List, Optional, Tuple

from . import gff

OBJECTS_FILE = "SEGOBJEX.GFF"
OJFF_ICON = 0x0C  # an object's word naming its icon (BMP chunk)
FIRE = tuple(range(240, 249))  # the colours the game cycles: the Bloodwrath's glow
VIOLET = (37, 36, 35, 36)  # a violet no region changes

Rows = List[List[Optional[int]]]


def decode(chunk: bytes) -> Rows:
    from .art import decode_frame
    return [list(r) for r in decode_frame(chunk)[2]]


def encode(rows: Rows) -> bytes:
    """A one-frame picture chunk, as the game's own: for each row with pixels its y, then its runs
    (x, a last-run flag, the count, the data's length, the data in literal pieces of up to 128),
    then FFh."""
    height, width = len(rows), max((len(r) for r in rows), default=0)
    body = bytearray(struct.pack("<HH", width, height))
    for y, row in enumerate(rows):
        runs, x = [], 0
        while x < len(row):
            if row[x] is None:
                x += 1
                continue
            start = x
            while x < len(row) and row[x] is not None:
                x += 1
            runs.append((start, row[start:x]))
        if runs:
            body.append(y)
        for k, (start, pixels) in enumerate(runs):
            data = bytearray()
            for i in range(0, len(pixels), 128):
                piece = pixels[i:i + 128]
                data += bytes([(len(piece) - 1) << 1]) + bytes(piece)
            body += bytes([start, 0x80 if k == len(runs) - 1 else 0, len(pixels), len(data)]) + data
    body += b"\xff"
    head_size = 4 + 2 + 4
    return struct.pack("<IHI", head_size + len(body), 1, head_size) + bytes(body)


def shorter_blade(rows: Rows, steps: int = 4) -> Rows:
    """A sword drawn from top left to bottom right, its first STEPS diagonal steps of blade gone,
    the rest centred where the whole was."""
    size = len(rows)
    drawn = [(x, y) for y, r in enumerate(rows) for x, p in enumerate(r) if p is not None]
    x0, y0 = min(x for x, _ in drawn), min(y for _, y in drawn)
    cut = [[None if (y < y0 + steps or x < x0 + steps) else p for x, p in enumerate(r)] for y, r in enumerate(rows)]
    points = [(x, y) for y, r in enumerate(cut) for x, p in enumerate(r) if p is not None]
    left, top = min(x for x, _ in points), min(y for _, y in points)
    right, bottom = max(x for x, _ in points), max(y for _, y in points)
    dx, dy = (size - (right - left + 1)) // 2 - left, (size - (bottom - top + 1)) // 2 - top
    out: Rows = [[None] * len(rows[0]) for _ in range(size)]
    for x, y in points:
        out[y + dy][x + dx] = cut[y][x]
    return out


def glow(rows: Rows, which: Callable[[int, int, int], bool], colours: Tuple[int, ...]) -> Rows:
    """Pixels chosen by WHICH(colour, x, y) in colours the game cycles, stepping along them."""
    return [[colours[(x + y) % len(colours)] if p is not None and which(p, x, y) else p
             for x, p in enumerate(r)] for y, r in enumerate(rows)]


# the leather Helm's shades -> the bone scale armour's (its icons' mauves) of the same brightness
BONE = {129: 207, 128: 205, 134: 58, 135: 194, 136: 206, 137: 59, 138: 60, 139: 61, 140: 61}


def recolour(rows: Rows, colours: Dict[int, int]) -> Rows:
    return [[colours.get(p, p) if p is not None else None for p in r] for r in rows]


# (name, the plain item's picture, the new object's number, its icon's number, the icon made from
# the plain one's)
ICONS: Tuple[Tuple[str, int, int, int, Callable[[Rows], Rows]], ...] = (
    ("Short Sword", 0xFC0A, 2427, 2432, shorter_blade),
    ("Leather Chest Armor +1", 0xFC02, 2428, 2433,
     lambda r: glow(r, lambda p, x, y: p in (0x89, 0x8A), FIRE)),
    ("Cloak of Protection +1", 0xFBE3, 2429, 2434,
     lambda r: glow(r, lambda p, x, y: p in (0x8A, 0x8B, 0x8C) and (x + y) % 2 == 0, VIOLET)),
    ("Pehtucl's Ring of Protection +1", 0xFA1C, 2430, 2435, lambda r: glow(r, lambda p, x, y: p == 0x3A, VIOLET)),
    ("Ring of Protection +1", 0xFA1C, 2431, 2436, lambda r: glow(r, lambda p, x, y: p == 0x3A, FIRE)),
    ("Bone Helm", 0xFC03, 2437, 2438, lambda r: recolour(r, BONE)),
)
PICTURES: Dict[str, int] = {name: 0x10000 - number for name, _, number, _, _ in ICONS}  # an item's +0


def new_chunks(chunks: gff.Chunks) -> gff.Chunks:
    """The objects and pictures to add to the game's SEGOBJEX.GFF."""
    out: gff.Chunks = {}
    for _, plain, number, icon, make in ICONS:
        base = 0x10000 - plain
        record = bytearray(chunks[("OJFF", base)])
        old_icon, = struct.unpack_from("<H", record, OJFF_ICON)
        struct.pack_into("<H", record, OJFF_ICON, icon)
        out[("OJFF", number)] = bytes(record)
        out[("BMP ", number)] = chunks[("BMP ", base)]  # its picture on the map: the plain item's
        out[("BMP ", icon)] = encode(make(decode(chunks[("BMP ", old_icon)])))
    return out


def with_chunks(data: bytes, added: gff.Chunks) -> bytes:
    """DATA (a GFF file whose types list their ids as ranges, with their offsets in GFFI index
    chunks, its table of contents last) with ADDED appended: each added chunk, the index chunks
    of their types grown by them, and a new table of contents, the header pointing to it.
    Everything already in the file stays where it was."""
    toc_offset, toc_length = struct.unpack_from("<II", data, 12)
    pos = toc_offset + 8
    count, = struct.unpack_from("<H", data, pos)
    pos += 2
    types = []  # [type, ranged, info]
    for _ in range(count):
        kind, n = struct.unpack_from("<4sI", data, pos)
        pos += 8
        if n & 0x80000000:
            total, index, runs = struct.unpack_from("<III", data, pos)
            pos += 12
            ranges = [list(struct.unpack_from("<II", data, pos + 8 * i)) for i in range(runs)]
            pos += 8 * runs
            types.append([kind, True, [total, index, ranges]])
        else:
            entries = [list(struct.unpack_from("<III", data, pos + 12 * i)) for i in range(n)]
            pos += 12 * n
            types.append([kind, False, entries])
    out = bytearray(data)
    gffi = next(info for kind, ranged, info in types if kind == b"GFFI" and not ranged)
    for kind, ranged, info in types:
        ids = sorted(cid for (k, cid) in added if k.encode("latin1") == kind)
        if not ids:
            continue
        if not ranged:
            raise gff.GffError(f"{kind!r} lists its chunks one by one")
        total, index, ranges = info
        entry = next(e for e in gffi if e[0] == index)
        table = data[entry[1]:entry[1] + entry[2]]
        listed, k = {}, 0  # id: (offset, length), in the order the runs give them
        for first, n in ranges:
            for cid in range(first, first + n):
                listed[cid] = struct.unpack_from("<II", table, 4 + 8 * k)
                k += 1
        for cid in ids:
            chunk = added[(kind.decode("latin1"), cid)]
            listed[cid] = (len(out), len(chunk))
            out += chunk
        # the game looks ids up in runs sorted by id (as the file's own are)
        ranges[:] = []
        new_table = bytearray(struct.pack("<I", len(listed)))
        for cid in sorted(listed):
            if ranges and ranges[-1][0] + ranges[-1][1] == cid:
                ranges[-1][1] += 1
            else:
                ranges.append([cid, 1])
            new_table += struct.pack("<II", *listed[cid])
        info[0] = len(listed)
        entry[1], entry[2] = len(out), len(new_table)
        out += new_table
    toc = bytearray(data[toc_offset:toc_offset + 4]) + bytes(4) + struct.pack("<H", len(types))
    for kind, ranged, info in types:
        if ranged:
            total, index, ranges = info
            toc += struct.pack("<4sIIII", kind, 0x80000000 | len(ranges), total, index, len(ranges))
            for first, n in ranges:
                toc += struct.pack("<II", first, n)
        else:
            toc += struct.pack("<4sI", kind, len(info))
            for cid, offset, length in info:
                toc += struct.pack("<III", cid, offset, length)
    struct.pack_into("<I", toc, 4, len(toc) - 2)  # (as the game's own: the length less 2)
    new_toc = len(out)
    out += toc
    struct.pack_into("<II", out, 12, new_toc, len(toc))
    return bytes(out)


def write_objects(source: str, dest: str) -> None:
    """The game's SEGOBJEX.GFF (SOURCE, only read) with the companion's icons, to DEST."""
    with open(source, "rb") as f:
        data = f.read()
    out = with_chunks(data, new_chunks(gff.read_gff(data)))
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(out)
    os.replace(tmp, dest)


# The companion's items, and the plain pictures they keep in a game that hasn't the copy
TSR_OBJECTS_ON = 218  # in DSCLOG's header: 1 once the game has opened the copy
PICTURE_CACHE = 0x0C  # an item's cache of the picture loaded for it (cleared to load anew)
LEATHER_CHEST_TYPE = 6
PLAIN: Dict[str, int] = {name: plain for name, plain, _, _, _ in ICONS}


def ready(gd, tsr_hdr) -> bool:
    """The game has opened the copy with the icons (DSCLOG says so)."""
    if tsr_hdr is None:
        return False
    return struct.unpack("<H", gd.guest.read(tsr_hdr + TSR_OBJECTS_ON, 2))[0] == 1


def which(rec: bytes) -> Optional[str]:
    """Which of the companion's items an item record is, if one: the Short Sword and the Cloak by
    their types, the rings by their names and plus, Leather Chest Armor +1 by its type and plus."""
    from . import game, npcitems, ring
    if len(rec) < game.ITEM_SIZE:
        return None
    kind, = struct.unpack_from("<H", rec, game.ITEM_TYPE)
    if kind == game.BONE_HELM_TYPE:
        return "Bone Helm"
    plus = struct.unpack("b", rec[game.ITEM_PLUS:game.ITEM_PLUS + 1])[0]
    if kind == game.SHORT_SWORD_TYPE:
        return "Short Sword"
    if kind == game.CLOAK_TYPE:
        return "Cloak of Protection +1"
    if ring.is_ring(rec) and plus == 1:
        name, = struct.unpack_from("<H", rec, game.ITEM_NAME)
        if name == ring.NAME_ENTRY:
            return "Ring of Protection +1"
        if name == npcitems.RING:
            return "Pehtucl's Ring of Protection +1"
    if kind == LEATHER_CHEST_TYPE and plus == 1:
        return "Leather Chest Armor +1"
    return None


def picture(name: str, on: bool) -> int:
    return PICTURES[name] if on else PLAIN[name]


def repaint(gd, on: bool) -> int:
    """The companion's items anywhere in the region (carried, in a container, on the ground) with
    their own icons (ON: the game has the copy), or back to the plain ones (so a game without the
    copy never looks for a picture it hasn't). How many changed."""
    from . import game, ring
    it = ring.Items(gd)
    done = set()
    for thing in range(ring.THING_COUNT):
        for item, rec in it.chain(thing):
            name = which(rec)
            if name is None or item in done:
                continue
            want = picture(name, on)
            if struct.unpack_from("<H", rec, 0)[0] != want:
                at = it.items + item * game.ITEM_SIZE
                gd.guest.write(at, struct.pack("<H", want))
                gd.guest.write(at + PICTURE_CACHE, bytes(4))
                done.add(item)
    return len(done)
