"""Runs DSCLOG's replacement rand() in a CPU emulator (needs `pip install unicorn`).

Checks it returns what Borland's rand() returns, keeps the registers the game
relies on, and records the entries the companion decodes.
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion.dicelog import Entry

try:
    from unicorn import Uc, UC_ARCH_X86, UC_MODE_16
    from unicorn import x86_const as r
except ImportError:  # optional dependency
    Uc = None

EXE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dos", "DSCLOG.EXE")
TSR, GAME_DS, SS, CALLER, PARENT = 0x2000, 0x3000, 0x4000, 0x5000, 0x6000
BP, PARENT_BP = 0x1000, 0x1100


def borland_rand(seed):
    seed = (seed * 0x015A4E35 + 1) & 0xFFFFFFFF
    high = seed >> 16
    return seed, high & 0x7FFF, 0xFFFF if high & 0x8000 else 0


@unittest.skipIf(Uc is None, "unicorn is not installed")
class StubTests(unittest.TestCase):
    def test_matches_borland_rand_and_logs_entries(self):
        with open(EXE, "rb") as f:
            exe = f.read()
        image = exe[struct.unpack_from("<H", exe, 8)[0] * 16:]
        stub, hdr_off = struct.unpack_from("<HH", image, 18)[0], struct.unpack_from("<H", image, 20)[0]
        ring = struct.unpack_from("<H", image, 16)[0]
        self.assertEqual(image[hdr_off:hdr_off + 8], b"DSCLOGv1")

        mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        mu.mem_write(TSR * 16, image)
        mu.mem_write(TSR * 16 + hdr_off + 24, struct.pack("<4H", 0x494A, 0, 0, 0))
        seed = 0x12345678
        mu.mem_write(GAME_DS * 16 + 0x4122, struct.pack("<I", seed))
        mu.mem_write(GAME_DS * 16 + 0x494A, struct.pack("<H", 0xBEEF))
        # the caller's frame: saved BP, return address into PARENT, arguments; its locals below BP
        mu.mem_write(SS * 16 + BP, struct.pack("<HHH", PARENT_BP, 0x40, PARENT) + bytes(range(1, 29)))
        mu.mem_write(SS * 16 + BP - 16, bytes(range(200, 216)))
        mu.mem_write(SS * 16 + PARENT_BP + 0x0A, bytes(range(100, 116)))
        mu.mem_write(PARENT * 16 + 0x40, bytes(range(50, 66)))
        # the caller: CALL FAR stub; then code the log copies
        call = b"\x9a" + struct.pack("<HH", stub, TSR)
        after = bytes(range(0x80, 0x98))
        mu.mem_write(CALLER * 16 + 0x10, call + after)

        for n in range(70):  # more than the ring holds
            mu.reg_write(r.UC_X86_REG_CS, CALLER)
            mu.reg_write(r.UC_X86_REG_DS, GAME_DS)
            mu.reg_write(r.UC_X86_REG_SS, SS)
            mu.reg_write(r.UC_X86_REG_ES, 0x1234)
            mu.reg_write(r.UC_X86_REG_ESP, 0x800)
            mu.reg_write(r.UC_X86_REG_EBP, BP)
            mu.reg_write(r.UC_X86_REG_EAX, 0xAAAA0000 | n)
            mu.reg_write(r.UC_X86_REG_ESI, 0x5151)
            mu.reg_write(r.UC_X86_REG_EDI, 0x7171)
            mu.emu_start(CALLER * 16 + 0x10, CALLER * 16 + 0x10 + len(call))

            seed, value, dx = borland_rand(seed)
            self.assertEqual(mu.reg_read(r.UC_X86_REG_EAX), 0xAAAA0000 | value)
            self.assertEqual(mu.reg_read(r.UC_X86_REG_DX), dx)
            self.assertEqual(struct.unpack("<I", mu.mem_read(GAME_DS * 16 + 0x4122, 4))[0], seed)
            for reg, want in ((r.UC_X86_REG_SI, 0x5151), (r.UC_X86_REG_DI, 0x7171),
                              (r.UC_X86_REG_ES, 0x1234), (r.UC_X86_REG_DS, GAME_DS),
                              (r.UC_X86_REG_BP, BP), (r.UC_X86_REG_SP, 0x800)):
                self.assertEqual(mu.reg_read(reg), want)

            nent = struct.unpack("<H", mu.mem_read(TSR * 16 + hdr_off + 12, 2))[0]
            e = Entry.parse(bytes(mu.mem_read(TSR * 16 + ring + (n % nent) * Entry.SIZE, Entry.SIZE)))
            self.assertEqual((e.seq, e.ip, e.cs, e.raw, e.bp, e.ss, e.ds, e.parent_bp),
                             (n + 1, 0x15, CALLER, value, BP, SS, GAME_DS, PARENT_BP))
            self.assertEqual(e.arg(2), 0x40)
            self.assertEqual(e.frame[4:], bytes(range(1, 29)))
            self.assertEqual(e.parent, bytes(range(100, 116)))
            self.assertEqual(e.glob, (0xBEEF, 0, 0, 0))
            self.assertEqual(e.locals, bytes(range(200, 216)))
            self.assertEqual(e.code, after)
            self.assertEqual(e.parent_code, bytes(range(50, 66)))

        seq, widx, nent = struct.unpack("<HHH", mu.mem_read(TSR * 16 + hdr_off + 8, 6))
        self.assertEqual((seq, widx), (70, 70 % nent))

        def call_with_filters(*filters):
            mu.mem_write(TSR * 16 + hdr_off + 32, struct.pack("<H", len(filters)) + b"".join(filters))
            mu.reg_write(r.UC_X86_REG_CS, CALLER)
            mu.reg_write(r.UC_X86_REG_DS, GAME_DS)
            mu.reg_write(r.UC_X86_REG_SS, SS)
            mu.reg_write(r.UC_X86_REG_ESP, 0x800)
            mu.reg_write(r.UC_X86_REG_EBP, BP)
            mu.emu_start(CALLER * 16 + 0x10, CALLER * 16 + 0x10 + len(call))
            self.assertEqual(mu.reg_read(r.UC_X86_REG_SP), 0x800)
            self.assertEqual(mu.reg_read(r.UC_X86_REG_DS), GAME_DS)
            return struct.unpack("<H", mu.mem_read(TSR * 16 + hdr_off + 8, 2))[0], \
                struct.unpack("<H", mu.mem_read(TSR * 16 + hdr_off + 98, 2))[0]

        # no filter matches: the call is counted as skipped, not recorded, and rand() still works
        self.assertEqual(call_with_filters(b"\x11" * 8, after[:7] + b"\x00"), (70, 1))
        seed, value, _ = borland_rand(seed)
        self.assertEqual(mu.reg_read(r.UC_X86_REG_AX), value)
        # the second filter matches: recorded
        self.assertEqual(call_with_filters(b"\x11" * 8, after[:8]), (71, 1))


if __name__ == "__main__":
    unittest.main()
