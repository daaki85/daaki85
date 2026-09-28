import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion import guestmem, values
from dscompanion.layout import Layout
from dscompanion.process import ProcessError, Region
from dscompanion.search import SearchSession

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
        "party": {"count": 3, "slots": ["0x100", None, "0x300"], "stride": "0x80",
                  "name_offset": 4, "name_length": 8},
        "fields": [
            {"label": "HP", "offset": "0x10", "type": "s16"},
            {"label": "Race", "offset": -2, "type": "u8", "values": {"1": "Mul"}},
            {"label": "THAC0", "offset": None},
        ],
    }

    def test_slots_follow_stride(self):
        self.assertEqual(Layout(self.RAW).slot_addresses(), [0x100, 0x180, 0x300])

    def test_window_and_decode(self):
        layout = Layout(self.RAW)
        start, end = layout.window()
        self.assertEqual((start, end), (-2, 0x12))
        record = bytearray(end - start)
        record[0] = 1  # offset -2
        record[6:12] = b"RIKUS\0"  # name at offset 4
        struct.pack_into("<h", record, 0x12, 31)
        name, rows = layout.decode(bytes(record), start)
        self.assertEqual(name, "RIKUS")
        self.assertEqual(rows, [("HP", "31"), ("Race", "Mul (1)"), ("THAC0", "?")])

    def test_save_writes_slots(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "layout.json")
            with open(path, "w") as f:
                json.dump(self.RAW, f)
            layout = Layout.load(path)
            layout.slots[1] = 0x1A0
            layout.save()
            self.assertEqual(Layout.load(path).slots, [0x100, 0x1A0, 0x300])

    def test_bundled_layout_loads(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "layouts", "shattered_lands.json")
        layout = Layout.load(path)
        self.assertEqual(layout.count, 4)
        self.assertTrue(all(f.offset is None for f in layout.fields))


if __name__ == "__main__":
    unittest.main()
