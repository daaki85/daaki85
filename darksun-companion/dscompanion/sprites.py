"""The party's map sprites with what each character wears (spritegear.py), in the running game.

The party are objects 300-313 (SEGOBJEX's OJFF chunks): object 300 + the figure picked at character
creation (the creature's +18h). An object's word +0Ch names its walking picture (a BMP chunk), its
combat picture the next chunk. In the Ledger's copy of SEGOBJEX (icons.write_objects) each of the
14 objects gets a pair of its own, SPRITE_BASE on: the game's own pictures with room round them
(gear sticks out), in chunks of a fixed size with room to spare, a marker at the end of each.

While the game runs, when a party member's worn items change the Ledger rebuilds their object's
two pictures (the same size) and writes them over the copies the game has loaded (found by the
marker), and marks their things on the map changed (MAP_FLAGS), so the game draws them again at
once.

Two party members of the same race and sex share an object, and the game loads a picture once and
draws everyone with it from the same place in its picture cache. So the copy also has a spare pair
for each party place (SPARES, after the 14), each with room for any model: a member whose figure an
earlier member already has is drawn in the spare pair of their place. Each thing on the map (the
table at MAP_ENTRIES, one entry per combatant) names the picture it is drawn with (+18h, the
walking one; its combat one is the next) and the slot in the game's picture cache it is drawn from
(+0Fh). The Ledger names the member's spare picture there and empties the slot, and the game loads
the picture itself and draws them with it at once. The same puts right a save from before the copy,
whose party still names the game's own pictures.
"""

import struct
from typing import Callable, Dict, List, Optional, Tuple

from . import art, game, spritegear as sg, spriteparts as sp
from .game import GameData

SPRITE_BASE = 2450  # (pairs: object 300's walking picture 2450, its combat one 2451, ...)
PARTY_OBJECTS = range(300, 314)
SPARES = range(314, 314 + game.PARTY_SIZE)  # (each party place's spare pair: 314 + the member)
# Things on the map: 32 bytes each, by combatant; +0Fh the picture-cache slot it is drawn from,
# +18h its walking picture's number
MAP_ENTRIES, MAP_ENTRY_SIZE, MAP_SLOT, MAP_PICTURE = 0x6694, 32, 0x0F, 0x18
# ... and, for the party, where on its picture it stands (+7h half the width, +8h the height, of the
# picture it was made with): ours have PAD more room left, right and above than the game's own
MAP_ANCHOR = 0x07
MAP_FLAGS, MAP_CHANGED = 0x00, 0x01  # (+0: bit 0 marks it changed, for the game to draw again)
# A thing whose slot is NO_SLOT the game gives one as it goes through them (DSUN.EXE 23232h): its
# picture loaded into the cache (the walking one, or the combat one in a fight pose), and drawn
NO_SLOT = 0xFFFF
OJFF_PICTURE = 0x0C
CREATURE_FIGURE = 0x18
PAD = 10
MARKER = b"TLGSPRT"  # (then a byte: the object less 300, then one: 0 walking, 1 combat)
MARKER_SIZE = len(MARKER) + 2

# The slots (game.EQUIP_SLOTS) and what spritegear makes of them
HANDS = {"right hand": "right", "left hand": "left", "missile": "missile", "ammo": "ammo",
         "head": "helm", "cloak": "cloak", "foot": "boots", "waist": "belt"}
ARMOUR_SLOTS = ("chest", "arm", "legs")


def picture_ids(obj: int) -> Tuple[int, int]:
    walk = SPRITE_BASE + 2 * (obj - PARTY_OBJECTS[0])
    return walk, walk + 1


def encode_frames(frames: List[sg.Rows]) -> bytes:
    """A picture chunk of FRAMES (the game's format: art.decode_frame reads it back)."""
    from .icons import encode
    bodies = [encode(f)[10:] for f in frames]
    head = 4 + 2 + 4 * len(bodies)
    offsets, pos = [], head
    for b in bodies:
        offsets.append(pos)
        pos += len(b)
    return struct.pack("<IH", pos, len(bodies)) + b"".join(struct.pack("<I", o) for o in offsets) + b"".join(bodies)


def capacity(frames: List[sg.Rows]) -> int:
    """Room for any outfit on these frames: the plain padded picture's size and three quarters
    more (a full outfit, the bulkiest, adds about a third), and the marker."""
    plain = len(encode_frames([sg.padded(f, PAD) for f in frames]))
    return plain * 7 // 4 + MARKER_SIZE


def sized(chunk: bytes, size: int, obj: int, combat: bool) -> bytes:
    """CHUNK in SIZE bytes: its size word the whole, the room after it, the marker at the end."""
    if len(chunk) + MARKER_SIZE > size:
        raise ValueError("no room")
    tail = MARKER + bytes([obj - PARTY_OBJECTS[0], int(combat)])
    return struct.pack("<I", size) + chunk[4:] + bytes(size - len(chunk) - MARKER_SIZE) + tail


class Pictures:
    """The game's own pictures each party object's are made from, and the template cloak."""

    def __init__(self, chunks):
        self.chunks = chunks
        self.frames: Dict[int, List[sg.Rows]] = {}

    def model(self, obj: int) -> Optional[int]:
        rec = self.chunks.get(("OJFF", obj))
        return struct.unpack_from("<H", rec, OJFF_PICTURE)[0] if rec else None

    def own(self, picture: int) -> List[sg.Rows]:
        if picture not in self.frames:
            d = self.chunks[("BMP ", picture)]
            n, = struct.unpack_from("<H", d, 4)
            self.frames[picture] = [[list(r) for r in art.decode_frame(d, f)[2]] for f in range(n)]
        return self.frames[picture]

    def spare_capacity(self, combat: bool) -> int:
        """A spare picture's size: room for any model's."""
        return max(capacity(self.own(m + combat)) for m in sp.MODELS if ("BMP ", m + combat) in self.chunks)

    def build(self, obj: int, combat: bool, gear: Dict[str, Tuple[int, int]], armour: Tuple[int, ...],
              model: Optional[int] = None) -> bytes:
        """The object's walking (or COMBAT) picture in this outfit, at its fixed size (ValueError
        if it doesn't fit: shown plain instead). A spare (SPARES): MODEL's, at the spare size."""
        model = self.model(obj) if model is None else model
        frames = self.own(model + combat)
        cloaks = self.own(sg.CLOAK_MODEL + combat)
        out = []
        for f, rows in enumerate(frames):
            template = sg.cloak_template(cloaks[f], sg.CLOAK_MODEL, f, combat) if f < len(cloaks) else None
            out.append(sg.armed(rows, model, f, combat, gear, PAD, armour, template))
        size = self.spare_capacity(combat) if obj in SPARES else capacity(frames)
        return sized(encode_frames(out), size, obj, combat)


def new_chunks(chunks) -> Dict[Tuple[str, int], bytes]:
    """For the Ledger's copy of SEGOBJEX: each party object's own pair of pictures (as the game's,
    with room for gear), the object pointing at them."""
    pics = Pictures(chunks)
    out = {}
    for obj in PARTY_OBJECTS:
        if pics.model(obj) is None or pics.model(obj) not in sp.MODELS:
            continue
        walk, fight = picture_ids(obj)
        out[("BMP ", walk)] = pics.build(obj, False, {}, ())
        out[("BMP ", fight)] = pics.build(obj, True, {}, ())
        rec = bytearray(chunks[("OJFF", obj)])
        struct.pack_into("<H", rec, OJFF_PICTURE, walk)
        out[("OJFF", obj)] = bytes(rec)
    spare_model = next((m for m in sorted(sp.MODELS) if ("BMP ", m) in chunks and ("BMP ", m + 1) in chunks), None)
    if spare_model is not None:  # (no object of their own: the Ledger names them on the map)
        for obj in SPARES:
            walk, fight = picture_ids(obj)
            out[("BMP ", walk)] = pics.build(obj, False, {}, (), spare_model)
            out[("BMP ", fight)] = pics.build(obj, True, {}, (), spare_model)
    return out


def worn(gd: GameData, member: int) -> Tuple[Dict[str, Tuple[int, int]], Tuple[int, ...]]:
    """What a party member wears, as spritegear takes it: ({place: (item type, material)}, armour)."""
    gear: Dict[str, Tuple[int, int]] = {}
    armour: List[int] = []
    for _, item, typ in gd._worn(member):
        slot = item[game.ITEM_SLOT]
        if slot >= len(game.EQUIP_SLOTS):
            continue
        name = game.EQUIP_SLOTS[slot]
        kind = struct.unpack_from("<H", item, game.ITEM_TYPE)[0]
        material = typ[0x08] & 0x0F if len(typ) == game.ITEM_TYPE_SIZE else 4
        if name in ARMOUR_SLOTS:
            armour.append(kind)
        elif name in HANDS:
            gear[HANDS[name]] = (kind, material)
    return gear, tuple(sorted(armour))


def places(data: bytes) -> Dict[Tuple[int, bool], Tuple[int, int]]:
    """Where each party object's pictures are in DATA (the Ledger's copy of SEGOBJEX, or the
    game's memory): {(object, combat): (offset, size)}, by the marker at each one's end and the
    size word at its start."""
    out: Dict[Tuple[int, bool], Tuple[int, int]] = {}
    at = data.find(MARKER)
    while at >= 0:
        key = (PARTY_OBJECTS[0] + data[at + len(MARKER)], bool(data[at + len(MARKER) + 1]))
        for size in range(64, 400000):
            start = at + MARKER_SIZE - size
            if start < 0:
                break
            if struct.unpack_from("<I", data, start)[0] == size:
                out[key] = (start, size)
                break
        at = data.find(MARKER, at + 1)
    return out


RESCAN = 10.0  # seconds between looks through the game's memory for copies not yet found
AREA_RESCANS = (0.5, 2.0, 5.0)  # ... and after an area change, these seconds after it


class Dresser:
    """Keeps the party's sprites in the running game dressed in what they wear. The game loads a
    picture again from the file (plain) when it needs it anew (a fight's pictures, an area's), so
    each copy written is checked each time, and memory looked through again for new ones."""

    def __init__(self, gd: GameData, objects_file: str, palette: List[Tuple[int, int, int]],
                 copy_file: Optional[str] = None):
        from .gff import read_gff
        with open(objects_file, "rb") as f:
            self.pics = Pictures(read_gff(f.read()))
        sg.set_palette(palette)
        self.gd = gd
        # the Ledger's copy of SEGOBJEX the game reads (dos\SEGOBJEX.GFF): each picture's place in
        # it, to write it there too, so that the game loads it dressed (a fight's, an area's)
        self.copy_file = copy_file
        self.in_file: Dict[Tuple[int, bool], Tuple[int, int]] = {}  # (object, combat): (offset, size)
        if copy_file:
            try:
                with open(copy_file, "rb") as f:
                    self.in_file = places(f.read())
            except OSError:
                self.in_file = {}
        self.shown: Dict[int, tuple] = {}  # object: the outfit it shows
        self.request_redraw: Optional[Callable[[], None]] = None  # has the view drawn again (DSCLOG)
        self.chunks: Dict[Tuple[int, bool], bytes] = {}  # (object, combat): the picture written
        self.copies: Dict[Tuple[int, bool], List[int]] = {}  # ... and where its copies are
        self._scanned = -RESCAN
        self._rescans: List[float] = []  # (looks through memory soon after an area change)

    def _to_file(self, key: Tuple[int, bool], chunk: bytes) -> None:
        place = self.in_file.get(key)
        if not place or place[1] != len(chunk):
            return
        try:
            with open(self.copy_file, "r+b") as f:
                f.seek(place[0])
                f.write(chunk)
        except OSError:
            pass  # (the copy in memory still dressed; one loaded anew plain)

    @classmethod
    def for_game(cls, gd: GameData, game_dir: Optional[str], copy_file: Optional[str] = None) -> Optional["Dresser"]:
        """A Dresser from the game's own files (the objects and the palette), or None."""
        from .gff import GffError, read_gff
        objects = art._find(game_dir, "SEGOBJEX.GFF") if game_dir else None
        gpl = art._find(game_dir, "GPLDATA.GFF") if game_dir else None
        if not objects or not gpl:
            return None
        try:
            with open(gpl, "rb") as f:
                palette = art.palette_colours(read_gff(f.read())[("PAL ", art.PORTRAIT_PALETTE)])
            return cls(gd, objects, palette, copy_file)
        except (OSError, GffError, KeyError, struct.error, ValueError):
            return None

    def objects(self) -> Dict[int, Tuple[int, int]]:
        """{object: (party member, their figure's object)}: the first member with a figure has its
        object, any other with the same figure the spare of their place."""
        out: Dict[int, Tuple[int, int]] = {}
        for member in range(game.PARTY_SIZE):
            rec = self.gd.creature(member)
            if len(rec) < game.CREATURE_SIZE or not rec[game.CREATURE_NAME]:
                continue
            obj = PARTY_OBJECTS[0] + struct.unpack_from("<H", rec, CREATURE_FIGURE)[0]
            if obj not in PARTY_OBJECTS or self.pics.model(obj) is None:
                continue
            if obj in out and SPARES[0] + member in SPARES:
                out[SPARES[0] + member] = (member, obj)
            else:
                out.setdefault(obj, (member, obj))
        return out

    def _point(self, member: int, figure: int, target: int, redraw: bool = False) -> bool:
        """MEMBER's things on the map drawn with TARGET's pictures (their FIGURE's object's, or
        their place's spare) where they name another of the party's, or the game's own picture of
        the figure (a save from before the copy): the picture named, and the slot emptied, so that
        the game loads it and draws from it at once. Each one changed (or, with REDRAW, each drawn
        with TARGET's) marked to be drawn again."""
        wanted = picture_ids(target)
        model = self.pics.model(figure)
        others = {picture_ids(o)[0] for o in (figure,) + tuple(SPARES) if o != target}
        if model is not None:
            others.add(model)
        moved = False
        for combatant, creature in self.gd.combatants().items():
            if creature != member:
                continue
            at = self.gd.ds * 16 + MAP_ENTRIES + combatant * MAP_ENTRY_SIZE
            picture, = struct.unpack("<H", self.gd.guest.read(at + MAP_PICTURE, 2))
            if redraw and picture == wanted[0]:
                request = getattr(self, "request_redraw", None)
                if request is not None:
                    request()  # (the view drawn again: not marked, as in a fight that
                else:                      #   can set it walking again)
                    self._changed(at)
            if picture in others:
                self.gd.guest.write(at + MAP_PICTURE, struct.pack("<H", wanted[0]))
                self.gd.guest.write(at + MAP_SLOT, struct.pack("<H", NO_SLOT))
                if picture == model:  # (the game's own, smaller: drawn from where ours has room)
                    x, y = struct.unpack("<bb", self.gd.guest.read(at + MAP_ANCHOR, 2))
                    self.gd.guest.write(at + MAP_ANCHOR, struct.pack("<bb", min(127, x + PAD), min(127, y + PAD)))
                self._changed(at)
                moved = True
        return moved

    def _changed(self, at: int) -> None:
        """The thing on the map at AT marked changed: the game gives it its picture (where its slot
        is empty) and draws it again, then clears the mark."""
        flags = self.gd.guest.read(at + MAP_FLAGS, 1)[0]
        self.gd.guest.write(at + MAP_FLAGS, bytes([flags | MAP_CHANGED]))

    def _scan(self) -> None:
        """Where each of the party objects' pictures has a copy in the game's memory (by marker)."""
        mem = self.gd.guest.read(0, self.gd.guest.size)
        self.copies = {}
        at = mem.find(MARKER)
        while at >= 0:  # (a picture can be loaded more than once: each copy)
            for key, (start, _) in places(mem[max(0, at - 400000):at + MARKER_SIZE]).items():
                if mem[at + len(MARKER):at + MARKER_SIZE] == bytes([key[0] - PARTY_OBJECTS[0], key[1]]):
                    self.copies.setdefault(key, []).append(max(0, at - 400000) + start)
            at = mem.find(MARKER, at + 1)

    def _current(self, key: Tuple[int, bool]) -> bool:
        """Each known copy of the picture is the one written."""
        chunk = self.chunks.get(key)
        return chunk is not None and all(self.gd.guest.read(start, len(chunk)) == chunk
                                         for start in self.copies.get(key, []))

    def area_changed(self, now: float) -> None:
        """A new area: its pictures are loaded anew, so memory is looked through for them soon
        (AREA_RESCANS after), not only every RESCAN."""
        self._rescans = [now + after for after in AREA_RESCANS]

    def update(self, on: bool = True, now: float = 0.0) -> List[int]:
        """Each party member's sprites in what they wear (ON; else as the game's own): where it
        has changed, or the game has loaded a picture of theirs anew. The objects written."""
        due = [t for t in self._rescans if t <= now]
        if due:
            self._rescans = [t for t in self._rescans if t > now]
        if due or now - self._scanned >= RESCAN:
            self._scan()
            self._scanned = now
        changed = []
        for obj, (member, figure) in self.objects().items():
            outfit = worn(self.gd, member) if on else ({}, ())
            model = self.pics.model(figure)
            key = (model, repr(sorted(outfit[0].items())), outfit[1])
            fresh = self.shown.get(obj) != key
            wrote = False
            for combat in (False, True):
                pic = (obj, combat)
                if not fresh and self._current(pic):
                    continue
                if fresh or pic not in self.chunks:
                    try:
                        self.chunks[pic] = self.pics.build(obj, combat, outfit[0], outfit[1], model)
                    except ValueError:  # (more than there is room for: plain)
                        self.chunks[pic] = self.pics.build(obj, combat, {}, (), model)
                    self._to_file(pic, self.chunks[pic])
                for start in self.copies.get(pic, []):
                    if struct.unpack("<I", self.gd.guest.read(start, 4))[0] == len(self.chunks[pic]):
                        self.gd.guest.write(start, self.chunks[pic])
                        wrote = True
            self.shown[obj] = key
            if self._point(member, figure, obj, redraw=wrote):
                wrote = True
            if wrote:
                changed.append(obj)
        return changed
