"""Cheat-Engine-style value search, for discovering where the game keeps a stat.

Start with a known value (e.g. a character's current HP), change it in the game
(take a hit), then narrow the candidates with the new value. Repeat until only
a few addresses are left.
"""

import json
from typing import Dict, Optional

from . import values

OPS = ("eq", "changed", "unchanged", "increased", "decreased")


class SearchSession:
    def __init__(self, vtype: str, candidates: Dict[int, int]):
        self.vtype = vtype
        self.candidates = candidates  # guest address -> value when last checked

    @classmethod
    def start(cls, snapshot: bytes, vtype: str, value: int,
              lo: int = 0, hi: Optional[int] = None) -> "SearchSession":
        pattern = values.encode(value, vtype)
        hi = len(snapshot) if hi is None else min(hi, len(snapshot))
        candidates = {}
        pos = snapshot.find(pattern, max(lo, 0), hi)
        while pos != -1 and pos + len(pattern) <= hi:
            candidates[pos] = value
            pos = snapshot.find(pattern, pos + 1, hi)
        return cls(vtype, candidates)

    def refine(self, snapshot: bytes, op: str, value: Optional[int] = None) -> None:
        if op not in OPS:
            raise ValueError(f"Unknown comparison {op!r}; expected one of {', '.join(OPS)}")
        if op == "eq" and value is None:
            raise ValueError("'eq' needs a value")
        kept = {}
        for addr, old in self.candidates.items():
            new = values.decode(snapshot, addr, self.vtype)
            if new is None:
                continue
            if ((op == "eq" and new == value)
                    or (op == "changed" and new != old)
                    or (op == "unchanged" and new == old)
                    or (op == "increased" and new > old)
                    or (op == "decreased" and new < old)):
                kept[addr] = new
        self.candidates = kept

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump({"type": self.vtype,
                       "candidates": {f"{a:#x}": v for a, v in self.candidates.items()}}, f)

    @classmethod
    def load(cls, path: str) -> "SearchSession":
        with open(path) as f:
            data = json.load(f)
        return cls(data["type"], {int(a, 16): v for a, v in data["candidates"].items()})
