"""Layout files: where the party lives in memory and what each byte means.

A layout is a JSON file you fill in as you reverse-engineer the character
record. Field offsets are relative to a record's base address and may be
negative. Fields whose offset is still null are shown as "?".
"""

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import values

UNKNOWN = "?"


def _opt_int(v) -> Optional[int]:
    return None if v is None else values.parse_int(v)


@dataclass
class Field:
    label: str
    offset: Optional[int]
    type: str = "u8"
    length: int = 16
    names: Dict[int, str] = field(default_factory=dict)  # value -> display name, e.g. race ids

    @classmethod
    def from_json(cls, raw: dict) -> "Field":
        f = cls(label=raw["label"], offset=_opt_int(raw.get("offset")),
                type=raw.get("type", "u8"), length=raw.get("length", 16),
                names={values.parse_int(k): v for k, v in raw.get("values", {}).items()})
        values.type_size(f.type, f.length)  # validates the type
        return f

    @property
    def size(self) -> int:
        return values.type_size(self.type, self.length)

    def display(self, data: bytes, data_start: int) -> str:
        """Format this field from `data`, which holds the record starting at offset `data_start`."""
        if self.offset is None:
            return UNKNOWN
        v = values.decode(data, self.offset - data_start, self.type, self.length)
        if v is None:
            return "-"
        if v in self.names:
            return f"{self.names[v]} ({v})"
        return str(v)


class Layout:
    def __init__(self, raw: dict, path: Optional[str] = None):
        self.raw = raw
        self.path = path
        self.game = raw.get("game", "")
        party = raw.get("party", {})
        self.count = party.get("count", 4)
        slots = [_opt_int(s) for s in party.get("slots", [])]
        self.slots: List[Optional[int]] = (slots + [None] * self.count)[:self.count]
        self.stride = _opt_int(party.get("stride"))
        self.name = Field("Name", _opt_int(party.get("name_offset", 0)), "str",
                          party.get("name_length", 16))
        self.hex_before = party.get("hex_before", 64)
        self.hex_after = party.get("hex_after", 256)
        self.fields = [Field.from_json(f) for f in raw.get("fields", [])]

    @classmethod
    def load(cls, path: str) -> "Layout":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f), path)

    def save(self, path: Optional[str] = None) -> None:
        path = path or self.path
        party = self.raw.setdefault("party", {})
        party["slots"] = [None if s is None else f"{s:#x}" for s in self.slots]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.raw, f, indent=2)
            f.write("\n")

    def slot_addresses(self) -> List[Optional[int]]:
        """Record base of each party slot. Unset slots follow slot 1 by `stride`, if known."""
        result = []
        for i, addr in enumerate(self.slots):
            if addr is None and i > 0 and self.slots[0] is not None and self.stride:
                addr = self.slots[0] + i * self.stride
            result.append(addr)
        return result

    def window(self) -> Tuple[int, int]:
        """(start, end) offsets, relative to a record base, covering every mapped field."""
        mapped = [f for f in [self.name] + self.fields if f.offset is not None]
        start = min([0] + [f.offset for f in mapped])
        end = max([1] + [f.offset + f.size for f in mapped])
        return start, end

    def decode(self, data: bytes, data_start: int) -> Tuple[str, List[Tuple[str, str]]]:
        """(name, [(label, display value), ...]) for one record."""
        name = self.name.display(data, data_start)
        return name, [(f.label, f.display(data, data_start)) for f in self.fields]
