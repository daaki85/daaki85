"""Items of the companion's own on people in the slave pens.

- Kurzak, the leader of the guards: a metal Short Sword (a thief can lift it) and a leather Helm.
- Legcrusher, the half-giant monster trainer: Leather Chest Armor +1.
- Pehtucl, the head templar (the Templar in the pens' south-west corner, who carries the
  Obsidian Bloodwrath): a Cloak of Protection +1 (+1 AC, +1 on saves) and a Ring of
  Protection +1 (a thief can lift it).

The game has no short sword, and no cloak whose plus counts, so those two have item types of
the companion's own: DSCLOG adds TYPES after the game's 115 each time it reads its type table
in, as it adds names after its 322 (names.py). The Ledger puts the items among each one's
things once a game (the key in the tools_given set, kept in settings), when the party is in the
pens and the table has DSCLOG's types; the game then keeps and saves them like its own.
"""

import struct
from typing import Dict, List, Optional, Set, Tuple

from . import game, pickpocket, ring
from .game import GameData

REGION = 0x29  # the slave pens
SHORT_SWORD, CLOAK, RING = 0x144, 0x145, 0x146  # name entries DSCLOG adds
# as DSCLOG's EXTRA_NAMES has them. Pehtucl's ring is named as the arena's, in an entry of its own
# so that each keeps its own icon (icons.py)
NAMES = {SHORT_SWORD: b"Short Sword", CLOAK: b"Cloak/Protectn", RING: ring.NAME}
GAME_TYPES, SHORT_SWORD_TYPE, CLOAK_TYPE = game.GAME_TYPES, game.SHORT_SWORD_TYPE, game.CLOAK_TYPE
BONE_HELM_TYPE = game.BONE_HELM_TYPE
TYPES = (  # as DSCLOG's EXTRA_TYPES has them
    bytes.fromhex("010030001e00fa00040501010601000072160001"),  # the metal long sword's (63), 1d6
    bytes.fromhex("000000000a000a00400800000000008" "0ff1f0001"),  # the Cloak's (65): its plus counts for AC
    # the Helm's (5), of bone, worn by those who can wear the bone scale armour (+10h, the classes:
    # 126Fh, no thieves, where the Helm has 166Fh) (bonescale.py)
    bytes.fromhex("000000000f00fa0001060000000000806f120000"),
)
TSR_TYPES_OFF, TSR_TYPES_COUNT, TSR_TYPES_FIRST, TSR_TYPES_PTR = 208, 210, 212, 214
BLOODWRATH = 0x9C  # the name entry of the Templar's sword: which Templar is Pehtucl


ITEM_VALUE = 0x06  # an item's price (a word, in the game's coins)


def _item(template: str, plus: int = 0, type_: Optional[int] = None, name: Optional[int] = None,
          value: Optional[int] = None) -> bytes:
    """An item record from one of the game's templates (SEGOBJEX), in no list and no slot."""
    rec = bytearray.fromhex(template)
    struct.pack_into("<H", rec, game.ITEM_NEXT, game.NO_ITEM)
    struct.pack_into("<H", rec, ring.ITEM_CONTENTS, game.NO_ITEM)
    rec[game.ITEM_SLOT] = 0xFF
    if type_ is not None:
        struct.pack_into("<H", rec, game.ITEM_TYPE, type_)
    if name is not None:
        struct.pack_into("<H", rec, game.ITEM_NAME, name)
    rec[0x0C] = 0  # (the game's cache of the item's picture; the Cloak's template has 35h)
    rec[game.ITEM_PLUS] = plus & 0xFF
    if value is not None:
        struct.pack_into("<H", rec, ITEM_VALUE, value)
    return bytes(rec)


# pictures and the rest from the game's own: the metal long sword, the Helm, Leather Chest
# Armor, the Cloak
SWORD = _item("0afc00000000f40100003f000000000006ff1c0000", type_=SHORT_SWORD_TYPE, name=SHORT_SWORD)
HELM = _item("03fc000000000500000005000000000004ff060000")
# priced as magic items (the templates have the plain ones' 10 and 20: the game's Drake Armor +1 is
# 8000, Silk Armor +2 4000, Chain Chest Armor 1500, its magic rings 30000-50000)
CHEST_ARMOR = _item("02fc000000000a00000006000000000004ff070000", plus=1, value=3000)
CLOAK_ITEM = _item("e3fb000000001400000041003500000003ff0e0000", plus=1, type_=CLOAK_TYPE, name=CLOAK, value=5000)
RING_ITEM = ring.RING[:game.ITEM_NAME] + struct.pack("<H", RING) + ring.RING[game.ITEM_NAME + 2:]
PRICES = ((CHEST_ARMOR, 3000), (CLOAK_ITEM, 5000), (RING_ITEM, ring.VALUE), (ring.RING, ring.VALUE))


def reprice(gd: GameData) -> int:
    """The companion's magic items given before they had these prices (anywhere in the region:
    carried, in a container, on the ground), priced so. How many were."""
    it = ring.Items(gd)
    done = set()
    for thing in range(ring.THING_COUNT):
        for index, rec in it.chain(thing):
            for item, value in PRICES:
                if index not in done and _same(rec, item) and struct.unpack_from("<H", rec, ITEM_VALUE)[0] < value:
                    gd.guest.write(it.items + index * game.ITEM_SIZE + ITEM_VALUE, struct.pack("<H", value))
                    done.add(index)
    return len(done)
# each one's: (item, where it goes: worn in that slot, or None for a backpack cell). Worn
# things go on the body (and still a backpack cell if that slot is taken)
SLOT = {name: game.EQUIP_SLOTS.index(name) for name in ("head", "chest", "cloak")}
ITEMS_FOR: Dict[str, List[Tuple[bytes, Optional[int]]]] = {
    "Kurzak": [(SWORD, None), (HELM, SLOT["head"])],
    "Legcrusher": [(CHEST_ARMOR, SLOT["chest"])],
    "Pehtucl": [(CLOAK_ITEM, SLOT["cloak"]), (RING_ITEM, game.FINGER)],
}


def types_ready(gd: GameData, tsr_hdr) -> bool:
    """The game's type table has DSCLOG's types, numbered from GAME_TYPES."""
    if tsr_hdr is None:
        return False
    first, off, seg = struct.unpack("<HHH", gd.guest.read(tsr_hdr + TSR_TYPES_FIRST, 6))
    return first == GAME_TYPES and seg * 16 + off == game.far_pointer(gd.guest, gd.ds, game.ITEM_TYPES_PTR)


def who(gd: GameData, it: ring.Items, index: int) -> Optional[str]:
    """Which of the three a creature is: by name, and Pehtucl as the Templar carrying the
    Bloodwrath."""
    name = gd.creature_name(index)
    if name in ("Kurzak", "Legcrusher"):
        return name
    if name == "Templar":
        rec = gd.creature(index)
        for offset in game.CREATURE_ITEM_LISTS:
            thing, = struct.unpack_from("<h", rec, offset)
            if any(struct.unpack_from("<H", data, game.ITEM_NAME)[0] == BLOODWRATH for _, data in it.chain(thing)):
                return "Pehtucl"
    return None


def add_to(gd: GameData, creature: int, rec: bytes, slot: Optional[int] = None) -> bool:
    """An item from the game's free list, made `rec`, put first in the creature's (last
    non-empty) item list: worn in `slot` if given and free, else in a backpack cell of its
    own. False if there's nowhere (or no item record) for it."""
    it = ring.Items(gd)
    lists = [struct.unpack_from("<h", gd.creature(creature), o)[0] for o in game.CREATURE_ITEM_LISTS]
    thing = next((t for t in reversed(lists) if 0 <= t < ring.THING_COUNT), None)
    used = {data[game.ITEM_SLOT] for t in lists for _, data in it.chain(t, inside=False)}
    cell = slot if slot is not None and slot not in used else pickpocket.free_cell(gd, it, creature)
    item = it.word(ring.FREE_ITEMS)
    if thing is None or cell is None or item >= game.NO_ITEM:
        return False
    kind, first = it.thing(thing)
    if kind != game.THING_ITEM:
        return False
    gd.guest.write(gd.ds * 16 + ring.FREE_ITEMS, it.item(item)[game.ITEM_NEXT:game.ITEM_NEXT + 2])
    rec = bytearray(rec)
    struct.pack_into("<h", rec, game.ITEM_NEXT, first)
    rec[game.ITEM_SLOT] = cell
    gd.guest.write(it.items + item * game.ITEM_SIZE, bytes(rec))
    gd.guest.write(it.things + thing * 3, struct.pack("<Bh", game.THING_ITEM, item))
    return True


def place(gd: GameData, given: Set[str]) -> List[str]:
    """In the pens, each of the three gets those of their things not yet given this game
    (GIVEN: a key for each, updated)."""
    if gd.region() != REGION:
        return []
    it = ring.Items(gd)
    out = []
    for index in sorted(set(gd.combatants().values())):
        name = who(gd, it, index)
        rec = gd.creature(index)
        if name is None or len(rec) < game.CREATURE_SIZE or struct.unpack_from("<h", rec, 0)[0] <= 0:
            continue
        for item, slot in ITEMS_FOR[name]:
            key = f"{gd.creature_name(0)}|npc:{name}:{struct.unpack_from('<H', item, game.ITEM_NAME)[0]:x}"
            if key in given:
                continue
            if already_there(gd, it, index, item):  # (a game saved after it was given, say)
                given.add(key)
                continue
            if add_to(gd, index, item, slot):
                given.add(key)  # (each once a game, whatever comes of it)
                it = ring.Items(gd)
    return out  # (nothing in the log: the items are there to be found)


def _same(rec: bytes, item: bytes) -> bool:
    """REC is one of the companion's things like ITEM: the same type, name and plus."""
    return len(rec) >= game.ITEM_SIZE and rec[game.ITEM_TYPE:game.ITEM_TYPE + 2] == item[game.ITEM_TYPE:game.ITEM_TYPE + 2] \
        and rec[game.ITEM_NAME:game.ITEM_NAME + 3] == item[game.ITEM_NAME:game.ITEM_NAME + 3]


def already_there(gd: GameData, it: ring.Items, index: int, item: bytes) -> bool:
    """The item is in the game already, so isn't to be given again (the given-once keys live in
    the settings, not in the save: a save from after it was given, loaded where the keys are
    missing, would get a second). The Short Sword, Leather Chest Armor +1, the Cloak and
    Pehtucl's ring are the only ones of their kind: anywhere in the region (carried by the party
    or anyone, in a container, on the ground). The Helm is a common one: on its owner."""
    if item is HELM:
        lists = [struct.unpack_from("<h", gd.creature(index), o)[0] for o in game.CREATURE_ITEM_LISTS]
        return any(_same(rec, item) for t in lists for _, rec in it.chain(t))
    return any(_same(rec, item) for thing in range(ring.THING_COUNT) for _, rec in it.chain(thing))


def label(gd: GameData, rec: bytes) -> str:
    return gd.item_label(rec, gd.item_type_record(rec))
