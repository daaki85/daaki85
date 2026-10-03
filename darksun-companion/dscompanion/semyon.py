"""Semyon in the slave pens, as he promises.

Semyon (the arena's Tied-up Prisoner, untied: object SEMYON) fights beside the party for a
while, then leaves: "That's enough for me. I'll see you in the holding pens." Every way he goes
sets the game's flag GONE and walks him to the arena's door to the pens, where a script takes him
off the map (5Eh to region 255). Nothing in the pens ever brings him back: no script of theirs
names him or the flag. With the Ledger, the pens' master script (MAS 41) does, the way the
arena's script first put him on the map (25h: an object made at a place, as script 5 does when he
is untied): once the flag is set, the first time the party is in the pens after it he is in the
empty pen above Kalzith's (CELL), and talking to him runs his conversation (script SCRIPT).

His words are his own voice from the arena (a cheerful scout of the Veiled Alliance, who hid a
gem in one of the pens' grain pots), with no narration, as the game's talks.
"""

from typing import Dict, Tuple

from . import gpl, kalzith
from .kalzith import START, _Script, ALWAYS, _is

SEMYON = 280  # his object (RDFF 280, "Semyon"; the Tied-up Prisoner is 319)
SCRIPT = 219  # his conversation in the pens (Kalzith's is 218; the game's run to 217)
PORTRAIT = 118  # the game's portrait for him
GONE = 7  # the game's flag: he has gone to the holding pens
PLACED, MET = 764, 765  # (the companion's flags: Kalzith's are 760-763; the game's run to 755)
CELL = (99, 45)  # (tiles) the empty pen above Kalzith's, by its straw
MADE_AS = 6  # 25h's fifth number when the game makes him (script 5)


def placement(base: int) -> bytes:
    """For the end of the pens' master script, at offset BASE: him in his pen once he has gone
    there (once: PLACED), and his talk command."""
    s = _Script()
    gone_not_placed = ("expr", ["(", ("var", 0x8D, GONE), "==", ("n", 1), ")", "and",
                                "(", ("var", 0x8D, PLACED), "==", ("n", 0), ")"])
    s.when(gone_not_placed, lambda: (
        s.op(0x25, ("n", -SEMYON), ("n", 1), ("n", CELL[0]), ("n", CELL[1]), ("n", MADE_AS), ("n", 0)),
        s.flag(PLACED, 1)))
    s.op(kalzith.TALK, ("n", START), ("n", SCRIPT), ("n", -SEMYON))
    return s.bytes(base=base, end=False)


def with_semyon(master: bytes, field_types: bytes = b"") -> bytes:
    """The pens' master script with his part (once), just before its end: nothing of the game's
    moves (its "if" skips to a fixed offset)."""
    talk = gpl.encode_op((kalzith.TALK, [("n", START), ("n", SCRIPT), ("n", -SEMYON)]))
    if talk in master:
        return master
    ops = gpl.decode(master, field_types)
    if ops[-1].code != kalzith.END:
        raise gpl.ScriptError("the master script doesn't end as expected")
    end = ops[-1].at
    return master[:end] + placement(end) + master[end:]


def conversation() -> bytes:
    """Semyon's conversation in the pens (script SCRIPT)."""
    s = _Script()
    met = ("var", 0x8D, MET)

    def reply(text):
        return lambda: s.say(text)

    def farewell():
        s.say("Hail the Veiled Alliance!")
        s.page()
        s.leave()

    def menu():
        s.menu([("How did you get back in here?", reply(
                    "I walked in behind the water carriers. The guard counted heads, got one too "
                    "many, and decided he'd counted wrong. No templar ever doubts his own sums."), ALWAYS),
                ("Have you heard anything useful?", reply(
                    "Only the trustee, the head templar and Kurzak carry keys. The trustee keeps "
                    "his on his belt. Do with that what you will."), ALWAYS),
                ("Where was that gem again?", reply(
                    "In one of the grain pots: the kitchen, the storage room, or near the "
                    "fountain. I can't remember which, so check them all."), ALWAYS),
                ("Tell me about the Alliance.", reply(
                    "One village alone can't stand against an army. Bring them together, and Draj "
                    "will learn to fear the desert. But first, you have to get out of these pens."), ALWAYS),
                ("Farewell.", farewell, ALWAYS)])

    s.sub("menu", menu)
    s.op(kalzith.BEGIN)
    s.op(0x54, ("n", PORTRAIT))
    s.when(_is(met, 1),
           lambda: s.say("Hail, comrade! Still in one piece, I see."),
           lambda: (s.say("There you are! I told you I'd see you in the holding pens. Keep your "
                          "voice down: the walls in here have ears."), s.flag(MET, 1)))
    s.call("menu")
    return s.bytes()
