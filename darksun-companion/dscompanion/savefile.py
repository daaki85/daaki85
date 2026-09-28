"""Reading the party from a Shattered Lands save file (SAVEnn.SAV).

The save holds the same structures as memory, so the viewer's layout decodes
it directly. That makes saves a quick way to check a layout without running
the game:
  SAVE chunk 5: the current region's creature table (58-byte records, party first)
  SAVE chunk 6: the party's character sheets (71-byte records)
"""

from .gff import GffError, read_gff
from .layout import Layout

CREATURE_CHUNK = ("SAVE", 5)
SHEET_CHUNK = ("SAVE", 6)


class SaveMemory:
    """The save's creature table and sheet table laid end to end, read like guest memory."""

    def __init__(self, data: bytes):
        self.data = data

    def read(self, addr: int, size: int) -> bytes:
        start = max(addr, 0)
        return self.data[start:max(addr + size, start)]

    def snapshot(self) -> bytes:
        return self.data


def load_party(path: str, layout: Layout) -> SaveMemory:
    """Read a save and point `layout`'s slots at the party records inside it."""
    with open(path, "rb") as f:
        chunks = read_gff(f.read())
    missing = [c for c in (CREATURE_CHUNK, SHEET_CHUNK) if c not in chunks]
    if missing:
        raise GffError(f"{path} has no {' or '.join(f'{t} {i}' for t, i in missing)} chunk; "
                       "is it a Shattered Lands save?")
    mem = SaveMemory(chunks[CREATURE_CHUNK] + chunks[SHEET_CHUNK])

    creature = layout.name_record
    if not creature.stride:
        raise ValueError(f"The layout's {creature.name!r} record needs a stride to read saves")
    for slot in range(layout.count):
        layout.clear_slot(slot)
        base = slot * creature.stride
        name = layout.name.display(mem.read(base, creature.stride), 0)
        if name and name not in ("?", "-"):
            creature.slots[slot] = base
            layout.link_slot(slot, mem.data)
    return mem
