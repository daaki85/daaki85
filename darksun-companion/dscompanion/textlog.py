"""What the game shows as text: dialogue and message boxes.

DSCLOG copies everything the game sends to its dialogue window, and every
message box, into a text buffer (see dos/dsclog.asm). A dialogue arrives in
pieces: the speaker's portrait, then the text a phrase at a time (names are
separate pieces), then "END" when the window's text is complete and "CLOSE"
when the window closes. Replies to choose from arrive one by one, the first
being the list's title ("Answer Yes or No"), then the window is told to show
them.
"""

import struct
from dataclasses import dataclass, field
from typing import Callable, List, NamedTuple, Optional

KIND_REPLY, KIND_PORTRAIT, KIND_TEXT, KIND_SHOW_REPLIES, KIND_CLEAR = 0, 1, 2, 3, 4  # the dialogue window's
KIND_MESSAGE = 16  # a message box
RECORD_MARK = 0xFE
HEADER = 10  # mark, kind, dword, word, length
BUTTONS = {"END", "CLOSE", "MORE"}  # the window's buttons, sent like text
IDLE_SECONDS = 1.5  # a dialogue without END is shown after this long

# DSCLOG header offsets
TPOS, TBUF_OFF, TSIZE, HDR_OFF = 126, 128, 130, 20


class TextRecord(NamedTuple):
    kind: int
    pointer: int  # the far pointer the game passed (for text: where it was)
    value: int  # the word the game passed (for a portrait: its number)
    text: str


def parse_records(data: bytes) -> List[TextRecord]:
    """Records from a stretch of the text buffer that starts at a record."""
    out = []
    i = 0
    while i + HEADER <= len(data):
        if data[i] != RECORD_MARK:
            i += 1  # not expected: skip to the next record
            continue
        kind = data[i + 1]
        pointer, value, length = struct.unpack_from("<IHH", data, i + 2)
        text = data[i + HEADER:i + HEADER + length]
        if len(text) < length:
            break
        out.append(TextRecord(kind, pointer, value, text.decode("cp437", "replace")))
        i += HEADER + length
    return out


class TextBuffer:
    """Reads new records from DSCLOG's text buffer."""

    def __init__(self, read: Callable[[int, int], bytes], hdr: int):
        self.read = read
        self.hdr = hdr
        head = read(hdr, 132)
        base = hdr - struct.unpack_from("<H", head, HDR_OFF)[0]
        self.buf = base + struct.unpack_from("<H", head, TBUF_OFF)[0]
        self.size = struct.unpack_from("<H", head, TSIZE)[0]
        self.pos = struct.unpack_from("<H", head, TPOS)[0]
        self.missed = 0

    def poll(self) -> List[TextRecord]:
        pos = struct.unpack("<H", self.read(self.hdr + TPOS, 2))[0]
        new = (pos - self.pos) & 0xFFFF
        if not new:
            return []
        if new > self.size:  # more than the buffer holds came in: keep what's left
            self.missed += new - self.size
            new = self.size
        start = (pos - new) % self.size
        ring = self.read(self.buf, self.size)
        data = ring[start:start + new] + (ring[:start + new - self.size] if start + new > self.size else b"")
        self.pos = pos
        return parse_records(data)


@dataclass
class DialogueEntry:
    portrait: Optional[int]
    text: str = ""
    replies: List[str] = field(default_factory=list)
    title: str = ""  # of the replies, e.g. "Answer Yes or No"


class Dialogue:
    """Puts the pieces of the dialogue window back together."""

    def __init__(self):
        self.portrait: Optional[int] = None
        self.pieces: List[str] = []
        self.replies: List[str] = []
        self.last_at = 0.0

    def add(self, rec: TextRecord, now: float) -> List[DialogueEntry]:
        out: List[DialogueEntry] = []
        self.last_at = now
        if rec.kind == KIND_PORTRAIT:
            out += self.flush()
            self.portrait = rec.value
        elif rec.kind == KIND_REPLY:
            self.replies.append(rec.text)
        elif rec.kind == KIND_SHOW_REPLIES:
            out += self.flush()
        elif rec.kind == KIND_TEXT:
            if rec.text in BUTTONS:
                out += self.flush()
            else:
                if self.replies:  # text after a list of replies: a new message
                    out += self.flush()
                self.pieces.append(rec.text)
        return out

    def flush(self) -> List[DialogueEntry]:
        text = "".join(self.pieces).strip()
        title, replies = (self.replies[0], self.replies[1:]) if self.replies else ("", [])
        entry = DialogueEntry(self.portrait, text, replies, title) if text or self.replies else None
        self.pieces, self.replies = [], []
        return [entry] if entry else []

    def idle(self, now: float) -> List[DialogueEntry]:
        """What's waiting, if nothing has come for a while."""
        if (self.pieces or self.replies) and now - self.last_at >= IDLE_SECONDS:
            return self.flush()
        return []
