"""Dice log: shows the rolls Shattered Lands makes behind the scenes.

How it works:
  * DSCLOG.EXE (see dos/dsclog.asm), loaded before the game, keeps a ring
    buffer and a replacement for the game's Borland rand() that gives the same
    numbers but also records each call and the caller's stack frame.
  * attach() finds DSCLOG and the game's rand() in DOSBox's memory and patches
    rand() to jump to the replacement. detach() puts the original bytes back.
  * poll() returns new ring entries; describe() turns them into text using
    what the calling code does with the number (its dice size, and for known
    places in the game, THAC0, AC, ability scores and so on).

Everything game-specific here was taken from the GOG release of Shattered
Lands (DSUN.EXE, 611408 bytes).
"""

import re
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .game import CONVENTIONAL_AND_UPPER, CREATURE_NAME, CREATURE_SIZE, CREATURES_PTR, far_pointer
from .guestmem import GuestMemory

HDR_SIG = b"DSCLOGv1"

# Borland rand(): mov cx,[seed+2]; mov bx,[seed]; mov dx,015Ah; mov ax,4E35h; call LXMUL
RAND_RE = re.compile(rb"\x8b\x0e(..)\x8b\x1e(..)\xba\x5a\x01\xb8\x35\x4e\xe8", re.S)
# ... and after attach() has replaced its first 5 bytes with JMP FAR stub
RAND_PATCHED_RE = re.compile(rb"\xea(..)(..)\x1e(..)\xba\x5a\x01\xb8\x35\x4e\xe8", re.S)
RAND_IP = 0x822  # rand()'s offset in the game's first code segment

# Data the decoder reads from the game (DS offsets and load-segment-relative segments)
CREATURE_ABILITIES = 0x22
TARGET_GLOBAL = 0x494A  # combatant id of the current attack's target
# Far data the overlays use. Their code says segment 0x360 / 0x358, but those
# live 0x3612 paragraphs higher in memory (relative to the load segment).
COMBATANTS = (0x3972, 0xC36, 3)  # combatant id -> type byte (2 = creature), creature index word
CHECK_MODS = (0x396A, 4)  # ability check modifier table
CREATURE_STR = 0x22

# AD&D 2e strength damage adjustments (no exceptional strength in Dark Sun).
# The attack code adds the attacker's bonus after rolling melee damage; seen
# in play as +12 for STR 24.
STR_DAMAGE = {1: -4, 2: -2, 3: -1, 4: -1, 5: -1, 16: 1, 17: 1, 18: 2, 19: 7, 20: 8, 21: 9,
              22: 10, 23: 11, 24: 12, 25: 14}

ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")

# Code right after known rand() calls (the calling code, identified by its bytes)
ATTACK_SITE = bytes.fromhex("660fbfc0666bc01466bb00800000669966f7fb408946fa")
DICE_SITE = bytes.fromhex("660fbfc0660fbf5608660fafc266bb00800000669966f7fb")
CHECK_SITE = bytes.fromhex("660fbfc0666bc01466bb00800000669966f7fb8946fc3d13")
PERCENT_SITE = bytes.fromhex("bb640099f7fb3b56fe")
# Code right after the attack function's call to the dice function
WEAPON_DAMAGE_RETURN = bytes.fromhex("83c4068946fc0bc07f05")
# DSCLOG only records calls whose calling code starts like one of these (the
# rolls describe() can label), so bursts of other randomness don't crowd them out
FILTERS = (ATTACK_SITE[:8], DICE_SITE[:8], PERCENT_SITE[:8])  # the first also covers CHECK_SITE


class DiceLogError(Exception):
    pass


@dataclass
class Entry:
    seq: int
    ip: int
    cs: int
    raw: int
    bp: int
    ss: int
    ds: int
    parent_bp: int
    frame: bytes  # from SS:BP+2 (return address, then arguments)
    parent: bytes  # from SS:parentBP+0Ah
    glob: Tuple[int, int, int, int]
    locals: bytes  # from SS:BP-10h
    code: bytes  # the code right after this rand() call, copied when it ran
    parent_code: bytes  # the code at the caller's own return address

    SIZE = 128

    @classmethod
    def parse(cls, data: bytes) -> "Entry":
        head = struct.unpack_from("<8H", data, 0)
        return cls(*head, data[16:48], data[48:64], struct.unpack_from("<4H", data, 64), data[72:88],
                   data[88:112], data[112:128])

    def arg(self, bp_offset: int) -> int:
        """Signed word at [BP+bp_offset] in the caller's frame (bp_offset >= 2)."""
        return struct.unpack_from("<h", self.frame, bp_offset - 2)[0]

    def parent_arg(self, bp_offset: int) -> int:
        """Signed word at [BP+bp_offset] in the caller's caller's frame (bp_offset >= 0Ah)."""
        return struct.unpack_from("<h", self.parent, bp_offset - 0x0A)[0]

    def local(self, bp_offset: int) -> int:
        """Signed word at [BP+bp_offset] for bp_offset in -10h..-2."""
        return struct.unpack_from("<h", self.locals, bp_offset + 0x10)[0]


def scaled(raw: int, sides: int) -> int:
    """The game's rand()*N/32768: a number from 0 to N-1."""
    return raw * sides // 0x8000


def generic_roll(code: bytes, entry: Entry) -> Optional[Tuple[str, int]]:
    """(die, value), e.g. ("d20", 14) or ("0-9", 3), for the common 'rand()*N/32768 (+1)' shapes."""
    if not code.startswith(b"\x66\x0f\xbf\xc0"):  # movsx eax, ax
        return None
    rest = code[4:]
    if rest[:3] == b"\x66\x6b\xc0":  # imul eax, eax, imm8
        sides, rest = rest[3], rest[4:]
    elif rest[:3] == b"\x66\x69\xc0":  # imul eax, eax, imm32
        sides, rest = struct.unpack_from("<i", rest, 3)[0], rest[7:]
    elif rest[:3] == b"\x66\xc1\xe0":  # shl eax, n
        sides, rest = 1 << rest[3], rest[4:]
    elif rest[:4] == b"\x66\x0f\xbf\x56" and rest[5:9] == b"\x66\x0f\xaf\xc2":  # N = word [bp+x]
        sides, rest = entry.arg(rest[4]), rest[9:]
    else:
        return None
    if sides <= 0 or not rest.startswith(b"\x66\xbb\x00\x80\x00\x00\x66\x99\x66\xf7\xfb"):
        return None
    face = scaled(entry.raw, sides)
    if rest[11:12] == b"\x40":  # inc ax: a 1..N die
        return f"d{sides}", face + 1
    return f"0-{sides - 1}", face


class DiceLog:
    def __init__(self, guest: GuestMemory, show_all: bool = False):
        self.guest = guest
        self.show_all = show_all
        self.tsr_hdr: Optional[int] = None
        self.rand_addr: Optional[int] = None
        self.original: Optional[bytes] = None
        self.last_seq: Optional[int] = None
        self.missed = 0
        self._dice: Dict[Tuple[int, int, int, int], List[int]] = {}

    # ---- attaching ------------------------------------------------------------

    def attach(self) -> str:
        """Find DSCLOG and the game's rand(), and patch rand(). Returns a status line."""
        low = self.guest.read(0, CONVENTIONAL_AND_UPPER)
        hdr = next((m.start() for m in re.finditer(re.escape(HDR_SIG), low) if m.start() % 16 == 0), None)
        if hdr is None:
            raise DiceLogError("DSCLOG is not loaded. Start the game with 'Start Game with Dice Log.bat'.")
        stub_off, hdr_off = struct.unpack_from("<HH", low, hdr + 18)
        if (hdr - hdr_off) % 16:
            raise DiceLogError("DSCLOG header is misaligned")
        tsr_seg = (hdr - hdr_off) // 16
        jump = b"\xea" + struct.pack("<HH", stub_off, tsr_seg)

        for m in RAND_PATCHED_RE.finditer(low):
            if low[m.start():m.start() + 5] == jump and (m.start() - RAND_IP) % 16 == 0:
                seed = struct.unpack("<H", m.group(3))[0]
                self._attached(hdr, m.start(), b"\x8b\x0e" + struct.pack("<H", seed + 2) + b"\x8b", seed)
                return "Dice log already attached."
        found = [m for m in RAND_RE.finditer(low) if (m.start() - RAND_IP) % 16 == 0]
        if not found:
            raise DiceLogError("The game's rand() was not found. Is Shattered Lands running (past the intro)?")
        m = found[0]
        seed = struct.unpack("<H", m.group(2))[0]
        if struct.unpack("<H", m.group(1))[0] != seed + 2:
            raise DiceLogError("rand() does not look like Borland's")
        self._attached(hdr, m.start(), low[m.start():m.start() + 5], seed)
        self.guest.write(m.start(), jump)
        return "Dice log attached."

    def _attached(self, hdr: int, rand_addr: int, original: bytes, seed: int) -> None:
        self.guest.write(hdr + 22, struct.pack("<5H", seed, TARGET_GLOBAL, 0, 0, 0))
        self.tsr_hdr, self.rand_addr, self.original = hdr, rand_addr, original
        self.set_show_all(self.show_all)
        self.last_seq = struct.unpack("<H", self.guest.read(hdr + 8, 2))[0]

    def set_show_all(self, show_all: bool) -> None:
        """Record every rand() call, or (the default) only the kinds describe() can label."""
        self.show_all = show_all
        if self.tsr_hdr is not None:
            filters = () if show_all else FILTERS
            self.guest.write(self.tsr_hdr + 32, struct.pack("<H", len(filters)) + b"".join(filters))

    @property
    def attached(self) -> bool:
        return self.rand_addr is not None

    @property
    def load_seg(self) -> int:
        return (self.rand_addr - RAND_IP) // 16

    def still_patched(self) -> bool:
        """False when the game was restarted (rand() is back to the original)."""
        return self.guest.read(self.rand_addr, 5) != self.original

    def detach(self) -> None:
        if self.attached and self.still_patched():
            self.guest.write(self.rand_addr, self.original)
        self.rand_addr = self.original = None

    # ---- reading ----------------------------------------------------------------

    def poll(self) -> List[Entry]:
        """Entries written since the last poll, oldest first."""
        head = self.guest.read(self.tsr_hdr, 24)
        seq, _, nent, esize, ring_off = struct.unpack_from("<5H", head, 8)
        new = (seq - self.last_seq) & 0xFFFF
        if not new:
            return []
        ring_base = self.tsr_hdr - struct.unpack_from("<H", head, 20)[0] + ring_off
        ring = self.guest.read(ring_base, nent * esize)
        entries = {}
        for i in range(nent):
            e = Entry.parse(ring[i * esize:(i + 1) * esize])
            if 0 < (e.seq - self.last_seq) & 0xFFFF <= new:
                entries[e.seq] = e
        self.missed += new - len(entries)
        self.last_seq = seq
        return [entries[s] for s in sorted(entries, key=lambda s: (s - seq - 1) & 0xFFFF)]

    # ---- describing -----------------------------------------------------------

    def _far(self, ds: int, offset: int) -> int:
        return far_pointer(self.guest, ds, offset)

    def creature_name(self, ds: int, index: int) -> str:
        if not 0 <= index < 512:
            return f"creature {index}"
        rec = self._far(ds, CREATURES_PTR) + index * CREATURE_SIZE
        name = self.guest.read(rec + CREATURE_NAME, 16).split(b"\0", 1)[0].decode("cp437", "replace")
        return name or f"creature {index}"

    def combatant_name(self, ds: int, combatant: int) -> str:
        seg, off, stride = COMBATANTS
        if not 0 <= combatant < 256:
            return "?"
        kind, index = struct.unpack("<Bh", self.guest.read((self.load_seg + seg) * 16 + off + combatant * stride, 3))
        return self.creature_name(ds, index) if kind == 2 else "?"

    def strength(self, ds: int, index: int) -> int:
        return self.guest.read(self._far(ds, CREATURES_PTR) + index * CREATURE_SIZE + CREATURE_STR, 1)[0]

    def describe(self, e: Entry, show_all: bool = False) -> Optional[str]:
        """A log line for `e`, or None if it isn't worth showing (or completes later)."""
        code = e.code
        if code.startswith(ATTACK_SITE):
            d20 = scaled(e.raw, 20) + 1
            thac0, ac = e.arg(0x0A), e.arg(0x0C)
            need = thac0 - ac
            hit = d20 == 20 or (d20 != 1 and d20 >= need)
            note = " (natural 20)" if d20 == 20 else " (natural 1)" if d20 == 1 else ""
            return (f"{self.creature_name(e.ds, e.arg(0x0E))} attacks {self.combatant_name(e.ds, e.glob[0])}: "
                    f"d20 = {d20}{note}, needs {need} (THAC0 {thac0} with bonuses, target AC {ac}) "
                    f"-> {'HIT' if hit else 'miss'}")
        if code.startswith(DICE_SITE):
            return self._dice_roll(e, show_all)
        if code.startswith(CHECK_SITE):
            d20 = scaled(e.raw, 20) + 1
            ability = e.arg(0x0A)
            if not 0 <= ability < 6:
                return f"Check: d20 = {d20}" if show_all else None
            base = self.guest.read(self._far(e.ds, CREATURES_PTR) + e.arg(6) * CREATURE_SIZE
                                   + CREATURE_ABILITIES + ability, 1)[0]
            seg, off = CHECK_MODS
            mod = struct.unpack("<b", self.guest.read((self.load_seg + seg) * 16 + off + e.arg(8), 1))[0]
            ok = d20 != 20 and d20 <= base + mod
            mod_text = f" {'+' if mod >= 0 else '-'} {abs(mod)}" if mod else ""
            return (f"{self.creature_name(e.ds, e.arg(6))} {ABILITIES[ability]} check: d20 = {d20}, "
                    f"needs {base + mod} or less ({ABILITIES[ability]} {base}{mod_text}) "
                    f"-> {'success' if ok else 'failure'}")
        if code.startswith(PERCENT_SITE):
            chance, roll = e.local(-2), e.raw % 100 + 1
            return (f"Percentile check: d100 = {roll}, needs {chance} or less "
                    f"-> {'success' if roll <= chance else 'failure'}")
        if show_all:
            generic = generic_roll(code, e)
            where = f"{e.cs:04x}:{e.ip:04x}"
            if generic:
                return f"{generic[0]} = {generic[1]}  (at {where})"
            return f"rand() = {e.raw}  (at {where})"
        return None

    def _dice_roll(self, e: Entry, show_all: bool) -> Optional[str]:
        count, sides, bonus = e.arg(6), e.arg(8), e.arg(0x0A)
        key = (e.ss, e.bp, e.cs, e.ip)
        faces = self._dice.setdefault(key, [])
        faces.append(scaled(e.raw, sides) + 1)
        if len(faces) < count:
            return None
        del self._dice[key]
        weapon = e.parent_code.startswith(WEAPON_DAMAGE_RETURN)
        if not weapon and not show_all:
            return None
        signed = lambda n: f"{'+' if n >= 0 else '-'} {abs(n)}"
        rolled = f"{count}d{sides}" + (f"{signed(bonus).replace(' ', '')}" if bonus else "")
        faces_text = " + ".join(map(str, faces))
        parts = f"[{faces_text}]" + (f" {signed(bonus)}" if bonus else "")
        total = max(sum(faces) + bonus, 1) if weapon else sum(faces) + bonus
        if not weapon:
            return f"Dice: {rolled} = {parts} = {total}"
        attacker = e.parent_arg(0x0E)
        steps = f"{rolled} = {parts}"
        if sum(faces) + bonus < 1:
            steps += " (raised to the minimum of 1)"
        if e.parent_arg(0x16) <= 1:  # melee: the game adds the attacker's STR bonus
            strength = self.strength(e.ds, attacker)
            str_bonus = STR_DAMAGE.get(strength, 0)
            if str_bonus:
                steps += f" {signed(str_bonus)} STR {strength}"
                total += str_bonus
        return (f"  {self.creature_name(e.ds, attacker)} hits {self.combatant_name(e.ds, e.glob[0])} "
                f"for {total}: {steps}")
