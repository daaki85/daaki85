"""The patched copy of the game the dice log runs: DSUNLOG.EXE.

The copy differs from DSUN.EXE in a few places, each replaced by an INT
instruction that DSCLOG.EXE answers (see dos/dsclog.asm):

  * the start of rand(), so every random number goes through DSCLOG, which
    gives the same numbers and records who asked;
  * the end of the saving throw, where DSCLOG records the final total and the
    number it had to reach;
  * the end of the AC calculation, where DSCLOG records the AC the game uses;
  * the start of the routine that feeds the dialogue window, where DSCLOG
    copies the text, the replies to choose from and the portrait shown;
  * the start of the message box routine ("... is broken !", level ups);
  * two places where the game adds up AC and saving throw modifiers, so that a worn
    ring with a plus (the Ring +1 the companion can put in the arena) counts;
  * the routine that lists a character's weapons, where DSCLOG adds each one's THAC0;
  * the start of a turn in a fight, where DSCLOG can add a move for boots (a rule change
    the companion turns on, like AC 1 for helms, which the AC place above gives).

A last change lets the copy live outside the game folder: the game looks for
its data files in the folder its EXE is in, and the copy looks in the current
folder instead (the launcher runs it from the game folder).

Patching the file rather than the running game means the patches are in place
before the game runs, including in overlays each time they are loaded. The
original DSUN.EXE is only read.
"""

import os
from typing import NamedTuple

GOG_SIZE = 611408  # DSUN.EXE of the GOG release (1.1)

VEC_RAND, VEC_SAVE, VEC_AC, VEC_TEXT, VEC_MSG, VEC_CHAR = range(0x60, 0x66)  # as in dsclog.asm
VEC_TURN, VEC_USE, VEC_VIEW, VEC_WIN, VEC_LOOK, VEC_UNLOOK, VEC_NEXT = 0xF1, 0xF2, 0xF3, 0xF4, 0xF5, 0xF6, 0xF7  # not 66h-6Fh: the game calls those itself, looking for drivers
VEC_RING_AC, VEC_RING_SAVE, VEC_WEAPON, VEC_MOVE = 0xF8, 0xF9, 0xFA, 0xFB


class Patch(NamedTuple):
    name: str
    offset: int  # in DSUN.EXE
    original: bytes
    replacement: bytes


def _interrupt(vector: int, length: int) -> bytes:
    return bytes((0xCD, vector)) + b"\x90" * (length - 2)


PATCHES = (
    # rand(): mov cx,[seed+2] / mov bx,... (the second instruction's first byte)
    Patch("rand", 0x5C22, bytes.fromhex("8b0e24418b"), _interrupt(VEC_RAND, 5)),
    # saving throw: mov al,[bp-2] / cmp al,[bp-1]
    Patch("save", 0x79BB7, bytes.fromhex("8a46fe3a46ff"), _interrupt(VEC_SAVE, 6)),
    # AC: mov ax,[bp-6] / add ax,si
    Patch("ac", 0x58FB6, bytes.fromhex("8b46fa03c6"), _interrupt(VEC_AC, 5)),
    # the dialogue window's input routine (kind, far pointer, word): push bp / mov bp,sp
    Patch("text", 0x7CE83, bytes.fromhex("558bec"), _interrupt(VEC_TEXT, 3)),
    # the message box routine (far pointer to the message): push bp / mov bp,sp
    Patch("message", 0x5536E, bytes.fromhex("558bec"), _interrupt(VEC_MSG, 3)),
    # the inventory screen's right-hand panel, just after its weapon lines: add sp,0Eh
    # (DSCLOG then adds THAC0, the saves and thief skills, in the game's own lettering)
    Patch("inventory", 0x6F6BF, bytes.fromhex("83c40e"), _interrupt(VEC_CHAR, 3)),
    # the combat loop, straight after the call that may pass the turn on: add sp,4
    # (DSCLOG then shows the companion's summary of the turn that ended, if it wants to)
    Patch("turn", 0x1C953, bytes.fromhex("83c404"), _interrupt(VEC_TURN, 3)),
    # the combat routine that call runs, once it has passed the turn on and before it plays a
    # turn the computer runs (a monster's) whole: cmp word [bp-2],0 / jne +5 (DSCLOG checks
    # the turn there too, so the turn before gets its own summary, then goes where the compare
    # and the jump would have; the jump is left as it is, but DSCLOG relies on it being there)
    Patch("next", 0x5734F, bytes.fromhex("837efe007505"), _interrupt(VEC_NEXT, 4) + bytes.fromhex("7505")),
    # the USE (cast spells) screen, after it labels its LEVEL button: add sp,0Ch
    # (DSCLOG then draws the character's spell slots under the spells)
    Patch("use", 0x70FBB, bytes.fromhex("83c40c"), _interrupt(VEC_USE, 3)),
    # the View Character screen's upper panel, once drawn: push dword 000B0140h
    # (DSCLOG then adds THAC0 and the saves under the item icons, and does the push)
    Patch("view", 0x8A471, bytes.fromhex("666840010b00"), _interrupt(VEC_VIEW, 6)),
    # the end of the routine that brings a window to the front and redraws it: xor ax,ax /
    # pop si (for the USE screen's window, DSCLOG draws the spell slots again)
    Patch("window", 0x2BBA9, bytes.fromhex("33c05e"), _interrupt(VEC_WIN, 3)),
    # the Look box (a creature in a fight), once its first status rows are drawn: mov si,ax /
    # xor di,di (DSCLOG then adds the monster's defences in the rows left, and does the moves)
    Patch("look", 0x5FCDA, bytes.fromhex("8bf033ff"), _interrupt(VEC_LOOK, 4)),
    # the end of the routine that closes the Look box: mov word [0844h],270Fh (DSCLOG does it,
    # then shows the monster's whole description in the dialogue window)
    Patch("unlook", 0x5F2AA, bytes.fromhex("c70644080f27"), _interrupt(VEC_UNLOOK, 6)),
    # the AC function, as it reads a worn item's type flags: mov al,es:[bx+0Fh] / cbw (DSCLOG
    # does it, marking rings as counting for AC, so a ring's plus betters AC)
    Patch("ring_ac", 0x58EBD, bytes.fromhex("268a470f98"), _interrupt(VEC_RING_AC, 5)),
    # the start of the saving throw's modifiers: xor si,si (DSCLOG starts SI, their sum, at
    # the plus of the rings the one saving wears)
    Patch("ring_save", 0x79D47, bytes.fromhex("33f6"), _interrupt(VEC_RING_SAVE, 2)),
    # the routine that lists a creature's weapons (the inventory screen, the Look box), straight
    # after drawing one: add sp,10h (DSCLOG does it, then adds that weapon's THAC0)
    Patch("weapon", 0x7276E, bytes.fromhex("83c410"), _interrupt(VEC_WEAPON, 3)),
    # where a creature's turn in a fight starts: mov es:[bx+22Bh],ax, its movement for the turn
    # (DSCLOG does it, adding 1 move for boots when the companion's rule is on)
    Patch("move", 0x57566, bytes.fromhex("2689872b02"), _interrupt(VEC_MOVE, 5)),
    # The data path is argv[0] cut after its last \ or :, kept at DS:4B81h. The
    # code that finds the cut becomes: path = ".\", then on to "mov byte [si],0"
    # which ends it. (Not an empty path: the save list needs a \ in it.)
    Patch("path", 0x60D68, bytes.fromhex("8bf00bc0740346eb166a3a"),
          bytes.fromhex("c706814b2e5c"  # mov word [4B81h], ".\"
                        "be834b"  # mov si, 4B83h
                        "eb14")),  # jmp to mov byte [si],0
)


class PatchError(Exception):
    pass


def patched(original: bytes) -> bytes:
    """DSUN.EXE's bytes with the dice log patches applied."""
    if len(original) != GOG_SIZE:
        raise PatchError(f"DSUN.EXE is {len(original)} bytes; the dice log knows the GOG release "
                         f"({GOG_SIZE} bytes) only")
    data = bytearray(original)
    for p in PATCHES:
        if data[p.offset:p.offset + len(p.original)] != p.original:
            raise PatchError(f"DSUN.EXE is not the version the dice log knows ({p.name} differs)")
        data[p.offset:p.offset + len(p.original)] = p.replacement
    return bytes(data)


def write_patched(source: str, dest: str) -> None:
    """Write the patched copy of `source` to `dest`, unless it is already there."""
    with open(source, "rb") as f:
        data = patched(f.read())
    try:
        with open(dest, "rb") as f:
            if f.read() == data:
                return
    except OSError:
        pass
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
