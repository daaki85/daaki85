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

from dscompanion.dicelog import FILTERS, HDR_SIG, Entry
from dscompanion.textlog import TextBuffer
from dscompanion.gamepatch import (VEC_AC, VEC_DOUBLE, VEC_MSG, VEC_NEXT, VEC_RAND, VEC_RING_AC, VEC_USE_ITEM,
                                  VEC_RING_SAVE, VEC_SAVE, VEC_TEXT, VEC_TWO, VEC_GRACE_CAST, VEC_GRACE_EFFECT,
                                  VEC_GRACE_ABILITY, VEC_NAMES_FILL, VEC_NAMES_SIZE, VEC_STEALTH, VEC_TYPES_FILL,
                                  VEC_TYPES_SIZE, VEC_LEVEL, VEC_HD_ROLL, VEC_HD_CON)

try:
    from unicorn import Uc, UC_ARCH_X86, UC_HOOK_INTR, UC_HOOK_MEM_WRITE, UC_MODE_16
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
        self.assertEqual(image[hdr:hdr + 8], HDR_SIG)
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


@unittest.skipIf(Uc is None, "unicorn is not installed")
class NextTests(unittest.TestCase):
    """PROBE_NEXT, in the game's overlaid combat routine: it goes on where the compare and the
    JNE it replaces would have, by way of a frame the overlay manager can fix up while the
    turn's summary is up."""
    DLG = (GAME_DS + 0x42CA - 0x4356) & 0xFFFF  # the dialogue window's overlay stub
    MOVED = (0x7777, 0x0100)  # where the fake overlay manager says the combat routine is now

    def setUp(self):
        image = load_image()
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        mu.mem_write(TSR * 16, image)
        self.hdr = TSR * 16 + image.find(HDR_SIG)
        handler = image.find(bytes.fromhex("fb66600689e3368b4722"))  # sti, pushad, push es, ...
        self.assertGreater(handler, 0)
        mu.mem_write(VEC_NEXT * 4, struct.pack("<HH", handler, TSR))
        mu.hook_add(UC_HOOK_INTR, real_mode_interrupt)
        mu.mem_write(GAME_DS * 16 + 0x4979, struct.pack("<H", 44))  # a monster's turn now
        mu.mem_write(self.DLG * 16 + 0x25, b"\xCB")  # feeding the window: retf
        # waiting for Continue: the combat routine is moved meanwhile, and the overlay manager
        # fixes up the return address in the frame BP points at (push bp / mov bp,sp /
        # mov bx,[bp] / mov word [ss:bx+2],IP / mov word [ss:bx+4],CS / pop bp / retf)
        mu.mem_write(self.DLG * 16 + 0x34, bytes.fromhex("5589e58b5e00") + bytes.fromhex("36c74702") +
                     struct.pack("<H", self.MOVED[1]) + bytes.fromhex("36c74704") +
                     struct.pack("<H", self.MOVED[0]) + bytes.fromhex("5dcb"))

    def run_next(self, local, popups, until):
        """INT VEC_NEXT + 2 NOPs + the game's JNE +5 at CALLER:0600h, [BP-2] = LOCAL."""
        mu = self.mu
        mu.mem_write(CALLER * 16 + 0x600, bytes((0xCD, VEC_NEXT, 0x90, 0x90, 0x75, 0x05)))
        mu.mem_write(SS * 16 + BP - 2, struct.pack("<H", local))
        mu.mem_write(self.hdr + 140, struct.pack("<HH", 1, popups))  # the summary is ready
        msg = TSR * 16 + struct.unpack("<H", mu.mem_read(self.hdr + 144, 2))[0]
        mu.mem_write(msg, b"Slig attacks\0")
        regs = dict(cs=CALLER, ds=GAME_DS, ss=SS, esp=0x800, ebp=BP, eflags=IF | 2, eax=0x1111, ebx=0x2222,
                    ecx=0x3333, edx=0x4444, esi=0x5555, edi=0x6666, es=0x7070)
        for name, value in regs.items():
            mu.reg_write(getattr(r, "UC_X86_REG_" + name.upper()), value)
        mu.emu_start(CALLER * 16 + 0x600, until[0] * 16 + until[1], count=200000)
        self.assertEqual((mu.reg_read(r.UC_X86_REG_CS), mu.reg_read(r.UC_X86_REG_IP)), until)
        kept = [name for name in regs if name not in ("cs", "eflags")]
        self.assertEqual([mu.reg_read(getattr(r, "UC_X86_REG_" + name.upper())) for name in kept],
                         [regs[name] for name in kept])

    def test_no_summary_goes_on_as_the_jump_would(self):
        self.run_next(0, popups=0, until=(CALLER, 0x606))  # [BP-2] = 0: past the JNE
        self.run_next(3, popups=0, until=(CALLER, 0x60B))  # not 0: to its target

    def test_back_where_the_overlay_manager_says(self):
        """The summary shown, the way back is the one the overlay manager left in the frame."""
        self.run_next(3, popups=1, until=self.MOVED)
        self.assertEqual(self.mu.mem_read(self.hdr + 138, 2), struct.pack("<H", 1))  # the turn counted


@unittest.skipIf(Uc is None, "unicorn is not installed")
class UseItemTests(unittest.TestCase):
    """PROBE_USE_ITEM, where the game uses the item on the pointer on what's under it: on as the
    compare and JNE it replaces would go, or, for the Ledger's thieving tools, to the routine's
    end (DSUN.EXE: 7361Ah, 7361Dh and 7371Dh, less the address after the INT)."""
    NONE, SOME, DONE = 0x605, 0x608, 0x602 + 0x106

    def setUp(self):
        image = load_image()
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        mu.mem_write(TSR * 16, image)
        self.hdr = TSR * 16 + image.find(HDR_SIG)
        handler = image.find(bytes.fromhex("fb66600689e3ba0300"))  # sti, pushad, push es, mov bx,sp, mov dx,3
        self.assertGreater(handler, 0)
        mu.mem_write(VEC_USE_ITEM * 4, struct.pack("<HH", handler, TSR))
        mu.hook_add(UC_HOOK_INTR, real_mode_interrupt)
        self.taken = 0

        def companion(uc, access, address, size, value, _):  # answers as soon as it's asked
            if address == self.hdr + 180:
                uc.mem_write(self.hdr + 182, struct.pack("<H", value))
                uc.mem_write(self.hdr + 186, struct.pack("<H", self.taken))
        mu.hook_add(UC_HOOK_MEM_WRITE, companion, begin=self.hdr + 180, end=self.hdr + 181)

    def run_use(self, si, until, on=1):
        mu = self.mu
        mu.mem_write(CALLER * 16 + 0x600, bytes((0xCD, VEC_USE_ITEM, 0x90, 0x90, 0x90)))
        mu.mem_write(self.hdr + 178, struct.pack("<H", on))
        mu.mem_write(TSR * 16 + struct.unpack("<H", mu.mem_read(self.hdr + 176, 2))[0], b"\0")
        for name, value in dict(cs=CALLER, ds=GAME_DS, ss=SS, esp=0x800, ebp=BP, eflags=IF | 2, esi=si).items():
            mu.reg_write(getattr(r, "UC_X86_REG_" + name.upper()), value)
        mu.emu_start(CALLER * 16 + 0x600, CALLER * 16 + until, count=100000)
        self.assertEqual((mu.reg_read(r.UC_X86_REG_IP), mu.reg_read(r.UC_X86_REG_SP), mu.reg_read(r.UC_X86_REG_SI)),
                         (until, 0x800, si))

    def test_nothing_there(self):
        self.run_use(0xFFFF, self.NONE)

    def test_not_ours(self):
        """The Ledger is told what was used on what: the pointer's item 1, item 231 in the
        segment the routine's "mov dx,<segment>" (3FEh past the INT) loads."""
        mu = self.mu
        mu.mem_write(GAME_DS * 16 + 0x17A0, struct.pack("<h", 1))
        mu.mem_write(CALLER * 16 + 0x602 + 0x3FE, struct.pack("<H", 0x9000))
        mu.mem_write(0x9000 * 16 + 1 * 10 + 0x44, struct.pack("<H", 231))
        self.run_use(300, self.SOME, on=0)
        self.run_use(300, self.SOME)  # the Ledger says it's not its tools
        self.assertEqual(struct.unpack("<HH", mu.mem_read(self.hdr + 184, 2) + mu.mem_read(self.hdr + 188, 2)),
                         (300, 231))

    def test_the_tools(self):
        self.taken = 1
        self.run_use(300, self.DONE)


@unittest.skipIf(Uc is None, "unicorn is not installed")
class RingTests(unittest.TestCase):
    """The ring probes: a worn ring's plus counts for AC and (all worn rings) on saves."""
    THINGS_SEG, CREATURES, ITEMS, TYPES = 0x8000, 0x9000, 0xA000, 0xB000

    def setUp(self):
        image = load_image()
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        mu.mem_write(TSR * 16, image)
        # the handlers aren't in the header: find them by their first instructions
        ac = image.find(bytes.fromhex("268a470f98" "83f966"))
        save = image.find(bytes.fromhex("5589e5505351520631f6c45e02"))
        self.assertGreater(min(ac, save), 0)
        mu.mem_write(VEC_RING_AC * 4, struct.pack("<HH", ac, TSR))
        mu.mem_write(VEC_RING_SAVE * 4, struct.pack("<HH", save, TSR))
        mu.hook_add(UC_HOOK_INTR, real_mode_interrupt)
        mu.mem_write(GAME_DS * 16 + 0x1665, struct.pack("<HH", 0, self.CREATURES))
        mu.mem_write(GAME_DS * 16 + 0x165D, struct.pack("<HH", 0, self.ITEMS))
        things = self.THINGS_SEG * 16 + 0xC36
        # object 3: creature 1, whose lists start at objects 10 (item 4, then 5) and 11 (item 7)
        for thing, kind, index in ((3, 2, 1), (10, 1, 4), (11, 1, 7), (12, 1, 5)):
            mu.mem_write(things + thing * 3, struct.pack("<BH", kind, index))
        mu.mem_write(self.CREATURES * 16 + 0x3A + 8, struct.pack("<HHH", 10, 9999, 11))
        # items: type, slot, plus, next
        for item, typ, slot, plus, nxt in ((4, 102, 4, 1, 5), (5, 102, 0xFF, 2, 9999), (7, 102, 4, 2, 9999)):
            rec = bytearray(21)
            struct.pack_into("<H", rec, 4, nxt)
            struct.pack_into("<H", rec, 0x0A, typ)
            rec[0x11], rec[0x14] = slot, plus
            mu.mem_write(self.ITEMS * 16 + item * 21, bytes(rec))
        self.at = 0x600

    def run_at(self, code, **regs):
        mu = self.mu
        self.at += 0x20
        mu.mem_write(CALLER * 16 + self.at, code)
        for name, value in dict(cs=CALLER, ds=GAME_DS, ss=SS, esp=0x800, ebp=BP, eflags=IF | 2, **regs).items():
            mu.reg_write(getattr(r, "UC_X86_REG_" + name.upper()), value)
        mu.emu_start(CALLER * 16 + self.at, CALLER * 16 + self.at + 2)
        self.assertEqual(mu.reg_read(r.UC_X86_REG_SP), 0x800)

    def save(self, thing):
        """INT VEC_RING_SAVE where "xor si,si" was, then the code after it in the game."""
        code = bytes((0xCD, VEC_RING_SAVE)) + bytes.fromhex("8bdf6bdb03b8") + struct.pack("<H", self.THINGS_SEG)
        self.run_at(code, edi=thing, esi=0x5555, eax=0x1111, ebx=0x2222, ecx=0x3333, edx=0x4444, es=0x6666)
        mu = self.mu
        self.assertEqual([mu.reg_read(x) for x in (r.UC_X86_REG_AX, r.UC_X86_REG_BX, r.UC_X86_REG_CX,
                                                   r.UC_X86_REG_DX, r.UC_X86_REG_ES, r.UC_X86_REG_DI,
                                                   r.UC_X86_REG_BP, r.UC_X86_REG_DS)],
                         [0x1111, 0x2222, 0x3333, 0x4444, 0x6666, thing, BP, GAME_DS])
        return mu.reg_read(r.UC_X86_REG_SI)

    def test_saves_count_worn_rings(self):
        self.assertEqual(self.save(3), 3)  # items 4 and 7 (+1, +2); item 5 is only carried

    def test_saves_not_a_creature(self):
        self.assertEqual(self.save(10), 0)

    def test_saves_count_a_cloak_of_protection(self):
        """Item 7 made a cloak of protection (+2, the second of DSCLOG's types) worn on the back:
        counted once the types are in (TYPES_FIRST, the header's +212), with ring 4's +1."""
        mu = self.mu
        rec = self.ITEMS * 16 + 7 * 21
        mu.mem_write(rec + 0x0A, struct.pack("<H", 116))
        mu.mem_write(rec + 0x11, bytes([12]))
        hdr = TSR * 16 + load_image().find(HDR_SIG)
        self.assertEqual(self.save(3), 1)  # no types yet: the ring alone
        mu.mem_write(hdr + 212, struct.pack("<H", 115))
        self.assertEqual(self.save(3), 3)
        mu.mem_write(rec + 0x11, bytes([0xFF]))  # only carried
        self.assertEqual(self.save(3), 1)

    def test_ac_counts_rings(self):
        """AX gets the type's flags (sign-extended); bit 80h is set for the ring type."""
        mu = self.mu
        for typ, flags, want in ((102, 0x00, 0x0080), (6, 0x80, 0xFF80), (6, 0x00, 0), (102, 0x02, 0x0082)):
            mu.mem_write(self.TYPES * 16 + 0x0F, bytes([flags]))
            self.run_at(bytes((0xCD, VEC_RING_AC)), es=self.TYPES, ebx=0, ecx=typ, eax=0x1234)
            self.assertEqual(mu.reg_read(r.UC_X86_REG_AX), want)
            self.assertEqual((mu.reg_read(r.UC_X86_REG_CX), mu.reg_read(r.UC_X86_REG_BX)), (typ, 0))



@unittest.skipIf(Uc is None, "unicorn not installed")
class RuleTests(RingTests):
    """The companion's rule changes: two weapons' to-hit, and the doubled save d20."""
    RULES = 170  # the header's RULES word

    def setUp(self):
        super().setUp()
        image = load_image()
        two = image.find(bytes.fromhex("2ef606") + struct.pack("<H", self.RULES) + bytes([4]))
        double = image.find(bytes.fromhex("2ef606") + struct.pack("<H", self.RULES) + bytes([16]))
        self.assertGreater(min(two, double), 0)
        self.mu.mem_write(VEC_TWO * 4, struct.pack("<HH", two, TSR))
        self.mu.mem_write(VEC_DOUBLE * 4, struct.pack("<HH", double, TSR))

    def rules(self, value):
        self.mu.mem_write(TSR * 16 + self.RULES, struct.pack("<H", value))

    def two(self, dex_adjust, item):
        """INT VEC_TWO with AX the DEX's initiative adjustment, [BP+0Ah] the attack's item and
        CX the attacker's object (3: creature 1): the adjustment in DX."""
        self.mu.mem_write(SS * 16 + BP + 0x0A, struct.pack("<H", item))
        self.run_at(bytes((0xCD, VEC_TWO)), eax=dex_adjust & 0xFFFF, ebx=0x2222, ecx=3, es=0x6666)
        self.assertEqual([self.mu.reg_read(x) for x in (r.UC_X86_REG_BX, r.UC_X86_REG_CX, r.UC_X86_REG_ES)],
                         [0x2222, 3, 0x6666])
        return struct.unpack("<h", struct.pack("<H", self.mu.reg_read(r.UC_X86_REG_DX)))[0]

    def hands(self, right=(81, 3), left=(81, 10)):
        """Creature 1's items 4 and 7 as (type, slot); type 81 is a melee weapon (class 1),
        type 90 a shield (class 0)."""
        self.mu.mem_write(GAME_DS * 16 + 0x1669, struct.pack("<HH", 0, self.TYPES))
        things = (GAME_DS + 0x3972 - 0x4356) * 16 + 0xC36  # where the game keeps them, from DS
        for thing, kind, index in ((3, 2, 1), (10, 1, 4), (11, 1, 7), (12, 1, 5)):
            self.mu.mem_write(things + thing * 3, struct.pack("<BH", kind, index))
        for typ, cls in ((81, 1), (90, 0), (60, 2)):
            self.mu.mem_write(self.TYPES * 16 + typ * 0x14 + 0x0A, bytes([cls]))
        for item, (typ, slot) in ((4, right), (7, left)):
            rec = bytearray(self.mu.mem_read(self.ITEMS * 16 + item * 21, 21))
            struct.pack_into("<H", rec, 0x0A, typ)
            rec[0x11] = slot
            self.mu.mem_write(self.ITEMS * 16 + item * 21, bytes(rec))

    def test_two_weapons_the_games(self):
        self.rules(0)
        self.hands()
        self.assertEqual([self.two(adj, 4) for adj in (-6, -1, 0, 3)], [6, 1, 0, 0])

    def test_two_weapons_adnd(self):
        """A weapon in each hand: item 4 in the right (main), item 7 in the left (off)."""
        self.rules(4)
        self.hands()
        self.assertEqual([self.two(adj, 4) for adj in (-3, 0, 1, 2, 5)], [-5, -2, -1, 0, 0])
        self.assertEqual([self.two(adj, 7) for adj in (-3, 0, 2, 3, 4, 5)], [-7, -4, -2, -1, 0, 0])

    def test_one_weapon_no_penalty(self):
        """A shield in the other hand, a bow in the missile slot, or the weapon not in a hand:
        no penalty, whatever the DEX."""
        self.rules(4)
        for right, left in (((81, 3), (90, 10)), ((81, 3), (60, 2)), ((81, 3), (81, 0xFF)), ((81, 2), (81, 10))):
            self.hands(right, left)
            self.assertEqual([self.two(adj, 4) for adj in (-3, 0)], [0, 0], (right, left))

    def test_doubled_save(self):
        for rules, want in ((0, 14), (16, 7)):
            self.rules(rules)
            self.run_at(bytes((0xCD, VEC_DOUBLE)), eax=7)
            self.assertEqual(self.mu.reg_read(r.UC_X86_REG_AL), want)

    def level(self, level):
        """INT VEC_LEVEL with ES:BX a sheet whose class level (+24h) is LEVEL: (below the cap,
        at it), from the flags the game's JL and JZ read; AX and interrupts as they were."""
        image = load_image()
        probe = image.find(bytes.fromhex("fb50b0092ef606") + struct.pack("<H", self.RULES) + bytes([128]))
        self.assertGreater(probe, 0)
        self.mu.mem_write(VEC_LEVEL * 4, struct.pack("<HH", probe, TSR))
        self.mu.mem_write(self.TYPES * 16 + 0x100 + 0x24, bytes([level]))
        self.run_at(bytes((0xCD, VEC_LEVEL)), es=self.TYPES, ebx=0x100, eax=0x1234)
        flags = self.mu.reg_read(r.UC_X86_REG_EFLAGS)
        self.assertEqual((self.mu.reg_read(r.UC_X86_REG_AX), bool(flags & IF)), (0x1234, True))
        return bool(flags & 0x80) != bool(flags & 0x800), bool(flags & 0x40)

    def test_level_cap(self):
        """The game's cap of 9, or 10 with rule 128."""
        self.rules(0)
        self.assertEqual([self.level(n) for n in (1, 8, 9, 10)],
                         [(True, False), (True, False), (False, True), (False, False)])
        self.rules(128)
        self.assertEqual([self.level(n) for n in (8, 9, 10, 11)],
                         [(True, False), (True, False), (False, True), (False, False)])

    def hit_dice(self, cls, levels=9):
        """INT VEC_HD_ROLL with ES:BX a hit point group whose dice go up to LEVELS and the
        game's [BP+8] the class: the levels that roll dice, in AL."""
        image = load_image()
        probe = image.find(bytes.fromhex("268a4701") + bytes.fromhex("2ef606") + struct.pack("<H", self.RULES))
        self.assertGreater(probe, 0)
        self.mu.mem_write(VEC_HD_ROLL * 4, struct.pack("<HH", probe, TSR))
        self.mu.mem_write(self.TYPES * 16 + 0x200, bytes([6, levels, 2, 6]))
        self.mu.mem_write(SS * 16 + BP + 8, struct.pack("<H", cls))
        self.run_at(bytes((0xCD, VEC_HD_ROLL)), es=self.TYPES, ebx=0x200, eax=0x1200)
        self.assertEqual(self.mu.reg_read(r.UC_X86_REG_AH), 0x12)
        return self.mu.reg_read(r.UC_X86_REG_AL)

    def test_thief_hit_dice(self):
        """A thief (17) rolls up to 10th with rule 128; a psionicist (12) still stops at 9th."""
        self.rules(0)
        self.assertEqual([self.hit_dice(c) for c in (17, 12)], [9, 9])
        self.rules(128)
        self.assertEqual([self.hit_dice(c) for c in (17, 12)], [10, 9])
        self.assertEqual(self.hit_dice(17, levels=10), 10)  # (a preserver's group: as it was)

    def con_levels(self, cls, level):
        """INT VEC_HD_CON with AL a class's level, ES:BX its group (dice up to 9), the game's
        [BP-4] a sheet whose second class (CX = 1) is CLS: whether the level is past the cap
        (the game's JNG not taken); DX and the sheet's ES:BX as they were."""
        image = load_image()
        probe = image.find(bytes.fromhex("fb52268a5701"))
        self.assertGreater(probe, 0)
        self.mu.mem_write(VEC_HD_CON * 4, struct.pack("<HH", probe, TSR))
        self.mu.mem_write(self.TYPES * 16 + 0x200, bytes([6, 9, 2, 6]))
        self.mu.mem_write(self.CREATURES * 16 + 0x300 + 0x21, bytes([12, cls, 0]))
        self.mu.mem_write(SS * 16 + BP - 4, struct.pack("<HH", 0x300, self.CREATURES))
        self.run_at(bytes((0xCD, VEC_HD_CON)), es=self.TYPES, ebx=0x200, ecx=1, edx=0x5555, eax=level)
        mu = self.mu
        self.assertEqual([mu.reg_read(x) for x in (r.UC_X86_REG_DX, r.UC_X86_REG_ES, r.UC_X86_REG_BX)],
                         [0x5555, self.TYPES, 0x200])
        flags = mu.reg_read(r.UC_X86_REG_EFLAGS)
        return not (flags & 0x40 or bool(flags & 0x80) != bool(flags & 0x800))

    def test_thief_con_levels(self):
        self.rules(0)
        self.assertEqual([self.con_levels(17, n) for n in (9, 10)], [False, True])
        self.rules(128)
        self.assertEqual([self.con_levels(c, n) for c, n in ((17, 9), (17, 10), (12, 10))], [False, False, True])



@unittest.skipIf(Uc is None, "unicorn not installed")
class GraceTests(RuleTests):
    """Cat's Grace (spell 14, rule 32): Strength's code, its own effect (54), DEX."""

    def setUp(self):
        super().setUp()
        image = load_image()
        for vector, start in ((VEC_GRACE_CAST, "8b460e2ef606aa0020"), (VEC_GRACE_EFFECT, "c746ec4300817e0e9400"),
                              (VEC_GRACE_ABILITY, "8946f6b90700")):
            at = image.find(bytes.fromhex(start))
            self.assertGreater(at, 0)
            self.mu.mem_write(vector * 4, struct.pack("<HH", at, TSR))

    def word(self, offset, value=None):
        at = SS * 16 + (BP + offset) % 0x10000
        if value is not None:
            self.mu.mem_write(at, struct.pack("<h", value))
        return struct.unpack("<h", self.mu.mem_read(at, 2))[0]

    def test_cast_goes_to_strength(self):
        for rules, spell, want in ((32, 14, 23), (0, 14, 14), (32, 20, 20), (32, 23, 23)):
            self.rules(rules)
            self.word(0x0E, spell)
            self.run_at(bytes((0xCD, VEC_GRACE_CAST)))
            self.assertEqual((self.word(-0x1A), self.mu.reg_read(r.UC_X86_REG_AX)), (want, spell if want == spell else 23))

    def test_its_own_effect(self):
        for rules, spell, want in ((32, 14, 54), (0, 14, 0x43), (32, 23, 0x43), (32, 0x94, 0x42), (0, 0x94, 0x42)):
            self.rules(rules)
            self.word(0x0E, spell)
            self.run_at(bytes((0xCD, VEC_GRACE_EFFECT)))
            self.assertEqual(self.word(-0x14), want, (rules, spell))

    def test_adds_to_dex(self):
        effects = 0x9800
        self.mu.mem_write(effects * 16 + 0x10F, bytes([5]))
        for effect, dex, want in ((54, 15, 20), (54, 21, 24), (67, 15, 15)):
            self.word(-0x340, dex)
            self.word(-0x342, 18)  # STR, untouched
            self.run_at(bytes((0xCD, VEC_GRACE_ABILITY)), eax=effect, ebx=0, es=effects, ecx=0)
            self.assertEqual((self.word(-0x340), self.word(-0x342), self.word(-0x0A)), (want, 18, effect))
            self.assertEqual(self.mu.reg_read(r.UC_X86_REG_CX), 7)


@unittest.skipIf(Uc is None, "unicorn not installed")
class NamesTests(unittest.TestCase):
    """The game's name table: room for NAMES_EXTRA more names, and DSCLOG's copied in."""
    NAMES_SEG = 0x5000

    def setUp(self):
        self.image = image = load_image()
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        mu.mem_write(TSR * 16, image)
        size = image.find(bytes.fromhex("8146fc2003" "8356fe00"))
        fill = image.find(bytes.fromhex("83c40c" "2eff36")) - 15
        self.assertGreater(min(size, fill), 0)
        mu.mem_write(VEC_NAMES_SIZE * 4, struct.pack("<HH", size, TSR))
        mu.mem_write(VEC_NAMES_FILL * 4, struct.pack("<HH", fill, TSR))
        mu.hook_add(UC_HOOK_INTR, real_mode_interrupt)
        mu.mem_write(GAME_DS * 16 + 0x166D, struct.pack("<HH", 4, self.NAMES_SEG))
        self.hdr = TSR * 16 + image.find(HDR_SIG)

    def interrupt(self, vector, **regs):
        mu = self.mu
        mu.mem_write(CALLER * 16 + 0x600, bytes((0xCD, vector, 0x90)))
        for name, value in dict(cs=CALLER, ds=GAME_DS, ss=SS, esp=0x800, ebp=BP, eflags=IF | 2, **regs).items():
            mu.reg_write(getattr(r, "UC_X86_REG_" + name.upper()), value)
        mu.emu_start(CALLER * 16 + 0x600, CALLER * 16 + 0x602)
        return mu.reg_read(r.UC_X86_REG_SP)

    def test_room(self):
        """In place of "push dword 1": the chunk's size (the dword at [BP-4]) gets the room."""
        for size, want in ((8050, 8850), (0xFF00, 0xFF00 + 800)):
            self.mu.mem_write(SS * 16 + BP - 4, struct.pack("<I", size))
            self.assertEqual(self.interrupt(VEC_NAMES_SIZE), 0x7FC)
            self.assertEqual(struct.unpack("<II", self.mu.mem_read(SS * 16 + 0x7FC, 4) +
                                           self.mu.mem_read(SS * 16 + BP - 4, 4)), (1, want))

    def test_filled(self):
        """In place of "add sp,0Ch": with the chunk read (AX 0), DSCLOG's names after the game's."""
        names = self.NAMES_SEG * 16 + 4 + 0x142 * 25
        self.assertEqual(self.interrupt(VEC_NAMES_FILL, eax=0), 0x80C)
        self.assertEqual(bytes(self.mu.mem_read(names, 50)),
                         b"Ring/Protection".ljust(25, b"\0") + b"Thieves' Tools".ljust(25, b"\0"))
        self.assertEqual(struct.unpack("<HH", self.mu.mem_read(self.hdr + 200, 4)), (4, self.NAMES_SEG))
        self.assertEqual([self.mu.reg_read(x) for x in (r.UC_X86_REG_AX, r.UC_X86_REG_DS, r.UC_X86_REG_BP)],
                         [0, GAME_DS, BP])

    def test_not_read(self):
        self.assertEqual(self.interrupt(VEC_NAMES_FILL, eax=1), 0x80C)
        self.assertEqual(bytes(self.mu.mem_read(self.NAMES_SEG * 16 + 4 + 0x142 * 25, 4)), bytes(4))
        self.assertEqual(bytes(self.mu.mem_read(self.hdr + 200, 4)), bytes(4))
        self.assertEqual(self.mu.reg_read(r.UC_X86_REG_AX), 1)


@unittest.skipIf(Uc is None, "unicorn not installed")
class StealthTests(unittest.TestCase):
    """A hidden thief's attack (RULE_STEALTH, 64): from behind, a backstab when it can be."""
    SHEETS, TYPES = 0x8000, 0x9000

    def setUp(self):
        self.image = image = load_image()
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        mu.mem_write(TSR * 16, image)
        self.hdr = TSR * 16 + image.find(HDR_SIG)
        at = image.find(bytes.fromhex("2ef606") + struct.pack("<H", 170) + bytes([64]))
        self.assertGreater(at, 0)
        mu.mem_write(VEC_STEALTH * 4, struct.pack("<HH", at - 15, TSR))  # (after its three pops)
        mu.hook_add(UC_HOOK_INTR, real_mode_interrupt)
        mu.mem_write(GAME_DS * 16 + 0x1661, struct.pack("<HH", 0, self.SHEETS))
        mu.mem_write(GAME_DS * 16 + 0x1669, struct.pack("<HH", 0, self.TYPES))
        mu.mem_write(TSR * 16 + 170, struct.pack("<H", 64))

    def word(self, offset, value=None):
        at = SS * 16 + (BP + offset) % 0x10000
        if value is not None:
            self.mu.mem_write(at, struct.pack("<h", value))
        return struct.unpack("<h", self.mu.mem_read(at, 2))[0]

    def attack(self, attacker=2, hidden=0b0100, behind=0, stab=0, thac0=15, thief=True, melee=1,
               weight=20, target_object=0):
        """INT VEC_STEALTH with SI the attacker; its sheet 5 ([BP-12h]) a thief or not, its
        weapon of type 7 ([BP-4]): ([BP-1Ah], [BP-24h], [BP-20h], what was pushed, STEALTH,
        STEALTH_USED)."""
        mu = self.mu
        mu.mem_write(self.hdr + 204, struct.pack("<HH", hidden, 0))
        mu.mem_write(self.SHEETS * 16 + 5 * 0x47 + 0x12, struct.pack("<H", 0x400 if thief else 0))
        mu.mem_write(self.TYPES * 16 + 7 * 0x14 + 4, struct.pack("<H", weight))
        for offset, value in ((-0x12, 5), (-4, 7), (-0x1A, behind), (-0x24, stab), (-0x20, thac0),
                              (-0x1C, target_object), (0x0E, melee)):
            self.word(offset, value)
        mu.mem_write(CALLER * 16 + 0x600, bytes((0xCD, VEC_STEALTH, 0x90)))
        for name, value in dict(cs=CALLER, ds=GAME_DS, ss=SS, esp=0x800, ebp=BP, eflags=IF | 2, esi=attacker,
                                eax=0x1111, ebx=0x2222, es=0x6666).items():
            mu.reg_write(getattr(r, "UC_X86_REG_" + name.upper()), value)
        mu.emu_start(CALLER * 16 + 0x600, CALLER * 16 + 0x602)
        self.assertEqual(mu.reg_read(r.UC_X86_REG_SP), 0x7FE)
        self.assertEqual([mu.reg_read(x) for x in (r.UC_X86_REG_AX, r.UC_X86_REG_BX, r.UC_X86_REG_ES)],
                         [0x1111, 0x2222, 0x6666])
        pushed, = struct.unpack("<h", mu.mem_read(SS * 16 + 0x7FE, 2))
        stealth, used = struct.unpack("<HH", mu.mem_read(self.hdr + 204, 4))
        return self.word(-0x1A), self.word(-0x24), self.word(-0x20), pushed, stealth, used

    def test_backstab(self):
        self.assertEqual(self.attack(), (1, 1, 11, 1, 0, 1))

    def test_behind_already(self):
        """The game had it from behind: only the backstab's +2 more."""
        self.assertEqual(self.attack(behind=1, thac0=13), (1, 1, 11, 1, 0, 1))

    def test_no_backstab(self):
        """From behind only: not a thief, a missile, a weapon too heavy."""
        for kw in (dict(thief=False), dict(melee=2), dict(weight=41)):
            self.assertEqual(self.attack(**kw), (1, 0, 13, 1, 0, 1), kw)

    def test_not_hidden(self):
        self.assertEqual(self.attack(hidden=0b1011), (0, 0, 15, 0, 0b1011, 0))
        self.assertEqual(self.attack(attacker=0x29, hidden=0b1111), (0, 0, 15, 0, 0b1111, 0))

    def test_an_object(self):
        """Attacking an object (no back): nothing, but the hiding is over."""
        self.assertEqual(self.attack(target_object=1), (0, 0, 15, 0, 0, 1))

    def test_rule_off(self):
        self.mu.mem_write(TSR * 16 + 170, struct.pack("<H", 0))
        self.assertEqual(self.attack(), (0, 0, 15, 0, 0b0100, 0))


@unittest.skipIf(Uc is None, "unicorn not installed")
class TypesTests(unittest.TestCase):
    """The game's item type table: room for TYPES_EXTRA more, and DSCLOG's copied in after."""
    TYPES_SEG = 0x5000

    def setUp(self):
        image = load_image()
        self.mu = mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        mu.mem_write(TSR * 16, image)
        size = image.find(bytes.fromhex("8146fca000" "8356fe00"))  # 8 types of 20 bytes: A0h
        names_fill = image.find(bytes.fromhex("83c40c" "2eff36"))
        fill = image.find(bytes.fromhex("83c40c" "2eff36"), names_fill + 1) - 15
        self.assertGreater(min(size, fill - names_fill), 0)
        mu.mem_write(VEC_TYPES_SIZE * 4, struct.pack("<HH", size, TSR))
        mu.mem_write(VEC_TYPES_FILL * 4, struct.pack("<HH", fill, TSR))
        mu.hook_add(UC_HOOK_INTR, real_mode_interrupt)
        mu.mem_write(GAME_DS * 16 + 0x1669, struct.pack("<HH", 0, self.TYPES_SEG))
        self.hdr = TSR * 16 + image.find(HDR_SIG)

    def interrupt(self, vector, **regs):
        mu = self.mu
        mu.mem_write(CALLER * 16 + 0x600, bytes((0xCD, vector, 0x90)))
        for name, value in dict(cs=CALLER, ds=GAME_DS, ss=SS, esp=0x800, ebp=BP, eflags=IF | 2, **regs).items():
            mu.reg_write(getattr(r, "UC_X86_REG_" + name.upper()), value)
        mu.emu_start(CALLER * 16 + 0x600, CALLER * 16 + 0x602)
        return mu.reg_read(r.UC_X86_REG_SP)

    def test_room_and_filled(self):
        """The game's 115 types (2300 bytes): 160 bytes more reserved, and after the read
        DSCLOG's types at 115 on, the number noted."""
        from dscompanion import npcitems
        self.mu.mem_write(SS * 16 + BP - 4, struct.pack("<I", 2300))
        self.assertEqual(self.interrupt(VEC_TYPES_SIZE), 0x7FC)
        self.assertEqual(struct.unpack("<I", self.mu.mem_read(SS * 16 + BP - 4, 4))[0], 2460)
        self.mu.mem_write(SS * 16 + 0x7FC, bytes(4))
        self.assertEqual(self.interrupt(VEC_TYPES_FILL, eax=0), 0x80C)
        at = self.TYPES_SEG * 16 + 115 * 20
        self.assertEqual(bytes(self.mu.mem_read(at, 40)), b"".join(npcitems.TYPES))
        first, off, seg = struct.unpack("<HHH", self.mu.mem_read(self.hdr + 212, 6))
        self.assertEqual((first, off, seg), (115, 0, self.TYPES_SEG))
        self.assertEqual([self.mu.reg_read(x) for x in (r.UC_X86_REG_AX, r.UC_X86_REG_DS)], [0, GAME_DS])

    def test_not_read(self):
        self.mu.mem_write(SS * 16 + BP - 4, struct.pack("<I", 2460))
        self.assertEqual(self.interrupt(VEC_TYPES_FILL, eax=1), 0x80C)
        self.assertEqual(bytes(self.mu.mem_read(self.hdr + 212, 6)), bytes(6))


if __name__ == "__main__":
    unittest.main()
