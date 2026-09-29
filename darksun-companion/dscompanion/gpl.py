"""Reader for the game's scripts (GPL), from GPLDATA.GFF in the game folder.

Everything the story does outside a fight is a script: conversations, doors, locks,
traps set off by hand, rewards. The interpreter is in DSUN.EXE: it reads a command byte,
then that command's values, and runs it (the table of commands is at DS:00C0h).

Values ("expressions") are one or more terms joined by operator bytes D1h-DFh, with E2h/E1h
as brackets. A term is:
  00h-7Fh    a number, this byte and the next (big-endian)
  8Fh b      a small number (signed byte);  90h w  a word;  91h w  minus a word;  8Bh dd  a dword
  81h-8Eh b  a variable (C1h-CEh with a word), 80h the last result
  8Ch op     the result of running a command;  92h  a string;  B1h  an object's field
A string is 1 (a name the game fills in), 2 (bytes stored shifted) or 5 (7-bit packed),
ending with code 3.

The decoder was checked against every script: all of them read to the end, and every
jump and call target in them lands on the start of a command.
"""

import struct
from typing import Callable, Dict, Iterator, List, NamedTuple, Optional, Tuple

from .gff import read_gff

SCRIPT_TYPES = ("GPL ", "MAS ")
FIELD_TYPES_AT = 0x3DE  # in the GPLX chunk: one byte per object field, which the query command needs
PARTY = 0x7FFE  # "who" meaning the whole party
OPERATORS = ("+", "-", "*", "/", "and", "or", "==", "!=", ">", "<", ">=", "<=", "&", "|", "^")
FIELD_SPECIAL = {0x25, 0x26, 0x27, 0x28, 0x2B, 0x2C}  # object numbers the game fills in

# Command 22h runs one of the game's actions: (action, who, value, value). Action 3 is a thief
# skill check: (3, who, skill, bonus); for the party, the member with the best chance rolls.
DO_ACTION = 0x22
ACTION_SKILL = 3
# Action 7 sets off a trap-like object at a map square: (7, object, x, y). The party's best at
# find/remove traps rolls first (no bonus); success, or Detect Traps, avoids it. The game uses
# it for traps and for scripted blasts (a thrown sphere, a summoning circle...).
ACTION_TRAP = 7
# Command 59h: an ability check, (who, modifier number, ability), a d20 under the ability.
ABILITY_CHECK = 0x59
SKILLS = ("pick pockets", "open locks", "find/remove traps", "move silently", "hide in shadows",
          "hear noise", "climb walls", "read languages")
ABILITIES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")


class ScriptError(Exception):
    pass


class Op(NamedTuple):
    at: int  # offset in the script
    code: int
    args: list


class _Reader:
    def __init__(self, data: bytes, field_types: bytes):
        self.d, self.i, self.field_types = data, 0, field_types

    def byte(self) -> int:
        if self.i >= len(self.d):
            raise ScriptError("past the end")
        self.i += 1
        return self.d[self.i - 1]

    def peek(self) -> int:
        """The next byte, or 0 (no operator or marker) at the end."""
        return self.d[self.i] if self.i < len(self.d) else 0

    def word(self) -> int:
        return (self.byte() << 8) | self.byte()


def _signed(v: int, bits: int) -> int:
    return v - (1 << bits) if v >= 1 << (bits - 1) else v


def _field(r: _Reader) -> tuple:
    obj = r.word()
    if obj >= 0x8000 and obj & 0x7FFF not in FIELD_SPECIAL:
        return ("field", obj, [])
    return ("field", obj, [r.byte() for _ in range(r.byte())])


def _string(r: _Reader) -> tuple:
    kind = r.peek()
    if kind == 1:
        r.byte()
        return ("str", "<name>")
    if kind == 2:
        r.byte()
        out = []
        while len(out) < 0x12B:
            c = (r.byte() << 2) & 0xFF
            if c == 3:
                break
            out.append(c)
        return ("str", bytes(out).decode("cp437"))
    if kind == 5:
        r.byte()
        w, shift, out = 0, 1, []
        while True:
            if shift > 0:
                w = ((w << 8) & 0xFF00) | r.byte()
            c = (w >> shift) & 0x7F
            if c == 3:
                break
            out.append(c)
            shift = shift + 1 if shift < 7 else 0
            if len(out) > 2000:
                raise ScriptError("string too long")
        return ("str", bytes(out).decode("cp437"))
    return ("str", None)


def _term(r: _Reader) -> tuple:
    b = r.byte()
    if b < 0x80:
        return ("n", (b << 8) | r.byte())
    if b == 0x80:
        return ("last",)
    if b == 0x8F:
        return ("n", _signed(r.byte(), 8))
    if b == 0x90:
        return ("n", _signed(r.word(), 16))
    if b == 0x91:
        return ("n", -_signed(r.word(), 16))
    if b == 0x8B:
        return ("n", _signed((r.word() << 16) | r.word(), 32))
    if b in (0x8C, 0xCC):
        return ("op", _op(r))
    if 0x81 <= b <= 0x8E:
        return ("var", b, r.byte())
    if 0xC1 <= b <= 0xCE:
        return ("var", b & 0xBF, r.word())
    if b == 0x92:
        return _string(r)
    if b == 0xB1:
        return _field(r)
    raise ScriptError(f"unknown term {b:02X}h")


def _expr(r: _Reader) -> tuple:
    parts, depth = [], 0
    while True:
        if r.peek() == 0xE2:
            r.byte()
            depth += 1
            parts.append("(")
            continue
        parts.append(_term(r))
        while depth and r.peek() == 0xE1:
            r.byte()
            depth -= 1
            parts.append(")")
        if 0xD1 <= r.peek() <= 0xDF:
            parts.append(OPERATORS[r.byte() - 0xD1])
            continue
        if depth:
            raise ScriptError("unclosed bracket")
        return parts[0] if len(parts) == 1 else ("expr", parts)


def _values(n: int) -> Callable[[_Reader], list]:
    return lambda r: [_expr(r) for _ in range(n)]


def _destination(r: _Reader) -> tuple:
    t = r.byte() & 0x7F
    wide = t & 0x40
    if wide:
        t = (t + 0xC0) & 0xFF
    if t < 0x10:
        return ("var", t, r.word() if wide else r.byte())
    return _field(r)


def _inline(r: _Reader) -> list:
    """The text commands a reply menu may have around each reply."""
    out = []
    while r.peek() in (0x23, 0x28, 0x2E, 0x4B):
        out.append(_op(r))
    return out


def _menu(r: _Reader) -> list:
    menu = {"before": _inline(r), "title": _expr(r), "replies": []}
    while r.peek() != 0x4A and len(menu["replies"]) <= 0x18:
        before, text, target, shown, after = _inline(r), _expr(r), _expr(r), _expr(r), _inline(r)
        menu["replies"].append({"text": text, "goto": target, "if": shown, "before": before, "after": after})
    r.byte()
    return [menu]


def _query(r: _Reader) -> list:
    who, a, b, tests = _expr(r), r.byte(), r.byte(), []
    while True:
        if r.peek() == 0x53:
            r.byte()
        field, kind, value = r.byte(), r.byte(), None
        if 4 <= kind <= 6 and field < len(r.field_types) and r.field_types[field] in (0x10, 0x12, 0x13, 0x14):
            value = _expr(r)
        tests.append((field, kind, value))
        if r.peek() != 0x53:
            return [who, a, b, tests]


_COUNTS = {0x01: 2, 0x02: 1, 0x03: 1, 0x04: 1, 0x05: 1, 0x06: 1, 0x07: 1, 0x08: 1, 0x09: 1, 0x0A: 2,
           0x0B: 2, 0x0C: 1, 0x0F: 1, 0x10: 3, 0x11: 2, 0x12: 1, 0x13: 1, 0x14: 2, 0x17: 1, 0x18: 1,
           0x1A: 2, 0x1B: 4, 0x1C: 4, 0x1D: 1, 0x1E: 1, 0x1F: 1, 0x20: 2, 0x21: 2, 0x22: 4, 0x24: 1,
           0x25: 6, 0x27: 2, 0x29: 1, 0x2D: 2, 0x2E: 1, 0x2F: 3, 0x30: 1, 0x32: 2, 0x34: 1, 0x36: 1,
           0x37: 2, 0x39: 4, 0x3A: 2, 0x3B: 1, 0x3C: 3, 0x3D: 1, 0x3E: 1, 0x3F: 1, 0x41: 1, 0x42: 1,
           0x43: 1, 0x44: 1, 0x45: 1, 0x46: 1, 0x49: 2, 0x4B: 3, 0x4F: 2, 0x50: 2, 0x52: 1, 0x54: 1,
           0x58: 3, 0x59: 3, 0x5A: 2, 0x5B: 2, 0x5C: 4, 0x5D: 1, 0x5E: 5, 0x5F: 1, 0x62: 1, 0x63: 1,
           0x64: 1, 0x65: 3, 0x66: 3, 0x68: 5, 0x69: 5, 0x6A: 7, 0x6B: 7, 0x6C: 3, 0x6D: 3, 0x6E: 3,
           0x6F: 3, 0x70: 4, 0x80: 2, **{c: 2 for c in range(0x76, 0x80)}}
_NONE = (0x00, 0x0E, 0x15, 0x19, 0x26, 0x2A, 0x2B, 0x31, 0x35, 0x38, 0x47, 0x4A, 0x4C, 0x4D, 0x4E,
         0x51, 0x53, 0x55, 0x56, 0x57, 0x60, 0x61, 0x67, 0x71, 0x72, 0x73, 0x74, 0x75)
COMMANDS: Dict[int, Callable[[_Reader], list]] = {c: _values(n) for c, n in _COUNTS.items()}
COMMANDS.update({c: (lambda r: []) for c in _NONE})
COMMANDS.update({
    0x16: lambda r: [_expr(r), _destination(r)],  # set a variable or field
    0x23: lambda r: [_string(r)],
    0x28: lambda r: [_expr(r), _expr(r), _string(r)],
    0x2C: lambda r: [_string(r)],
    0x33: _query,
    0x40: lambda r: [_field(r), _expr(r)],
    0x48: _menu,  # a reply menu
})


def _op(r: _Reader) -> Op:
    at, code = r.i, r.byte()
    if code not in COMMANDS:
        raise ScriptError(f"unknown command {code:02X}h at {at:X}h")
    return Op(at, code, COMMANDS[code](r))


def decode(data: bytes, field_types: bytes) -> List[Op]:
    """Every command in a script, in order."""
    r = _Reader(data, field_types)
    ops = []
    while r.i < len(data):
        ops.append(_op(r))
    return ops


def walk(x) -> Iterator[Op]:
    """Every command in a decoded script, including those inside values and menus."""
    if isinstance(x, Op):
        yield x
        yield from walk(x.args)
    elif isinstance(x, (list, tuple)):
        for y in x:
            yield from walk(y)
    elif isinstance(x, dict):
        for y in x.values():
            yield from walk(y)


def strings(x) -> Iterator[str]:
    if isinstance(x, tuple) and len(x) == 2 and x[0] == "str" and x[1]:
        yield x[1]
    elif isinstance(x, Op):
        yield from strings(x.args)
    elif isinstance(x, (list, tuple)):
        for y in x:
            yield from strings(y)
    elif isinstance(x, dict):
        for y in x.values():
            yield from strings(y)


def load_scripts(gpldata: bytes) -> Tuple[Dict[Tuple[str, int], bytes], bytes]:
    """({(type, id): script}, the field types) from GPLDATA.GFF's contents."""
    chunks = read_gff(gpldata)
    scripts = {k: v for k, v in chunks.items() if k[0] in SCRIPT_TYPES}
    extra = next((v for k, v in chunks.items() if k[0] == "GPLX"), b"")
    return scripts, extra[FIELD_TYPES_AT:]


class Check(NamedTuple):
    script: str  # "GPL 71"
    at: int
    kind: str  # "skill", "trap" or "ability"
    what: str  # "open locks", "DEX"
    who: str  # "party", "the active character"...
    bonus: Optional[int]  # a skill check's bonus; None when it isn't a number
    text: List[str]  # the script's text around it


def _number(e) -> Optional[int]:
    return e[1] if isinstance(e, tuple) and e[0] == "n" else None


def _who(e) -> str:
    n = _number(e)
    if n == PARTY:
        return "party (best chance rolls)"
    if n is not None:
        return f"creature {n}"
    return "the character acting" if e == ("var", 0x89, 0x25) else "a character the script chose"


def checks(scripts: Dict[Tuple[str, int], bytes], field_types: bytes, context: int = 300) -> List[Check]:
    """Every thief skill check (including the trap roll) and ability check in the scripts, with
    the text near each."""
    out = []
    for (ctype, cid), data in sorted(scripts.items()):
        ops = decode(data, field_types)
        every = list(walk(ops))
        for op in every:
            if op.code == DO_ACTION and _number(op.args[0]) == ACTION_SKILL:
                skill = _number(op.args[2])
                what = SKILLS[skill] if skill is not None and 0 <= skill < len(SKILLS) else "a skill"
                kind, who, bonus = "skill", _who(op.args[1]), _number(op.args[3])
            elif op.code == DO_ACTION and _number(op.args[0]) == ACTION_TRAP:
                obj = _number(op.args[1])
                kind, what, bonus = "trap", "find/remove traps", 0
                who = "party (best chance rolls)" + (f", object {obj}" if obj is not None else "")
            elif op.code == ABILITY_CHECK:
                ability = _number(op.args[2])
                what = ABILITIES[ability] if ability is not None and 0 <= ability < 6 else "an ability"
                kind, who, bonus = "ability", _who(op.args[0]), None
            else:
                continue
            text = [s for near in ops if abs(near.at - op.at) <= context for s in strings(near.args)]
            out.append(Check(f"{ctype.strip()} {cid}", op.at, kind, what, who, bonus, text))
    return out
