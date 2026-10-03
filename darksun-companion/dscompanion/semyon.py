"""Semyon in the slave pens, after he has fought beside the party and left the arena.

Semyon (the arena's Tied-up Prisoner, untied: object SEMYON) meets the party again in the
arena's bone area; recruited to the Alliance (the game's flag 6), he fights beside them in the
next fight and, if he survives, leaves: "That's enough for me. I'm leaving. I'll go find more
members for the Alliance." (script 2). Some of his replies in the bone area send him off before
that ("I'll see you in the holding pens", script 5). Each way he walks out through the arena's
entrance to the pens and a script takes him off the map, and nothing in the pens ever brings him
back.

The Ledger changes only the way after the fight: script 2 sends him walking out and, when he gets
there, runs script 5 at EXIT, which takes him off the map (5Eh to region 255); nothing else runs
that command. There, the Ledger's copy first sets its flag LEFT. A Semyon killed (in that fight,
or anywhere) the Ledger marks with its flag DIED (watch), and he is never put in the pens then.
The pens' master script (MAS 41) then puts him in his pen the way the
arena's script first put him on the map (25h: an object made at a place, as script 5 does when
he is untied): once LEFT is set, the first time the party is in the pens after it he is in the
free pen above Kalzith's (CELL), and talking to him runs his conversation (script SCRIPT). The
other ways he leaves, and a Semyon killed in the fight, stay as in the game: he isn't there.

His words are his own voice from the arena (a cheerful scout of the Veiled Alliance, who hid a
gem in one of the pens' grain pots), with no narration, as the game's talks.
"""

from typing import Dict, Tuple

from . import gpl, kalzith
from .kalzith import START, _Script, ALWAYS, _is

SEMYON = 280  # his object (RDFF 280, "Semyon"; the Tied-up Prisoner is 319)
SCRIPT = 219  # his conversation in the pens (Kalzith's is 218; the game's run to 217)
PORTRAIT = 118  # the game's portrait for him
GONE = 7  # the game's flag: he has gone to the holding pens (any way he left)
PLACED, MET = 764, 765  # (the companion's flags: Kalzith's are 760-763; the game's run to 755)
LEFT, DIED = 770, 771  # (the companion's) he left the arena after the fight he helped in; he died
ARENA_TALK, EXIT = 5, 2400  # his arena script, and where in it he is taken off the map then
REMOVE = 0x5E  # (object, region, x, y, ...): an object moved to a region (255: none)
GOTO = 0x64
CELL = (99, 45)  # (tiles) a free pen above Kalzith's, by its straw
MADE_AS = 6  # 25h's fifth number when the game makes him (script 5)


ESCAPED = 503  # the game's flag: the party escaped the pens (through the sewers' grate)
CLEARED = 775  # (the companion's) Kalzith and he taken off the map after the escape
GONE_AT = (255, 20, 20, 1)  # where the game puts the pens' people then (region 255: none)


def _flag(flag: int, value: int = 1) -> list:
    return ["(", ("var", 0x8D, flag), "==", ("n", value), ")"]


def placement(base: int) -> bytes:
    """For the end of the pens' master script, at offset BASE: him in his pen once he has left
    the arena after the fight (once: PLACED), and his talk command. After the party's escape,
    when the game takes the pens' people off the map (script 137 at 1176: "They killed everybody
    except for myself", the Trustee says), Kalzith and he go too (once: CLEARED), and he is never
    put in his pen."""
    s = _Script()
    gone_not_placed = ("expr", _flag(LEFT) + ["and"] + _flag(DIED, 0) + ["and"] + _flag(PLACED, 0)
                       + ["and"] + _flag(ESCAPED, 0))
    s.when(gone_not_placed, lambda: (
        s.op(0x25, ("n", -SEMYON), ("n", 1), ("n", CELL[0]), ("n", CELL[1]), ("n", MADE_AS), ("n", 0)),
        s.flag(PLACED, 1)))
    here = ("expr", ["(", ("op", (0x80, [kalzith.ACTOR, ("n", -SEMYON)])), ")", "<", ("n", 999)])
    s.when(("expr", _flag(ESCAPED) + ["and"] + _flag(CLEARED, 0)), lambda: (
        s.when(("expr", _flag(kalzith.STOCKED) + ["and"] + _flag(kalzith.DIED, 0)),
               lambda: s.op(REMOVE, ("n", -kalzith.OBJECT), *(("n", v) for v in GONE_AT))),
        s.when(here, lambda: s.op(REMOVE, ("n", -SEMYON), *(("n", v) for v in GONE_AT))),
        s.flag(CLEARED, 1)))
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


def with_exit(script: bytes, field_types: bytes = b"") -> bytes:
    """His arena script (ARENA_TALK) with LEFT set where he is taken off the map after the fight:
    the command at EXIT becomes a jump to the same after the script's end, LEFT set first, then a
    jump back to what follows it. Nothing of the game's moves. Unchanged if EXIT isn't that
    command (or is already the jump)."""
    try:
        ops = gpl.decode(script, field_types)
    except gpl.ScriptError:
        return script
    at = next((i for i, o in enumerate(ops) if o.at == EXIT), None)
    if at is None or at + 1 >= len(ops):
        return script
    op = ops[at]
    if op.code != REMOVE or op.args[0] != ("n", -SEMYON):
        return script
    s = _Script()
    s.flag(LEFT, 1)
    s.op(op.code, *op.args)
    s.op(GOTO, ("n", ops[at + 1].at))
    out = bytearray(script) + s.bytes(base=len(script), end=False)
    out[EXIT:EXIT + 3] = gpl.encode_op((GOTO, [("n", len(script))]))
    return bytes(out)


def watch(gd) -> bool:
    """DIED set once a creature named Semyon is dead (in the arena's fight, or anywhere): he
    isn't put in the pens then, and Dinos and the Trustee speak of him as dead. True when it was
    set now."""
    if gd.flag(DIED) or not kalzith.dead(gd, "Semyon"):
        return False
    gd.set_flag(DIED)
    return True


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
        s.menu([("Why did they tie you up out there?", reply(
                    "I was asking around the pens about the Veiled Alliance. Someone told the "
                    "templars, so they tied me out in the arena under the sun to see if I'd talk. "
                    "I didn't. After the fight they threw me back in here."), ALWAYS),
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
