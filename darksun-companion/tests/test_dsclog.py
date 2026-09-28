"""Runs DSCLOG's interrupt handlers in a CPU emulator (needs `pip install unicorn`).

Checks its rand() returns what Borland's rand() returns, keeps the registers
the game relies on, and records the entries the companion decodes; and that
the probes do the game instructions they replace.
"""

import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion.dicelog import FILTERS, Entry
from dscompanion.textlog import TextBuffer
from dscompanion.gamepatch import VEC_AC, VEC_MSG, VEC_RAND, VEC_SAVE, VEC_TEXT

try:
    from unicorn import Uc, UC_ARCH_X86, UC_HOOK_INTR, UC_MODE_16
    from unicorn import x86_const as r
except ImportError:  # optional dependency
    Uc = None

EXE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dos", "DSCLOG.EXE")
TSR, GAME_DS, SS, CALLER, PARENT, RAND = 0x2000, 0x3000, 0x4000, 0x5000, 0x6000, 0x7000
IF = 0x200  # the interrupt flag
BP, PARENT_BP = 0x1000, 0x1100


def borland_rand(seed):
    seed = (seed * 0x015A4E35 + 1) & 0xFFFFFFFF
    high = seed >> 16
    return seed, high & 0x7FFF, 0xFFFF if high & 0x8000 else 0


def load_image():
    with open(EXE, "rb") as f:
        exe = f.read()
    return exe[struct.unpack_from("<H", exe, 8)[0] * 16:]


def real_mode_interrupt(mu, intno, _):
    """Unicorn stops at INT; do what a real-mode CPU does: push FLAGS, CS, IP and jump via the IVT."""
    sp, ss = mu.reg_read(r.UC_X86_REG_SP), mu.reg_read(r.UC_X86_REG_SS)
    flags = mu.reg_read(r.UC_X86_REG_EFLAGS) & 0xFFFF
    frame = struct.pack("<HHH", mu.reg_read(r.UC_X86_REG_IP), mu.reg_read(r.UC_X86_REG_CS), flags)
    mu.mem_write(ss * 16 + sp - 6, frame)
    mu.reg_write(r.UC_X86_REG_SP, sp - 6)
    mu.reg_write(r.UC_X86_REG_EFLAGS, flags & ~(IF | 0x100))
    off, seg = struct.unpack("<HH", mu.mem_read(intno * 4, 4))
    mu.reg_write(r.UC_X86_REG_CS, seg)
    mu.reg_write(r.UC_X86_REG_IP, off)


class HeaderTests(unittest.TestCase):
    def test_built_in_filters_match_the_companion(self):
        image = load_image()
        hdr = struct.unpack_from("<H", image, 20)[0]
        self.assertEqual(image[hdr:hdr + 8], b"DSCLOGv6")
        n = struct.unpack_from("<H", image, hdr + 32)[0]
        built_in = tuple(image[hdr + 34 + i * 9 + 1:hdr + 34 + i * 9 + 1 + image[hdr + 34 + i * 9]]
                         for i in range(n))
        self.assertEqual(built_in, FILTERS)
        self.assertEqual(tuple(image[hdr + 112:hdr + 117]), (VEC_RAND, VEC_SAVE, VEC_AC, VEC_TEXT, VEC_MSG))


@unittest.skipIf(Uc is None, "unicorn is not installed")
class StubTests(unittest.TestCase):
    def test_matches_borland_rand_and_logs_entries(self):
        image = load_image()
        hdr_off = struct.unpack_from("<H", image, 20)[0]
        ring = struct.unpack_from("<H", image, 16)[0]
        probe_save, probe_ac = struct.unpack_from("<HH", image, hdr_off + 108)
        int_rand = struct.unpack_from("<H", image, hdr_off + 118)[0]

        mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        mu.mem_write(TSR * 16, image)
        mu.mem_write(TSR * 16 + hdr_off + 32, struct.pack("<H", 0))  # no filters: record every call
        for vec, off in ((VEC_RAND, int_rand), (VEC_SAVE, probe_save), (VEC_AC, probe_ac)):
            mu.mem_write(vec * 4, struct.pack("<HH", off, TSR))
        mu.hook_add(UC_HOOK_INTR, real_mode_interrupt)
        mu.mem_write(TSR * 16 + hdr_off + 24, struct.pack("<4H", 0x494A, 0, 0, 0))
        seed = 0x12345678
        mu.mem_write(GAME_DS * 16 + 0x4122, struct.pack("<I", seed))
        mu.mem_write(GAME_DS * 16 + 0x494A, struct.pack("<H", 0xBEEF))
        # the caller's frame: saved BP, return address into PARENT, arguments; its locals below BP
        mu.mem_write(SS * 16 + BP, struct.pack("<HHH", PARENT_BP, 0x40, PARENT) + bytes(range(1, 29)))
        mu.mem_write(SS * 16 + BP - 16, bytes(range(200, 216)))
        mu.mem_write(SS * 16 + PARENT_BP + 2, bytes(range(100, 132)))
        mu.mem_write(SS * 16 + PARENT_BP - 0x28, bytes(range(150, 190)))
        mu.mem_write(PARENT * 16 + 0x40, bytes(range(50, 66)))
        # the patched rand(): INT VEC_RAND; the caller: CALL FAR rand; then code the log copies
        mu.mem_write(RAND * 16 + 0x822, bytes((0xCD, VEC_RAND, 0x90, 0x90, 0x90)))
        call = b"\x9a" + struct.pack("<HH", 0x822, RAND)
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
            mu.reg_write(r.UC_X86_REG_EFLAGS, IF | 2)
            mu.emu_start(CALLER * 16 + 0x10, CALLER * 16 + 0x10 + len(call))
            self.assertTrue(mu.reg_read(r.UC_X86_REG_EFLAGS) & IF)  # interrupts are back on

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
            self.assertEqual(e.parent, bytes(range(100, 132)))
            self.assertEqual(e.glob, (0xBEEF, 0, 0, 0))
            self.assertEqual(e.locals, bytes(range(200, 216)))
            self.assertEqual(e.code, after)
            self.assertEqual(e.parent_code, bytes(range(50, 66)))
            self.assertEqual(e.parent_locals, bytes(range(150, 190)))

        seq, widx, nent = struct.unpack("<HHH", mu.mem_read(TSR * 16 + hdr_off + 8, 6))
        self.assertEqual((seq, widx), (70, 70 % nent))

        def call_with_filters(*filters):
            packed = b"".join(bytes([len(f)]) + f.ljust(8, b"\0") for f in filters)
            mu.mem_write(TSR * 16 + hdr_off + 32, struct.pack("<H", len(filters)) + packed)
            mu.reg_write(r.UC_X86_REG_CS, CALLER)
            mu.reg_write(r.UC_X86_REG_DS, GAME_DS)
            mu.reg_write(r.UC_X86_REG_SS, SS)
            mu.reg_write(r.UC_X86_REG_ESP, 0x800)
            mu.reg_write(r.UC_X86_REG_EBP, BP)
            mu.emu_start(CALLER * 16 + 0x10, CALLER * 16 + 0x10 + len(call))
            self.assertEqual(mu.reg_read(r.UC_X86_REG_SP), 0x800)
            self.assertEqual(mu.reg_read(r.UC_X86_REG_DS), GAME_DS)
            return struct.unpack("<H", mu.mem_read(TSR * 16 + hdr_off + 8, 2))[0], \
                struct.unpack("<H", mu.mem_read(TSR * 16 + hdr_off + 106, 2))[0]

        # no filter matches: the call is counted as skipped, not recorded, and rand() still works
        self.assertEqual(call_with_filters(b"\x11" * 8, after[:7] + b"\x00"), (70, 1))
        seed, value, _ = borland_rand(seed)
        self.assertEqual(mu.reg_read(r.UC_X86_REG_AX), value)
        # the second filter matches: recorded
        self.assertEqual(call_with_filters(b"\x11" * 8, after[:8]), (71, 1))
        # a shorter filter matches on its own length
        self.assertEqual(call_with_filters(after[:3]), (72, 1))
        self.assertEqual(call_with_filters(after[:2] + b"\x00"), (72, 2))

        call_at = [0x400]

        def run_probe(vector, bp_bytes, si, rest=b"\x90\x90\x90\x90\xf4"):
            mu.mem_write(SS * 16 + BP - 8, bp_bytes)
            code = bytes((0xCD, vector)) + rest
            call_at[0] += 0x10  # fresh code each time: the emulator caches translated code
            at = call_at[0]
            mu.mem_write(CALLER * 16 + at, code)
            # the saving throw's "mov ax, <spell table segment>", where DSUN.EXE has it
            mu.mem_write(CALLER * 16 + at - (0x79BB7 - 0x79A85), struct.pack("<H", 0x3E56))
            mu.reg_write(r.UC_X86_REG_CS, CALLER)
            mu.reg_write(r.UC_X86_REG_DS, GAME_DS)
            mu.reg_write(r.UC_X86_REG_SS, SS)
            mu.reg_write(r.UC_X86_REG_ESP, 0x800)
            mu.reg_write(r.UC_X86_REG_EBP, BP)
            mu.reg_write(r.UC_X86_REG_ESI, si)
            mu.reg_write(r.UC_X86_REG_EBX, 0xB0B0)
            mu.reg_write(r.UC_X86_REG_EAX, 0x12340000)
            mu.reg_write(r.UC_X86_REG_EFLAGS, IF | 2)
            mu.emu_start(CALLER * 16 + at, CALLER * 16 + at + len(code) - 1)
            seq = struct.unpack("<H", mu.mem_read(TSR * 16 + hdr_off + 8, 2))[0]
            nent = struct.unpack("<H", mu.mem_read(TSR * 16 + hdr_off + 12, 2))[0]
            e = Entry.parse(bytes(mu.mem_read(TSR * 16 + ring + ((seq - 1) % nent) * Entry.SIZE, Entry.SIZE)))
            return e

        # the save probe: [bp-2] = total 15, [bp-1] = needs 12 -> CMP leaves carry clear (JAE taken)
        e = run_probe(VEC_SAVE, bytes([0] * 6 + [15, 12]), 0x5151)
        self.assertEqual((e.kind, e.raw & 0xFF, e.raw >> 8, e.bp, e.extra), (1, 15, 12, BP, 0x3E56))
        self.assertTrue(mu.reg_read(r.UC_X86_REG_EFLAGS) & IF)
        self.assertEqual(mu.reg_read(r.UC_X86_REG_AL), 15)
        self.assertFalse(mu.reg_read(r.UC_X86_REG_EFLAGS) & 1)
        self.assertEqual((mu.reg_read(r.UC_X86_REG_SI), mu.reg_read(r.UC_X86_REG_BX)), (0x5151, 0xB0B0))
        self.assertEqual(mu.reg_read(r.UC_X86_REG_SP), 0x800)
        e = run_probe(VEC_SAVE, bytes([0] * 6 + [9, 12]), 0x5151)
        self.assertTrue(mu.reg_read(r.UC_X86_REG_EFLAGS) & 1)  # 9 < 12: carry set, JAE not taken
        # the AC probe: [bp-6] = 7 and SI = -3 -> AX = 4
        e = run_probe(VEC_AC, bytes([0, 0, 7, 0, 0, 0, 0, 0]), 0xFFFD, rest=b"\x90\x90\x90\xf4")
        self.assertEqual((e.kind, e.raw, e.extra), (2, 4, 0))
        self.assertEqual(mu.reg_read(r.UC_X86_REG_AX), 4)
        self.assertEqual((mu.reg_read(r.UC_X86_REG_SI), mu.reg_read(r.UC_X86_REG_BX)), (0xFFFD, 0xB0B0))
        self.assertEqual(mu.reg_read(r.UC_X86_REG_SP), 0x800)


    def test_text_probes_copy_the_text_and_do_the_routines_prologue(self):
        image = load_image()
        hdr_off = struct.unpack_from("<H", image, 20)[0]
        mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        mu.mem_write(TSR * 16, image)
        probe_text, probe_msg = struct.unpack_from("<HH", image, hdr_off + 132)
        for vec, off in ((VEC_TEXT, probe_text), (VEC_MSG, probe_msg)):
            mu.mem_write(vec * 4, struct.pack("<HH", off, TSR))
        mu.hook_add(UC_HOOK_INTR, real_mode_interrupt)
        mu.mem_write(GAME_DS * 16 + 0x100, b"Do not worry, \0")
        mu.mem_write(GAME_DS * 16 + 0x200, b"Long Sword is broken !\0")
        buf = TextBuffer(lambda a, n: bytes(mu.mem_read(a, n)), TSR * 16 + hdr_off)

        def call(vector, args, at):
            # the routine starts with INT (was PUSH BP / MOV BP,SP) then a NOP; its caller's
            # return address and arguments are on the stack
            mu.mem_write(CALLER * 16 + at, bytes((0xCD, vector, 0x90, 0xF4)))
            mu.mem_write(SS * 16 + 0x800, struct.pack("<HH", 0x1234, 0x5678) + args)
            for reg, value in ((r.UC_X86_REG_CS, CALLER), (r.UC_X86_REG_SS, SS), (r.UC_X86_REG_DS, GAME_DS),
                               (r.UC_X86_REG_ESP, 0x800), (r.UC_X86_REG_EBP, BP), (r.UC_X86_REG_ESI, 0x5151),
                               (r.UC_X86_REG_EAX, 0xAAAA), (r.UC_X86_REG_EFLAGS, IF | 2)):
                mu.reg_write(reg, value)
            mu.emu_start(CALLER * 16 + at, CALLER * 16 + at + 3)
            # as if PUSH BP / MOV BP,SP had run
            self.assertEqual(mu.reg_read(r.UC_X86_REG_SP), 0x7FE)
            self.assertEqual(mu.reg_read(r.UC_X86_REG_BP), 0x7FE)
            self.assertEqual(struct.unpack("<H", mu.mem_read(SS * 16 + 0x7FE, 2))[0], BP)
            for reg, want in ((r.UC_X86_REG_SI, 0x5151), (r.UC_X86_REG_AX, 0xAAAA), (r.UC_X86_REG_DS, GAME_DS)):
                self.assertEqual(mu.reg_read(reg), want)
            self.assertTrue(mu.reg_read(r.UC_X86_REG_EFLAGS) & IF)
            return buf.poll()

        recs = call(VEC_TEXT, struct.pack("<HHHH", 1, 0, 0, 119), 0x100)  # a portrait
        self.assertEqual([(x.kind, x.value, x.text) for x in recs], [(1, 119, "")])
        recs = call(VEC_TEXT, struct.pack("<HHHH", 2, 0x100, GAME_DS, 115), 0x110)
        self.assertEqual([(x.kind, x.value, x.text) for x in recs], [(2, 115, "Do not worry, ")])
        recs = call(VEC_MSG, struct.pack("<HH", 0x200, GAME_DS), 0x120)
        self.assertEqual([(x.kind, x.text) for x in recs], [(16, "Long Sword is broken !")])
        # "show the replies" passes no pointer: whatever lies above its arguments is not text
        recs = call(VEC_TEXT, struct.pack("<HHHH", 3, 0x100, GAME_DS, 0), 0x130)
        self.assertEqual([(x.kind, x.text) for x in recs], [(3, "")])


if __name__ == "__main__":
    unittest.main()
