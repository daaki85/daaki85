import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dscompanion.textlog import (KIND_MESSAGE, KIND_PORTRAIT, KIND_REPLY, KIND_TEXT, Dialogue, TextBuffer,
                                 TextRecord, parse_records)


def record(kind, text="", value=0, pointer=0):
    data = text.encode("cp437")
    return bytes((0xFE, kind)) + struct.pack("<IHH", pointer, value, len(data)) + data


class ParseTests(unittest.TestCase):
    def test_records(self):
        data = record(KIND_PORTRAIT, value=119) + record(KIND_TEXT, "Watch and enjoy! ", 115)
        self.assertEqual(parse_records(data), [TextRecord(KIND_PORTRAIT, 0, 119, ""),
                                               TextRecord(KIND_TEXT, 0, 115, "Watch and enjoy! ")])

    def test_buffer_wraps_around(self):
        mem = bytearray(0x3000)
        hdr, buf, size = 0x100, 0x1000, 64
        struct.pack_into("<H", mem, hdr + 20, 0)  # header at offset 0 of its segment
        struct.pack_into("<HHH", mem, hdr + 126, 50, buf - hdr, size)
        tb = TextBuffer(lambda a, n: bytes(mem[a:a + n]), hdr)
        rec = record(KIND_MESSAGE, "NO PATH FROM HERE")  # 27 bytes, from position 50: wraps at 64
        for i, b in enumerate(rec):
            mem[buf + (50 + i) % size] = b
        struct.pack_into("<H", mem, hdr + 126, 50 + len(rec))
        self.assertEqual(tb.poll(), [TextRecord(KIND_MESSAGE, 0, 0, "NO PATH FROM HERE")])
        self.assertEqual(tb.poll(), [])


class DialogueTests(unittest.TestCase):
    def test_pieces_make_one_entry_per_window(self):
        d = Dialogue()
        out = []
        for rec in (TextRecord(KIND_PORTRAIT, 0, 119, ""), TextRecord(KIND_TEXT, 0, 115, "Do not worry, "),
                    TextRecord(KIND_TEXT, 0, 115, "Gerakis"), TextRecord(KIND_TEXT, 0, 115, ". Stand back."),
                    TextRecord(KIND_TEXT, 0, 115, "END"), TextRecord(KIND_TEXT, 0, 115, "CLOSE")):
            out += d.add(rec, 1.0)
        self.assertEqual([(e.portrait, e.text) for e in out], [(119, "Do not worry, Gerakis. Stand back.")])

    def test_replies_and_idle(self):
        d = Dialogue()
        d.add(TextRecord(KIND_PORTRAIT, 0, 7, ""), 1.0)
        d.add(TextRecord(KIND_TEXT, 0, 115, "Who goes there?"), 1.0)
        d.add(TextRecord(KIND_REPLY, 0, 0, "A friend"), 1.0)
        d.add(TextRecord(KIND_REPLY, 0, 0, "Leave us alone"), 1.0)
        self.assertEqual(d.idle(1.5), [])
        (entry,) = d.idle(3.0)
        self.assertEqual((entry.portrait, entry.text, entry.replies), (7, "Who goes there?", ["A friend", "Leave us alone"]))


if __name__ == "__main__":
    unittest.main()
