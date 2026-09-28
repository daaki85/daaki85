"""Layout files: where the party lives in memory and what each byte means.

A character can be spread over several records (Dark Sun keeps a creature
record with the name, current HP and THAC0, and a separate character sheet with
XP, classes and saving throws). Each record kind has its own per-slot
addresses. Field offsets are relative to their record's base and may be
negative. Fields whose offset is still null are shown as "?".

A record can be *linked* to another: its base is found by searching memory for
bytes it shares with the other record (e.g. the ability scores and entity id
both records carry), so only the record holding the name has to be located by
hand.
"""

import json
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import values

UNKNOWN = "?"

Reader = Callable[[int, int], bytes]  # (address, size) -> bytes


def _opt_int(v) -> Optional[int]:
    return None if v is None else values.parse_int(v)


def _hex(v: Optional[int]):
    return None if v is None else f"{v:#x}"


@dataclass
class Field:
    label: str
    offset: Optional[int]
    record: str
    type: str = "u8"
    length: int = 16
    names: Dict[int, str] = field(default_factory=dict)  # value -> display name, e.g. race ids
    format: str = ""  # "halves": the value counts halves, shown as 1, 3/2, 2...
    base: Optional["Field"] = None  # shown in brackets when it differs, e.g. the score without spells

    @classmethod
    def from_json(cls, raw: dict, default_record: str) -> "Field":
        f = cls(label=raw["label"], offset=_opt_int(raw.get("offset")),
                record=raw.get("record", default_record),
                type=raw.get("type", "u8"), length=raw.get("length", 16),
                names={values.parse_int(k): v for k, v in raw.get("values", {}).items()},
                format=raw.get("format", ""))
        values.type_size(f.type, f.length)  # validates the type
        if "base" in raw:
            b = raw["base"]
            f.base = cls.from_json({"label": "base", "type": f.type, **b}, f.record)
        return f

    def value(self, data: bytes, data_start: int):
        if self.offset is None:
            return None
        return values.decode(data, self.offset - data_start, self.type, self.length)

    @property
    def size(self) -> int:
        return values.type_size(self.type, self.length)

    def display(self, data: bytes, data_start: int) -> str:
        """Format this field from `data`, which holds its record starting at offset `data_start`."""
        if self.offset is None:
            return UNKNOWN
        v = values.decode(data, self.offset - data_start, self.type, self.length)
        if v is None:
            return "-"
        if v in self.names:
            return f"{self.names[v]} ({v})"
        if self.format == "halves":
            return str(v // 2) if v % 2 == 0 else f"{v}/2"
        return str(v)


@dataclass
class Link:
    """This record matches the `to` record when, for every (mine, theirs, length)
    triple, the bytes at those offsets are equal."""
    to: str
    match: List[Tuple[int, int, int]]


@dataclass
class Record:
    name: str
    slots: List[Optional[int]]
    stride: Optional[int] = None
    link: Optional[Link] = None

    def addresses(self) -> List[Optional[int]]:
        """Base of each slot. Unset slots follow slot 1 by `stride`, if known."""
        first = self.slots[0]
        return [addr if addr is not None or i == 0 or first is None or not self.stride
                else first + i * self.stride
                for i, addr in enumerate(self.slots)]


def _links_to(record: Record, base: int, other_base: int, snapshot: bytes) -> bool:
    """Whether a `record` at `base` shares the linking bytes of the other record at `other_base`."""
    mine0, theirs0, _ = record.link.match[0]
    return base >= 0 and base + mine0 != other_base + theirs0 and all(
        len(mine := snapshot[base + m:base + m + n]) == n
        and mine == snapshot[other_base + t:other_base + t + n]
        for m, t, n in record.link.match)


def find_linked(record: Record, other_base: int, snapshot: bytes,
                prefer: Optional[int] = None) -> Optional[int]:
    """Base address of the `record` that matches the other record at `other_base`.

    Games keep stale copies of records around, so `prefer` (e.g. where the
    party's stride says the record should be) wins when it matches."""
    mine0, theirs0, len0 = record.link.match[0]
    pattern = snapshot[other_base + theirs0:other_base + theirs0 + len0]
    if len(pattern) < len0 or not any(pattern):  # zeros match anywhere: an empty slot
        return None
    if prefer is not None and _links_to(record, prefer, other_base, snapshot):
        return prefer
    pos = snapshot.find(pattern)
    while pos != -1:
        if _links_to(record, pos - mine0, other_base, snapshot):
            return pos - mine0
        pos = snapshot.find(pattern, pos + 1)
    return None


class Layout:
    def __init__(self, raw: dict, path: Optional[str] = None):
        self.raw = raw
        self.path = path
        self.game = raw.get("game", "")
        self.count = raw.get("count", 4)
        records = raw.get("records") or {"record": {}}
        self.records: Dict[str, Record] = {}
        for rname, spec in records.items():
            slots = [_opt_int(s) for s in spec.get("slots", [])]
            link = spec.get("link")
            self.records[rname] = Record(
                rname, (slots + [None] * self.count)[:self.count], _opt_int(spec.get("stride")),
                Link(link["to"], [tuple(values.parse_int(x) for x in m) for m in link["match"]])
                if link else None)
        default = next(iter(self.records))
        name = raw.get("name", {})
        self.name = Field("Name", _opt_int(name.get("offset", 0)), name.get("record", default),
                          "str", name.get("length", 16))
        self.hex_before = raw.get("hex_before", 64)
        self.hex_after = raw.get("hex_after", 256)
        self.fields = [Field.from_json(f, default) for f in raw.get("fields", [])]
        for f in [self.name] + self.fields:
            if f.record not in self.records:
                raise ValueError(f"Field {f.label!r} refers to unknown record {f.record!r}")

    @classmethod
    def load(cls, path: str) -> "Layout":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), path)

    def save(self, path: Optional[str] = None) -> None:
        path = path or self.path
        specs = self.raw.setdefault("records", {})
        for rname, rec in self.records.items():
            spec = specs.setdefault(rname, {})
            spec["slots"] = [_hex(s) for s in rec.slots]
            spec["stride"] = _hex(rec.stride)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.raw, f, indent=2)
            f.write("\n")

    @property
    def name_record(self) -> Record:
        return self.records[self.name.record]

    def link_slot(self, slot: int, snapshot: bytes) -> None:
        """Fill in linked records for `slot` from the record they link to."""
        for rec in self.records.values():
            if rec.link is None or rec.slots[slot] is not None:
                continue
            other = self.records[rec.link.to].addresses()[slot]
            if other is not None:
                # where slot 1's record plus the stride puts it (None for slot 1 itself)
                expected = rec.addresses()[slot]
                rec.slots[slot] = find_linked(rec, other, snapshot, prefer=expected)

    def clear_slot(self, slot: int) -> None:
        for rec in self.records.values():
            rec.slots[slot] = None

    def window(self, record: str) -> Tuple[int, int]:
        """(start, end) offsets, relative to a record base, covering its mapped fields."""
        every = [self.name] + self.fields + [f.base for f in self.fields if f.base]
        mapped = [f for f in every if f.record == record and f.offset is not None]
        start = min([0] + [f.offset for f in mapped])
        end = max([1] + [f.offset + f.size for f in mapped])
        return start, end

    def decode_slot(self, slot: int, read: Reader) -> Tuple[str, Dict[str, Optional[int]], List[Tuple[str, str]]]:
        """(name, {record: base}, [(label, value), ...]) for one party slot."""
        bases = {r: rec.addresses()[slot] for r, rec in self.records.items()}
        data = {}
        for r, base in bases.items():
            if base is not None:
                start, end = self.window(r)
                data[r] = (read(base + start, end - start), start)

        def show(f: Field) -> str:
            if f.record not in data:
                return ""
            text = f.display(*data[f.record])
            if f.base and f.base.record in data:
                base = f.base.value(*data[f.base.record])
                if base is not None and base != f.value(*data[f.record]):
                    text += f" ({base} without spells)"
            return text

        return show(self.name), bases, [(f.label, show(f)) for f in self.fields]
