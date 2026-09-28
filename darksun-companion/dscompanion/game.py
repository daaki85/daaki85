"""Where Shattered Lands (GOG release, DSUN.EXE) keeps things in memory.

The game is a 16-bit Borland C++ program. Its data segment (DS) starts with
Borland's copyright string at DS:0004, which makes DS easy to find; the
creature and character-sheet tables are reached through far pointers in DS.
"""

import re
import struct
from typing import List, Optional, Tuple

from .guestmem import GuestMemory

CONVENTIONAL_AND_UPPER = 0x110000  # real-mode programs live below this

BORLAND_SIG = b"Borland C++ - Copyright 1991 Borland Intl."
BORLAND_SIG_OFFSET = 4  # the string's offset in DS

CREATURES_PTR = 0x1665  # DS offset of a far pointer to the creature table
SHEETS_PTR = 0x1661  # DS offset of a far pointer to the character sheet table
CREATURE_SIZE = 0x3A
SHEET_SIZE = 0x47
CREATURE_SHEET_INDEX = 0x04
CREATURE_NAME = 0x28
PARTY_SIZE = 4  # the party are the first creatures in the table


def find_data_segment(guest: GuestMemory, low: Optional[bytes] = None) -> Optional[int]:
    """The game's DS, or None if the game isn't running."""
    low = guest.read(0, CONVENTIONAL_AND_UPPER) if low is None else low
    for m in re.finditer(re.escape(BORLAND_SIG), low):
        base = m.start() - BORLAND_SIG_OFFSET
        if base % 16 == 0:
            return base // 16
    return None


def far_pointer(guest: GuestMemory, ds: int, offset: int) -> int:
    off, seg = struct.unpack("<HH", guest.read(ds * 16 + offset, 4))
    return seg * 16 + off


def party_records(guest: GuestMemory, ds: int) -> List[Tuple[Optional[int], Optional[int]]]:
    """(creature record, character sheet) addresses for each party slot."""
    creatures = far_pointer(guest, ds, CREATURES_PTR)
    sheets = far_pointer(guest, ds, SHEETS_PTR)
    result = []
    for slot in range(PARTY_SIZE):
        creature = creatures + slot * CREATURE_SIZE
        record = guest.read(creature, CREATURE_SIZE)
        if len(record) < CREATURE_SIZE or not record[CREATURE_NAME]:
            result.append((None, None))
            continue
        sheet_index = struct.unpack_from("<H", record, CREATURE_SHEET_INDEX)[0]
        result.append((creature, sheets + sheet_index * SHEET_SIZE))
    return result
