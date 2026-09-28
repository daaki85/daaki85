"""Locating and reading the emulated PC's RAM inside a DOSBox process.

DOSBox keeps guest RAM in one contiguous host allocation. Guest addresses used
throughout this tool are *linear* addresses inside that block: under DOS/4GW
(which Dark Sun uses) the game's flat 32-bit pointers are these same numbers,
as long as paging is off (the default).

To find the block we look for two things DOSBox always sets up:
  * the BIOS date string "01/01/92" at guest address 0xFFFF5
  * the real-mode interrupt vector table at guest address 0, most of whose
    entries point into the BIOS segment 0xF000
"""

import re
from typing import List, Optional

from . import values
from .process import ProcessError, ProcessMemory

BIOS_DATE_ADDR = 0xFFFF5
BIOS_DATE = b"01/01/92"
MIN_GUEST_SIZE = 0x100000  # 1 MB: the date string alone lives just below this
_CHUNK = 4 * 1024 * 1024


class GuestMemoryError(Exception):
    pass


class GuestMemory:
    def __init__(self, proc: ProcessMemory, base: int, size: int):
        self.proc = proc
        self.base = base  # host address of guest address 0
        self.size = size

    def read(self, addr: int, size: int) -> bytes:
        """Read guest memory, clipped to the guest RAM bounds."""
        start = max(addr, 0)
        end = min(addr + size, self.size)
        if end <= start:
            return b""
        return self.proc.read(self.base + start, end - start)

    def write(self, addr: int, data: bytes) -> None:
        if addr < 0 or addr + len(data) > self.size:
            raise GuestMemoryError(f"Write at guest {addr:#x} is outside guest RAM")
        self.proc.write(self.base + addr, data)

    def snapshot(self) -> bytes:
        return self.read(0, self.size)

    def value(self, addr: int, vtype: str, length: int = 16):
        return values.decode(self.read(addr, values.type_size(vtype, length)), 0, vtype, length)

    def find(self, pattern: bytes, ignore_case: bool = False, data: Optional[bytes] = None) -> List[int]:
        """Every guest address where `pattern` occurs."""
        data = self.snapshot() if data is None else data
        flags = re.IGNORECASE if ignore_case else 0
        return [m.start() for m in re.finditer(re.escape(pattern), data, flags)]


def _looks_like_ivt(ivt: bytes) -> bool:
    if len(ivt) < 128:
        return False
    segments = [int.from_bytes(ivt[i * 4 + 2:i * 4 + 4], "little") for i in range(32)]
    return segments.count(0xF000) >= 8


def locate(proc: ProcessMemory, base: Optional[int] = None) -> GuestMemory:
    """Find guest RAM in a DOSBox process. `base` skips the search (host address)."""
    regions = sorted(proc.regions())
    if base is not None:
        for region in regions:
            if region.start <= base < region.end:
                return GuestMemory(proc, base, region.end - base)
        raise GuestMemoryError(f"Host address {base:#x} is not in a readable region")

    for region in regions:
        if region.size < MIN_GUEST_SIZE:
            continue
        for offset in range(0, region.size, _CHUNK):
            start = region.start + offset
            try:
                chunk = proc.read(start, min(_CHUNK + len(BIOS_DATE), region.end - start))
            except ProcessError:
                continue
            for m in re.finditer(re.escape(BIOS_DATE), chunk):
                candidate = start + m.start() - BIOS_DATE_ADDR
                if candidate < region.start:
                    continue
                try:
                    ivt = proc.read(candidate, 128)
                except ProcessError:
                    continue
                if _looks_like_ivt(ivt):
                    return GuestMemory(proc, candidate, region.end - candidate)
    raise GuestMemoryError(
        "Could not find DOSBox guest RAM (no BIOS signature found). "
        "Is this DOSBox, and has it finished starting?")
