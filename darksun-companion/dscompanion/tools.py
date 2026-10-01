"""Thieving tools: an item of the companion's own that picks pockets.

Every thief starts a new game with a set (in the backpack's first free cell): while the game
is new (its first hour, in the arena where every game starts), any thief in the party without
one gets one. Later on, a thief the Ledger hasn't seen before (an older game, someone who
joins) gets a set once. Picked up on
the inventory screen and taken back to the game, the pointer carries them; clicked on someone,
the patched game's routine for using an item on something (DSCLOG's PROBE_USE_ITEM) has the
Ledger try that person's pockets with the leader's hand (pickpocket.py), and shows what came
of it. The item is a small one of the game's "misc" type, with a key's picture. The game's
name table has no free entry left (the Ring of Protection has the one there was), so it uses
the game's own name "pick" (the pickaxe's), and is told apart by that name, the key's picture
and the type together, which no item of the game's has.
"""

import struct
from typing import List, Optional

from . import game, pickpocket, ring
from .game import GameData

NAME_ENTRY = 0xAD  # "pick"
NEW_GAME = 3600  # game seconds: a game this young, in the arena, has just started
ARENA = 0x2A  # the region every game starts in
PICTURE, TYPE = 0x8AB0, 60  # a Slavepen key's picture; small things carried (weight 1, worn nowhere)
# a Slavepen key's record, as the game has it, with that name, not in a slot
ITEM = struct.pack("<HH", PICTURE, 0) + bytes.fromhex("0f27" "0100" "0f27") + struct.pack("<H", TYPE) + \
    bytes.fromhex("00000000" "05" "ff") + struct.pack("<Hb", NAME_ENTRY, 0)


def is_tools(rec: bytes) -> bool:
    return len(rec) == game.ITEM_SIZE and struct.unpack_from("<H", rec, game.ITEM_NAME)[0] == NAME_ENTRY \
        and struct.unpack_from("<H", rec, 0)[0] == PICTURE and struct.unpack_from("<H", rec, game.ITEM_TYPE)[0] == TYPE


def new_game(gd: GameData) -> bool:
    now = gd.game_time()
    return gd.region() == ARENA and now is not None and now < NEW_GAME


def carries_tools(gd: GameData, it: ring.Items, member: int) -> bool:
    rec = gd.creature(member)
    for offset in game.CREATURE_ITEM_LISTS:
        thing, = struct.unpack_from("<h", rec, offset)
        if any(is_tools(data) for _, data in it.chain(thing)):
            return True
    return False


HELD, HELD_TABLE, HELD_SIZE, HELD_ITEM = 0x17A0, 0x9962, 10, 0x44  # DS: on the inventory
# screen, the item on the pointer (HELD: its number in that table, -1 for none)


def held_tools(gd: GameData, it: ring.Items) -> bool:
    """Tools on the pointer (being moved on the inventory screen: in no one's lists meanwhile)."""
    held, = struct.unpack("<h", gd.guest.read(gd.ds * 16 + HELD, 2))
    if held < 0:
        return False
    item, = struct.unpack("<H", gd.guest.read(gd.ds * 16 + HELD_TABLE + held * HELD_SIZE + HELD_ITEM, 2))
    return item < game.NO_ITEM and is_tools(it.item(item))


def give_tools(gd: GameData, given: set, now: bool = False, session: Optional[set] = None) -> List[str]:
    """A set of tools for each thief in the party that should have one: in a new game (or
    NOW, the Ledger's button), each without a set, but in a new game only once while the
    Ledger runs (SESSION: whom); later, each not given one before (GIVEN: whom). Both are
    updated."""
    fresh = now or new_game(gd)
    session = set() if session is None else session
    out = []
    it = ring.Items(gd)
    if held_tools(gd, it) and not now:
        return []  # someone's being moved: whose isn't known
    for member in range(game.PARTY_SIZE):
        rec = gd.creature(member)
        if len(rec) < game.CREATURE_SIZE or not rec[game.CREATURE_NAME]:
            continue
        key = f"{gd.creature_name(0)}|{gd.creature_name(member)}"
        if gd.thief_skill_parts(member, pickpocket.PICK_POCKETS) is None:
            continue
        if carries_tools(gd, it, member) or (key in given and not fresh) or (key in session and not now):
            given.add(key)
            continue
        cell = pickpocket.free_cell(gd, it, member)
        item = it.word(ring.FREE_ITEMS)
        if cell is None or item >= game.NO_ITEM:
            continue
        gd.guest.write(gd.ds * 16 + ring.FREE_ITEMS, it.item(item)[game.ITEM_NEXT:game.ITEM_NEXT + 2])
        gd.guest.write(it.items + item * game.ITEM_SIZE, ITEM)
        if not pickpocket.give(gd, ring.Items(gd), member, item, cell):
            continue
        given.add(key)
        session.add(key)
        out.append(f"{gd.creature_name(member)} has thieving tools in the backpack (a 'pick' with a key's picture): "
                   "pick them up, take them back to the game and click someone to try their pockets.")
        it = ring.Items(gd)
    return out
