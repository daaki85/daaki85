"""Encoding and decoding of the little-endian value types used by layouts and searches."""

import struct

FORMATS = {"u8": "<B", "s8": "<b", "u16": "<H", "s16": "<h", "u32": "<I", "s32": "<i"}
TYPES = tuple(FORMATS) + ("str",)


def type_size(vtype: str, length: int = 16) -> int:
    if vtype == "str":
        return length
    if vtype not in FORMATS:
        raise ValueError(f"Unknown type {vtype!r}; expected one of {', '.join(TYPES)}")
    return struct.calcsize(FORMATS[vtype])


def decode(data: bytes, offset: int, vtype: str, length: int = 16):
    """Value of type `vtype` at `offset` in `data`, or None if it runs past the end."""
    size = type_size(vtype, length)
    if offset < 0 or offset + size > len(data):
        return None
    if vtype == "str":
        # DOS text is code page 437, NUL-terminated.
        return data[offset:offset + size].split(b"\0", 1)[0].decode("cp437")
    return struct.unpack_from(FORMATS[vtype], data, offset)[0]


def encode(value: int, vtype: str) -> bytes:
    if vtype not in FORMATS:
        raise ValueError(f"Cannot search for type {vtype!r}; expected one of {', '.join(FORMATS)}")
    try:
        return struct.pack(FORMATS[vtype], value)
    except struct.error as e:
        raise ValueError(f"{value} does not fit in {vtype}") from e


def parse_int(text) -> int:
    """Accept ints, decimal strings and 0x-prefixed hex strings."""
    if isinstance(text, int):
        return text
    return int(str(text).strip(), 0)
