"""The rest of the bone scale armour, where its chest piece is.

The game has Bone Scale Chest Armor, Arm Armor and Leg Armor (objects 1033-1035, the arm and leg
pieces never placed anywhere in play) but no helm of bone. The first time the Ledger sees the
chest piece in the region (on the ground, in a container, or carried), it puts the arm and leg
pieces and a Bone Helm (an item type of the companion's own: the Helm's, of bone, with an icon
of its own in the bone scale's colours, icons.py) with it: in the same pile or container, or in
the carrier's backpack. Once a game (the key in the tools_given set, kept in settings), and
never where any of the three is already (a save made after they were added).
"""

import struct
from typing import List, Optional, Set

from . import game, npcitems, pickpocket, ring
from .game import GameData

KEY = "bone scale set"
CHEST_PICTURE, CHEST_TYPE = 0xFBF7, 15  # Bone Scale Chest Armor (object 1033)
HELM_NAME = 6  # "Helm" (the game shows the material before it: "Bone Helm")
# the game's own records (SEGOBJEX), in no list and no slot
ARM = npcitems._item("f6fb000000003000000037000000000005ff260100")  # Bone Scale Arm Armor
LEG = npcitems._item("f5fb000000003000000038000000000005ff270100")  # Bone Scale Leg Armor
# the leather Helm's, of the companion's bone helm type (its picture the Helm's until icons.py
# gives it its own)
HELM = npcitems._item("03fc000000000500000005000000000004ff060000", type_=game.BONE_HELM_TYPE, name=HELM_NAME)
PIECES = (ARM, LEG, HELM)


def is_chest(rec: bytes) -> bool:
    return len(rec) >= game.ITEM_SIZE and struct.unpack_from("<HH", rec, 0)[0] == CHEST_PICTURE and \
        struct.unpack_from("<H", rec, game.ITEM_TYPE)[0] == CHEST_TYPE


def is_piece(rec: bytes) -> bool:
    """One of the pieces the Ledger adds (the arm or leg piece, or the Bone Helm)."""
    return len(rec) >= game.ITEM_SIZE and (struct.unpack_from("<H", rec, 0)[0] in (0xFBF6, 0xFBF5) or
                                           struct.unpack_from("<H", rec, game.ITEM_TYPE)[0] == game.BONE_HELM_TYPE)


def find_chest(gd: GameData) -> Optional[int]:
    """The chest piece's item number, wherever it is in the region (a pile, a container, carried),
    or None, also when any of the other pieces is already there (a game saved after they were
    added, loaded again)."""
    it = ring.Items(gd)
    chest = None
    for thing in range(ring.THING_COUNT):
        for item, rec in it.chain(thing):
            if is_piece(rec):
                return None
            if is_chest(rec) and chest is None:
                chest = item
    return chest


def carrier(gd: GameData, it: ring.Items, item: int) -> Optional[int]:
    """The party member carrying the item, if one is."""
    for member in range(game.PARTY_SIZE):
        rec = gd.creature(member)
        if len(rec) < game.CREATURE_SIZE or not rec[game.CREATURE_NAME]:
            continue
        for offset in game.CREATURE_ITEM_LISTS:
            thing, = struct.unpack_from("<h", rec, offset)
            if any(i == item for i, _ in it.chain(thing)):
                return member
    return None


def insert_after(gd: GameData, it: ring.Items, after: int, rec: bytes) -> bool:
    """An item from the game's free list, made REC, put right after item AFTER in its list
    (the same pile or container), in its slot. False if no item record is to be had."""
    item = it.word(ring.FREE_ITEMS)
    if item >= game.NO_ITEM:
        return False
    gd.guest.write(gd.ds * 16 + ring.FREE_ITEMS, it.item(item)[game.ITEM_NEXT:game.ITEM_NEXT + 2])
    before = it.item(after)
    rec = bytearray(rec)
    rec[game.ITEM_NEXT:game.ITEM_NEXT + 2] = before[game.ITEM_NEXT:game.ITEM_NEXT + 2]
    rec[game.ITEM_SLOT] = before[game.ITEM_SLOT]
    gd.guest.write(it.items + item * game.ITEM_SIZE, bytes(rec))
    gd.guest.write(it.items + after * game.ITEM_SIZE + game.ITEM_NEXT, struct.pack("<h", item))
    return True


def place(gd: GameData, given: Set[str]) -> List[str]:
    """The arm and leg pieces and the Bone Helm with the chest piece, once a game (GIVEN: the
    key, added; and never where one of them already is). Nothing for the log."""
    if KEY in given:
        return []
    chest = find_chest(gd)
    if chest is None:
        return []
    it = ring.Items(gd)
    member = carrier(gd, it, chest)
    if member is not None:
        if pickpocket.free_cell(gd, it, member) is None:
            return []  # (no room in the pack: the next time there is)
        placed = [npcitems.add_to(gd, member, rec) for rec in PIECES]
    else:
        placed = [insert_after(gd, ring.Items(gd), chest, rec) for rec in reversed(PIECES)]
    if any(placed):
        given.add(KEY)
    return []  # (nothing in the log: the items are there to be found)
