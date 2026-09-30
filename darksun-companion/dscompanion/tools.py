"""Thieving tools: an item of the companion's own that picks pockets.

Every thief in the party gets a set, once (in the backpack's first free cell). Picked up on
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
PICTURE, TYPE = 0x8AB0, 60  # a Slavepen key's picture; small things carried (weight 1, worn nowhere)
# a Slavepen key's record, as the game has it, with that name, not in a slot
ITEM = struct.pack("<HH", PICTURE, 0) + bytes.fromhex("0f27" "0100" "0f27") + struct.pack("<H", TYPE) + \
    bytes.fromhex("00000000" "05" "ff") + struct.pack("<Hb", NAME_ENTRY, 0)


def is_tools(rec: bytes) -> bool:
    return len(rec) == game.ITEM_SIZE and struct.unpack_from("<H", rec, game.ITEM_NAME)[0] == NAME_ENTRY \
        and struct.unpack_from("<H", rec, 0)[0] == PICTURE and struct.unpack_from("<H", rec, game.ITEM_TYPE)[0] == TYPE


def give_tools(gd: GameData, given: set) -> List[str]:
    """A set of tools for each thief in the party that hasn't had one (GIVEN: whom, updated)."""
    out = []
    it = ring.Items(gd)
    for member in range(game.PARTY_SIZE):
        rec = gd.creature(member)
        if len(rec) < game.CREATURE_SIZE or not rec[game.CREATURE_NAME]:
            continue
        key = f"{gd.creature_name(0)}|{gd.creature_name(member)}"
        if key in given or gd.thief_skill_parts(member, pickpocket.PICK_POCKETS) is None:
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
        out.append(f"{gd.creature_name(member)} has thieving tools in the backpack (a 'pick' with a key's picture): "
                   "pick them up, take them back to the game and click someone to try their pockets.")
        it = ring.Items(gd)
    return out
