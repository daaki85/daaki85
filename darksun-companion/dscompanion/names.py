"""Names for the companion's own items, past the game's own 322 in its name table.

The game reads its item names (GPLDATA's NAME chunk: 322 of 25 bytes, numbered 0-321) into
memory as it starts and as each game is loaded; an item names its entry by number, and nothing
in the game checks that number against 322. The patched game has DSCLOG reserve room for
NAMES_EXTRA more each time and copy its own names into them (PROBE_NAMES_SIZE and
PROBE_NAMES_FILL), noting where in its header (names_ptr). The companion's items name those
entries (from OWN on: RING, TOOLS), so they take nothing of the game's.

Earlier versions borrowed two of the game's entries instead: one nothing used (the ring's) and
the label of the rest button's icon (the tools'). Their items get today's entries (migrate),
and the entries go back to what the game has there (restore).
"""

import struct

from . import game, npcitems, ring, tools
from .game import GameData

OWN = 0x142  # the game's own names: 0-321
EXTRA = 32  # how many DSCLOG adds (its NAMES_EXTRA)
RING, TOOLS = ring.NAME_ENTRY, tools.NAME_ENTRY  # 0x142, 0x143
NAMES = {RING: ring.NAME, TOOLS: tools.NAME, **npcitems.NAMES}  # as DSCLOG's EXTRA_NAMES has them
TSR_NAMES_OFF, TSR_NAMES_COUNT, TSR_NAMES_PTR = 196, 198, 200  # in DSCLOG's header
# the entries earlier versions borrowed: what the game has there, and what they wrote over it
BORROWED = ((0x95, b"", (b"Ring/Protection", b"Ring +1", b"Ring of Protection")),
            (0x60, b"Rest icon", (b"Thieves' Tools",)))


def table(gd: GameData) -> int:
    return game.far_pointer(gd.guest, gd.ds, game.ITEM_NAMES_PTR)


def ready(gd: GameData, tsr_hdr) -> bool:
    """The game's name table has DSCLOG's names after its own: the one it last read in is
    the one DSCLOG filled (not one it's reading in now, nor a game without DSCLOG's room)."""
    if tsr_hdr is None:
        return False
    off, seg = struct.unpack("<HH", gd.guest.read(tsr_hdr + TSR_NAMES_PTR, 4))
    return (off or seg) != 0 and seg * 16 + off == table(gd)


def restore(gd: GameData) -> None:
    """The entries earlier versions borrowed, back to the game's own (if they hold what those
    versions wrote: anything else is left be)."""
    base = table(gd)
    for entry, own, ours in BORROWED:
        at = base + entry * game.ITEM_NAME_SIZE
        if gd.guest.read(at, game.ITEM_NAME_SIZE).split(b"\0", 1)[0] in ours:
            gd.guest.write(at, own.ljust(game.ITEM_NAME_SIZE, b"\0"))


def migrate(gd: GameData) -> int:
    """Rings and tools named in a borrowed entry (anywhere in the region: carried, in a
    container, on the ground), named in today's. How many were."""
    it = ring.Items(gd)
    old_ring = tuple(entry for entry, own, _ in BORROWED if own == b"")
    done = set()
    for thing in range(ring.THING_COUNT):
        for item, rec in it.chain(thing):
            if item in done:
                continue
            name, = struct.unpack_from("<H", rec, game.ITEM_NAME)
            want = RING if ring.is_ring(rec) and name in old_ring else TOOLS if tools.is_tools(rec) else name
            if want != name:
                it.guest.write(it.items + item * game.ITEM_SIZE + game.ITEM_NAME, struct.pack("<H", want))
                done.add(item)
    return len(done)


def update(gd: GameData, tsr_hdr) -> bool:
    """Once the table has DSCLOG's names: the borrowed entries given back, the items that named
    them moved to today's. True if the companion's items can be named (and given) now."""
    if not ready(gd, tsr_hdr):
        return False
    restore(gd)
    migrate(gd)
    return True
