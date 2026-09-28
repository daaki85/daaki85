"""Write FAKEPTY.COM, a tiny DOS program for practising with the tools without the game.

It holds two made-up 0x40-byte character records (name, six ability scores,
HP, max HP) and lowers the first character's HP by one every second.
Run it in DOSBox, then try `find-text SADIRA` and `search u8 30` / `next decreased`.

Record layout (for checking your results):
  +0x00 name (16 bytes)  +0x10..+0x15 STR DEX CON INT WIS CHA
  +0x18 HP (s16)         +0x1A max HP (s16)
"""

import struct
import sys

RECORD = 0x40
DATA = 0x10C  # records start right after the code below


def record(name: bytes, abilities, hp: int) -> bytes:
    rec = bytearray(RECORD)
    rec[:len(name)] = name
    rec[0x10:0x16] = bytes(abilities)
    struct.pack_into("<hh", rec, 0x18, hp, hp)
    return bytes(rec)


def build() -> bytes:
    hp_addr = DATA + 0x18
    code = bytes([
        0xB9, 0x12, 0x00,                 # 100: mov cx, 18      (18 timer ticks ~ 1 s)
        0xF4,                             # 103: hlt
        0xE2, 0xFD,                       # 104: loop 103
        0xFE, 0x0E]) + struct.pack("<H", hp_addr) + bytes([  # 106: dec byte [hp]
        0xEB, 0xF4,                       # 10A: jmp 100
    ])
    assert 0x100 + len(code) == DATA
    return (code + record(b"SADIRA", [14, 17, 13, 16, 12, 15], 30)
            + record(b"RIKUS", [20, 15, 18, 10, 11, 12], 52))


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "FAKEPTY.COM"
    with open(out, "wb") as f:
        f.write(build())
    print(f"wrote {out}")
