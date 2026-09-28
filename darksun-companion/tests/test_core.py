import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dscompanion import guestmem, values
from dscompanion.gff import GffError, read_gff
from dscompanion.savefile import load_party
from dscompanion.layout import Layout
from dscompanion.process import ProcessError, Region
from dscompanion.search import SearchSession

import make_fake_party as fake

BUNDLED_LAYOUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "layouts", "shattered_lands.json")

HOST_REGION = 0x7F0000000000
HEADER = 0x10  # allocator header before the guest RAM block
GUEST_SIZE = 2 * 1024 * 1024


def make_guest_ram() -> bytearray:
    ram = bytearray(GUEST_SIZE)
    for i in range(32):  # IVT: most vectors point into the BIOS segment
        struct.pack_into("<HH", ram, i * 4, 0x1000 + i, 0xF000 if i % 4 else 0x0070)
    ram[guestmem.BIOS_DATE_ADDR:guestmem.BIOS_DATE_ADDR + 8] = guestmem.BIOS_DATE
    return ram


class FakeProcess:
    """Mimics ProcessMemory over an in-memory host region holding guest RAM."""

    pid = 4242

    def __init__(self, ram: bytearray, header: int = HEADER):
        self.memory = bytearray(header) + ram
        self.decoy = bytearray(4096)

    def regions(self):
        yield Region(0x1000, len(self.decoy))
        yield Region(HOST_REGION, len(self.memory))

    def read(self, addr, size):
        if HOST_REGION <= addr and addr + size <= HOST_REGION + len(self.memory):
            return bytes(self.memory[addr - HOST_REGION:addr - HOST_REGION + size])
        if 0x1000 <= addr and addr + size <= 0x1000 + len(self.decoy):
            return bytes(self.decoy[addr - 0x1000:addr - 0x1000 + size])
        raise ProcessError(f"unmapped {addr:#x}")


class LocateTests(unittest.TestCase):
    def test_finds_guest_ram_after_allocator_header(self):
        guest = guestmem.locate(FakeProcess(make_guest_ram()))
        self.assertEqual(guest.base, HOST_REGION + HEADER)
        self.assertEqual(guest.size, GUEST_SIZE)
        self.assertEqual(guest.read(guestmem.BIOS_DATE_ADDR, 8), guestmem.BIOS_DATE)

    def test_rejects_date_string_without_interrupt_table(self):
        ram = make_guest_ram()
        ram[:128] = bytes(128)
        with self.assertRaises(guestmem.GuestMemoryError):
            guestmem.locate(FakeProcess(ram))

    def test_explicit_host_base(self):
        guest = guestmem.locate(FakeProcess(make_guest_ram()), base=HOST_REGION + HEADER)
        self.assertEqual(guest.size, GUEST_SIZE)

    def test_reads_are_clipped_to_guest_ram(self):
        guest = guestmem.locate(FakeProcess(make_guest_ram()))
        self.assertEqual(len(guest.read(GUEST_SIZE - 4, 16)), 4)
        self.assertEqual(guest.read(GUEST_SIZE + 10, 16), b"")

    def test_find_text_ignoring_case(self):
        ram = make_guest_ram()
        ram[0x20000:0x20006] = b"SADIRA"
        ram[0x30000:0x30006] = b"Sadira"
        guest = guestmem.locate(FakeProcess(ram))
        self.assertEqual(guest.find(b"sadira", ignore_case=True), [0x20000, 0x30000])
        self.assertEqual(guest.find(b"Sadira"), [0x30000])


class ValuesTests(unittest.TestCase):
    def test_decode(self):
        data = b"KARA\0junk" + struct.pack("<hB", -5, 200)
        self.assertEqual(values.decode(data, 0, "str", 9), "KARA")
        self.assertEqual(values.decode(data, 9, "s16"), -5)
        self.assertEqual(values.decode(data, 11, "u8"), 200)
        self.assertIsNone(values.decode(data, 11, "u16"))
        self.assertIsNone(values.decode(data, -1, "u8"))

    def test_parse_int(self):
        self.assertEqual(values.parse_int("0x1c"), 28)
        self.assertEqual(values.parse_int("28"), 28)
        self.assertEqual(values.parse_int(28), 28)

    def test_encode_range(self):
        with self.assertRaises(ValueError):
            values.encode(300, "u8")


class SearchTests(unittest.TestCase):
    def test_narrowing(self):
        snap = bytearray(64)
        snap[5] = snap[20] = snap[40] = 23
        session = SearchSession.start(bytes(snap), "u8", 23)
        self.assertEqual(sorted(session.candidates), [5, 20, 40])
        snap[20] = 17
        snap[40] = 30
        session.refine(bytes(snap), "eq", 17)
        self.assertEqual(list(session.candidates), [20])

    def test_changed_and_near_window(self):
        snap = bytearray(64)
        snap[5] = snap[20] = snap[40] = 9
        session = SearchSession.start(bytes(snap), "u8", 9, lo=10, hi=50)
        self.assertEqual(sorted(session.candidates), [20, 40])
        snap[40] = 8
        session.refine(bytes(snap), "decreased")
        self.assertEqual(session.candidates, {40: 8})

    def test_save_and_load(self):
        session = SearchSession("s16", {0x1234: -3})
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s.json")
            session.save(path)
            loaded = SearchSession.load(path)
        self.assertEqual((loaded.vtype, loaded.candidates), ("s16", {0x1234: -3}))


class LayoutTests(unittest.TestCase):
    RAW = {
        "count": 3,
        "name": {"record": "main", "offset": 4, "length": 8},
        "records": {
            "main": {"slots": ["0x100", None, "0x300"], "stride": "0x80"},
            "extra": {"slots": [None, None, None],
                      "link": {"to": "main", "match": [["0x0", "0x10", 2], ["0x2", "0x12", 1]]}},
        },
        "fields": [
            {"label": "HP", "offset": "0x10", "type": "s16"},
            {"label": "Race", "offset": -2, "type": "u8", "values": {"1": "Mul"}},
            {"label": "THAC0", "offset": None},
            {"label": "XP", "record": "extra", "offset": 4, "type": "u16"},
        ],
    }

    def test_slots_follow_stride(self):
        self.assertEqual(Layout(self.RAW).records["main"].addresses(), [0x100, 0x180, 0x300])

    def test_window_and_decode(self):
        layout = Layout(self.RAW)
        self.assertEqual(layout.window("main"), (-2, 0x12))
        mem = bytearray(0x400)
        mem[0x100 - 2] = 1
        mem[0x104:0x10A] = b"RIKUS\0"
        struct.pack_into("<h", mem, 0x110, 31)
        name, bases, rows = layout.decode_slot(0, lambda a, n: bytes(mem[a:a + n]))
        self.assertEqual(name, "RIKUS")
        self.assertEqual(bases, {"main": 0x100, "extra": None})
        self.assertEqual(rows, [("HP", "31"), ("Race", "Mul (1)"), ("THAC0", "?"), ("XP", "")])

    def test_linked_record_is_found_by_shared_bytes(self):
        layout = Layout(self.RAW)
        mem = bytearray(0x400)
        mem[0x110:0x113] = b"\x07\x80\x05"  # main record: shared bytes
        mem[0x200:0x203] = b"\x07\x80\x09"  # decoy: first match only
        mem[0x250:0x253] = b"\x07\x80\x05"  # the real linked record
        struct.pack_into("<H", mem, 0x254, 1234)
        layout.link_slot(0, bytes(mem))
        self.assertEqual(layout.records["extra"].slots[0], 0x250)
        _, _, rows = layout.decode_slot(0, lambda a, n: bytes(mem[a:a + n]))
        self.assertEqual(rows[-1], ("XP", "1234"))

    def test_empty_slot_is_not_linked(self):
        layout = Layout(self.RAW)
        layout.link_slot(0, bytes(0x400))  # all zeros: the shared bytes match anywhere
        self.assertIsNone(layout.records["extra"].slots[0])

    def test_unknown_record_is_rejected(self):
        raw = dict(self.RAW, fields=[{"label": "X", "record": "nope", "offset": 0}])
        with self.assertRaises(ValueError):
            Layout(raw)

    def test_save_writes_slots(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "layout.json")
            with open(path, "w") as f:
                json.dump(self.RAW, f)
            layout = Layout.load(path)
            layout.records["main"].slots[1] = 0x1A0
            layout.save()
            self.assertEqual(Layout.load(path).records["main"].slots, [0x100, 0x1A0, 0x300])

    def test_bundled_layout_loads(self):
        layout = Layout.load(BUNDLED_LAYOUT)
        self.assertEqual(layout.count, 4)
        self.assertEqual(set(layout.records), {"creature", "sheet"})


def build_gff(chunks) -> bytes:
    """A GFF file holding {(type, id): bytes}, in the layout the game writes."""
    data = bytearray(struct.pack("<4s6I", b"GFFI", 0x30000, 28, 0, 0, 0, 0))
    toc = bytearray()
    types = {}
    for (ctype, cid), payload in chunks.items():
        types.setdefault(ctype, []).append((cid, len(data), len(payload)))
        data += payload
    toc += struct.pack("<IIH", 8, 0, len(types))
    for ctype, entries in types.items():
        toc += struct.pack("<4sI", ctype.encode(), len(entries))
        for entry in entries:
            toc += struct.pack("<III", *entry)
    struct.pack_into("<II", data, 12, len(data), len(toc))
    return bytes(data + toc)


class SaveFileTests(unittest.TestCase):
    def test_read_gff(self):
        chunks = read_gff(build_gff({("SAVE", 5): b"abc", ("SAVE", 6): b"", ("STXT", 1): b"x"}))
        self.assertEqual(chunks, {("SAVE", 5): b"abc", ("SAVE", 6): b"", ("STXT", 1): b"x"})

    def test_rejects_non_gff(self):
        with self.assertRaises(GffError):
            read_gff(b"MZ" + bytes(40))

    def test_party_from_save(self):
        sadira = [14, 17, 13, 16, 12, 15]
        rikus = [20, 15, 18, 10, 11, 12]
        creatures = (fake.creature(b"SADIRA", 0x8001, sadira, 21, 40, 18)
                     + fake.creature(b"RIKUS", 0x8002, rikus, 52, 20, 17)
                     + bytes(fake.CREATURE * 2))
        # sheets stored in the other order, to prove they are matched by content
        sheets = (fake.sheet(0x8002, rikus, 5200, 52, 20, 7, [10, 0, 0], [4, 0, 0])
                  + fake.sheet(0x8001, sadira, 4500, 30, 44, 3, [11, 0, 0], [4, 0, 0]))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "SAVE01.SAV")
            with open(path, "wb") as f:
                f.write(build_gff({("SAVE", 5): creatures, ("SAVE", 6): sheets}))
            layout = Layout.load(BUNDLED_LAYOUT)
            mem = load_party(path, layout)
        name, bases, rows = layout.decode_slot(0, mem.read)
        rows = dict(rows)
        self.assertEqual(name, "SADIRA")
        self.assertEqual((rows["HP"], rows["Max HP"], rows["XP"], rows["THAC0"]), ("21", "30", "4500", "18"))
        self.assertEqual(rows["Race"], "Elf (3)")
        self.assertEqual(layout.decode_slot(1, mem.read)[0], "RIKUS")
        self.assertIsNone(layout.records["creature"].slots[2])


if __name__ == "__main__":
    unittest.main()
