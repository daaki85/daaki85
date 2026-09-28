"""Reader for SSI's GFF container format (Dark Sun resource and save files).

Layout, as seen in Shattered Lands saves:
  header:  "GFFI", version, data offset, TOC offset, TOC length, flags, ...  (u32 each)
  TOC:     u32 x2 (offsets), u16 type count, then per type:
             4-char type, u32 chunk count, then per chunk: u32 id, u32 offset, u32 length
"""

import struct
from typing import Dict, Tuple

Chunks = Dict[Tuple[str, int], bytes]


class GffError(Exception):
    pass


def read_gff(data: bytes) -> Chunks:
    """{(type, id): chunk bytes} for every chunk in a GFF file."""
    if data[:4] != b"GFFI":
        raise GffError("Not a GFF file (missing GFFI signature)")
    try:
        toc_offset, = struct.unpack_from("<I", data, 12)
        pos = toc_offset + 8
        type_count, = struct.unpack_from("<H", data, pos)
        pos += 2
        chunks = {}
        for _ in range(type_count):
            ctype, count = struct.unpack_from("<4sI", data, pos)
            pos += 8
            for _ in range(count):
                cid, offset, length = struct.unpack_from("<III", data, pos)
                pos += 12
                if offset + length > len(data):
                    raise GffError(f"Chunk {ctype!r} {cid} runs past the end of the file")
                chunks[(ctype.decode("latin1"), cid)] = data[offset:offset + length]
    except struct.error as e:
        raise GffError(f"Truncated GFF table of contents: {e}") from e
    return chunks
