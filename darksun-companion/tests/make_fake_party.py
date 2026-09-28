"""Write FAKEPTY.COM, a tiny DOS program for practising with the tools without the game.

It holds two made-up characters in the same shapes Shattered Lands uses (see
layouts/shattered_lands.json): a creature table of 58-byte records and, a
little further on, a table of 71-byte character sheets. The first character
loses 1 HP every second (wrapping from 0 to 255), so you can watch it change.

Run it in DOSBox, open the viewer and search for SADIRA.
"""

import struct
import sys

CREATURE = 0x3A
SHEET = 0x47
CODE_END = 0x10C  # the creature table starts right after the code below
GAP = 0x40  # padding between the two tables, as they are separate arrays in the game


def creature(name: bytes, entity: int, abilities, hp: int, psp: int, thac0: int, sheet: int = 0) -> bytes:
    rec = bytearray(CREATURE)
    struct.pack_into("<hhHH", rec, 0, hp, psp, sheet, entity)
    rec[0x1A], rec[0x1B], rec[0x1F] = 10, 12, thac0
    rec[0x22:0x28] = bytes(abilities)
    rec[0x28:0x28 + len(name)] = name
    return bytes(rec)


def sheet(entity: int, abilities, xp: int, max_hp: int, max_psp: int, race: int,
          classes, levels) -> bytes:
    rec = bytearray(SHEET)
    struct.pack_into("<IIhhh", rec, 0, xp, xp, max_hp, 0, max_psp)
    struct.pack_into("<H", rec, 0x10, entity)
    rec[0x18], rec[0x19] = race, 1
    rec[0x1B:0x21] = bytes(abilities)
    rec[0x21:0x24] = bytes(classes)
    rec[0x24:0x27] = bytes(levels)
    rec[0x37:0x3C] = bytes([13, 15, 14, 16, 16])
    return bytes(rec)


def build() -> bytes:
    hp_addr = CODE_END  # creature 0, offset 0
    code = bytes([
        0xB9, 0x12, 0x00,                 # 100: mov cx, 18      (18 timer ticks ~ 1 s)
        0xF4,                             # 103: hlt
        0xE2, 0xFD,                       # 104: loop 103
        0xFE, 0x0E]) + struct.pack("<H", hp_addr) + bytes([  # 106: dec byte [hp]
        0xEB, 0xF4,                       # 10A: jmp 100
    ])
    assert 0x100 + len(code) == CODE_END
    sadira = [14, 17, 13, 16, 12, 15]
    rikus = [20, 15, 18, 10, 11, 12]
    creatures = (creature(b"SADIRA", 0x8001, sadira, 30, 40, 18, sheet=0)
                 + creature(b"RIKUS", 0x8002, rikus, 52, 20, 17, sheet=1))
    sheets = (sheet(0x8001, sadira, 4500, 30, 44, 3, [11, 0, 0], [4, 0, 0])
              + sheet(0x8002, rikus, 5200, 52, 20, 7, [10, 0, 0], [4, 0, 0]))
    return code + creatures + bytes(GAP) + sheets


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "FAKEPTY.COM"
    with open(out, "wb") as f:
        f.write(build())
    print(f"wrote {out}")
