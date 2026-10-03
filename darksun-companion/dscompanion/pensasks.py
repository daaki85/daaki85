"""Dinos and the Trustee asked about Kalzith and Semyon.

Both of the game's people answer questions about the others in the pens from a menu ("What do you
know about Gilal?", "What can you tell me about Dinos?"); with the Ledger, the same menus also ask
about Kalzith once the Ledger has found him in the pens (kalzith.py), and about Semyon while he
is in his pen (semyon.py). As the game's own, a question isn't shown again once answered in that
talk.

Nothing of the game's scripts moves (their jumps go to fixed offsets): two of their commands
become jumps (64h) to code put after the script's end. The one starting the menu's part, which
clears the menu's local, goes to a piece doing that, then setting the questions' flags, and
jumping back; the menu itself goes to a copy of it (the game's own bytes) with the new questions
after its last about someone, followed by a jump on to what comes after the game's menu. The
answers are subroutines, as the game's are.

The Trustee's script is then longer than the game's buffer for scripts allows (10000 bytes,
less some): the Ledger's copy of the game has a bigger one (gamepatch.SCRIPT_BUFFER).
"""

from typing import NamedTuple, Optional, Sequence

from . import gamepatch, gpl, kalzith, semyon
from .kalzith import _Script

GOTO, MENU, SET, TEST, SKIP_UNLESS = 0x64, 0x48, 0x16, 0x18, 0x63
WHERE = 0x80  # (the person talking, an object): 999 when the object isn't on the map (only for
# the game's objects, below 520: Kalzith's, 1000, is never found, so his question waits on the
# flag the Ledger sets once it has found him in the pens and given him his scrolls)
GONE = 999
LOCAL, SET_LOCAL, FLAG = 0x8E, 14, 0x8D
# The longest script the buffer runs: in the game's, of 10000 bytes, one of 9800 ran and one of
# 10000 didn't; so as much less again, to be safe
LONGEST = gamepatch.SCRIPT_BUFFER - 400


class Ask(NamedTuple):
    text: str  # the question (as the game's: two spaces first)
    flag: int  # the companion's flag showing it (set as the menu's part starts)
    who: Optional[int]  # whose object must be on the map (None: no such test)
    after: Optional[int]  # a flag that must be set too (None: none)
    answer: str


DINOS_SCRIPT, TRUSTEE_SCRIPT = 139, 146
DINOS_ASKS = (
    Ask("  What do you know about Kalzith?", 766, None, kalzith.STOCKED,
        "The defiler in the middle pens. The templars bring him out when the crowd wants to watch "
        "magic burn. He's polite enough to me, and grateful for the scraps I save him. Don't let "
        "the guards hear you asking about him."),
    Ask("  What do you know about Semyon?", 767, semyon.SEMYON, semyon.PLACED,
        "Semyon? The templars had him tied out in the arena for a while. Word is he was asking too "
        "many questions about the Veiled Alliance. He's back in his pen now and keeps his head "
        "down. Smart man."),
)
TRUSTEE_ASKS = (
    Ask("  What can you tell me about Kalzith?", 768, None, kalzith.STOCKED,
        "Keep clear of that one. A defiler. The templars put him in here until the arena wants "
        "him. Mind you, he never gave me any trouble."),
    Ask("  What can you tell me about Semyon?", 769, semyon.SEMYON, semyon.PLACED,
        "Semyon? The templars tied him out in the arena for asking after the Veiled Alliance. "
        "He's back in his pen now. Mouthy. If he talks to you about rebels, you didn't hear it "
        "from me."),
)
QUESTION = "  What"  # (the new questions go after the menu's last asking about someone: before
# Dinos's "Let's change the subject.", the Trustee's "How can I get to Dinos?", and "Goodbye.")
# (the script, its menu's first question, the questions added)
MENUS = ((DINOS_SCRIPT, "  What do you know about Gilal?", DINOS_ASKS),
         (TRUSTEE_SCRIPT, "  What can you tell me about Dinos?", TRUSTEE_ASKS))


def _here(obj: int) -> list:
    return ["(", ("op", (WHERE, [kalzith.ACTOR, ("n", -obj)])), ")", "<", ("n", GONE)]


def _shown(ask: Ask) -> tuple:
    """Whether ASK is shown: ASK.after is set and the one asked about is on the map."""
    parts = []
    if ask.after is not None:
        parts.append(["(", ("var", FLAG, ask.after), "==", ("n", 1), ")"])
    if ask.who is not None:
        parts.append(["("] + _here(ask.who) + [")"])
    out = parts[0]
    for part in parts[1:]:
        out = out + ["and"] + part
    return ("expr", out)


def with_asks(script: bytes, field_types: bytes, first: str, asks: Sequence[Ask]) -> bytes:
    """SCRIPT with ASKS in its menu whose first question is FIRST (once; unchanged without it)."""
    if gpl.encode_expr(("str", asks[0].text)) in script:
        return script
    ops = gpl.decode(script, field_types)
    m = next((i for i, o in enumerate(ops) if o.code == MENU and o.args[0]["replies"]
              and o.args[0]["replies"][0]["text"] == ("str", first)), None)
    if m is None or m < 2 or ops[m - 1].code != SKIP_UNLESS or ops[m - 2].code != TEST:
        return script
    test = ops[m - 2].args[0]  # (the menu's loop: while its local is 0)
    if not (test[0] == "expr" and len(test[1]) == 3 and test[1][0][:2] == ("var", LOCAL)):
        return script
    loop = test[1][0][2]
    start = next((i for i in range(m - 1, -1, -1) if ops[i].code == SET
                  and ops[i].args == [("n", 0), ("var", SET_LOCAL, loop)]), None)
    if start is None or m + 1 >= len(ops):
        return script
    start_op, menu_op = ops[start], ops[m]
    menu = menu_op.args[0]
    if script[menu_op.at:ops[m + 1].at] != gpl.encode_op(menu_op):
        return script  # (the copy must be the game's bytes)

    s = _Script()
    s.label("start")
    s.op(SET, *start_op.args)
    for ask in asks:
        s.flag(ask.flag, 0)
        s.when(_shown(ask), lambda ask=ask: s.flag(ask.flag, 1))
    s.op(GOTO, ("n", ops[start + 1].at))
    replies = list(menu["replies"])
    at = 1 + max(i for i, r in enumerate(replies)
                 if r["text"][0] == "str" and str(r["text"][1]).startswith(QUESTION))
    for ask in asks:
        name = s._new("reply")
        s.sub(name, lambda ask=ask: (s.say(ask.answer), s.flag(ask.flag, 0)))
        replies.insert(at, {"text": ("str", ask.text), "goto": ("label", name),
                            "if": ("var", FLAG, ask.flag), "before": [], "after": []})
        at += 1
    s.label("menu")
    s.op(MENU, dict(menu, replies=replies))
    s.op(GOTO, ("n", ops[m + 1].at))
    added = s.bytes(base=len(script), end=False)

    out = bytearray(script) + added
    if len(out) > LONGEST:
        return script
    for at, to in ((start_op.at, s.at["start"]), (menu_op.at, s.at["menu"])):
        jump = gpl.encode_op((GOTO, [("n", to)]))
        out[at:at + len(jump)] = jump
    return bytes(out)


def script_chunks(chunks, field_types: bytes) -> dict:
    """For the Ledger's copy of GPLDATA: Dinos's and the Trustee's talks with the questions."""
    out = {}
    for number, first, asks in MENUS:
        key = ("GPL ", number)
        if key in chunks:
            changed = with_asks(chunks[key], field_types, first, asks)
            if changed != chunks[key]:
                out[key] = changed
    return out
