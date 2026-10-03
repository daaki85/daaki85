"""Kalzith, a defiler in the slave pens who sells spell scrolls to a party that treats him well.

He is a slave the templars put in the arena now and then (the crowd loves to watch a defiler burn),
kept chained in an empty pen the rest of the time; he has the look of the arena's Defiler, but the
party has never fought him. He secretly scribes spells on scraps of hide, to buy a guard's blind eye; a preserver can learn from them (the game's own scrolls: right-click one, click
its spell). Insult him or threaten to report him and he won't trade until the party makes amends:
50 ceramic pieces, or a Charisma check.

He is the game's own kind of person, added to the Ledger's copies of three of its files (the game
folder is never changed; DSCLOG has the game open the copies):

  * SEGOBJEX.GFF: object OBJECT, his OJFF (a person's, with the arena Defiler's picture) and
    RDFF (a slave's record, Dinos's, with his name and a defiler's class);
  * RGN29.GFF, the slave pens: an entry in its entity table (ETAB) setting him in his pen (PEN);
  * GPLDATA.GFF: his conversation, script SCRIPT, and in the pens' master script (MAS 41) the
    command that runs it when the party talks to him (6Eh, as for Dinos and the rest), with its
    entry in the game's table of entry points (GPLI, which saves go by); and his
    portrait, PORTRAIT: the game's PORTRAIT_FROM with an X branded on the brow, so that no one
    else's face is his (the Ledger's dialogue tab shows it too).

The game reads the pens' people from RGN29 only the first time the party goes there (a save keeps
them as they were), so he is in new games: those started after the Ledger has these copies.
His stock, the six scrolls in SCROLLS, the Ledger puts among his things once a game (stock), as it
does the slave-pen items (npcitems); the game's shop screen (24h) sells what he carries.
"""

import struct
from typing import Callable, Dict, List, Optional, Tuple

from . import game, gpl
from .gff import read_gff

OBJECT = 1000  # (no object of the game's has it. Past the game's object table, 520 long: the
# shop command takes a number below that as an object there, so 297 opened someone's item list)
SCRIPTS_FILE, REGION_FILE = "GPLDATA.GFF", "RGN29.GFF"  # (DSCLOG opens the copies for the game's)
NAME = "Kalzith"
DINOS, DEFILER = 183, 296  # whose records his are made from
REGION, ETAB_ID, MASTER = 0x29, 41, 41  # the slave pens, its entity table and master script
SCRIPT = 218  # his conversation (the game's run to 217)
BEGIN, START = 0x19, 1  # the byte every game script opens with, and where talking starts: after it
                         # (the game takes a talk command for offset 0 as none: clicking did nothing)
PORTRAIT = 101  # his own: the game's portrait 61 with a slave's brand (101 is free in the game's)
PORTRAIT_FROM = 61  # a gaunt, bald man (shown also for another of the game's people)
PEN = (1580, 880)  # by the straw in the middle column's empty pen (its door on the left)
ENTITY_FLAGS = 14  # as the pens' other people have
OJFF_PICTURE = 0x0C  # an object's picture
RDFF_SELF, RDFF_NAME, RDFF_NAME_SIZE = 0x10, 0x32, 8  # the record's own object number; its name
RDFF_CLASS, RDFF_LEVEL = 0x6F, 0x72  # (as the arena Defiler's: a defiler, of level 9)
DEFILER_CLASS, LEVEL = 18, 5

# his state, in four of the game's global flags (bits; it uses 1-755, a save keeps 808): met
# him, friendly, cold; his scrolls given
MET, FRIENDLY, COLD = 760, 761, 762
STOCKED = 763  # (set by the Ledger: his scrolls given)

# The scrolls: (spell, its name, price in ceramic pieces). Cat's Grace is the game's Flaming Sphere
# (14) under the companion's rule, so it is sold only while the rule is on.
SCROLLS = ((8, "Magic Missile", 100), (4, "Color Spray", 100), (12, "Blur", 250),
           (game.FLAMING_SPHERE, "Cat's Grace", 250), (32, "Lightning Bolt", 500), (29, "Haste", 500))
SCROLL_TYPE = 0x60  # the game's spell scrolls (its objects 1400-1418)
SCROLL_TEMPLATE = "88fa01000f2700000f2760000000000105ff7f0000"  # its scroll of spell 1 (object 1400)
SCROLL_FROM = 1400  # the game's first scroll object, which his scrolls' objects copy
SCROLL_OBJECT = OBJECT + 1  # his k-th scroll is object 1001 + k: one each (the shop shows items of
# one object as one: six of 1400 showed as a single scroll), none of the game's (1001-1009 unused)
ITEM_OBJECT, ITEM_SPELL, ITEM_SPELL_AGAIN, ITEM_VALUE, ITEM_LINK = 0x00, 0x02, 0x0F, 0x06, 0x08


SCROLL_SPELL_FROM = 1  # a scroll names its spell one past the game's number for it (as the
# rest of the Ledger numbers spells: 1 Burning Hands): one of 29, Haste's, taught Flame Arrow


def scroll(spell: int, price: int, k: int = 0) -> bytes:
    """A spell scroll item (the game's own kind) teaching SPELL, priced PRICE: his K-th."""
    rec = bytearray.fromhex(SCROLL_TEMPLATE)
    struct.pack_into("<h", rec, ITEM_OBJECT, -(SCROLL_OBJECT + k))
    struct.pack_into("<H", rec, ITEM_LINK, game.NO_ITEM)  # (as the game's items; 0 linked item 0 in)
    struct.pack_into("<H", rec, ITEM_SPELL, spell + SCROLL_SPELL_FROM)
    rec[ITEM_SPELL_AGAIN] = spell + SCROLL_SPELL_FROM
    struct.pack_into("<H", rec, ITEM_VALUE, price)
    struct.pack_into("<H", rec, game.ITEM_NEXT, game.NO_ITEM)
    rec[game.ITEM_SLOT] = 0xFF
    return bytes(rec)


# ---------------------------------------------------------------------------------------------
# The objects file: his OJFF, RDFF and picture

def object_chunks(chunks) -> Dict[Tuple[str, int], bytes]:
    """For the Ledger's copy of SEGOBJEX: Kalzith's object (the arena Defiler's look) and record
    (a peaceful slave's, Dinos's, named and classed as a defiler)."""
    if any(k not in chunks for k in (("RDFF", DINOS), ("OJFF", DINOS), ("OJFF", DEFILER))):
        return {}
    rec = bytearray(chunks[("RDFF", DINOS)])
    struct.pack_into("<h", rec, RDFF_SELF, -OBJECT)
    rec[RDFF_NAME:RDFF_NAME + RDFF_NAME_SIZE] = NAME.encode("ascii").ljust(RDFF_NAME_SIZE, b"\0")
    rec[RDFF_CLASS], rec[RDFF_LEVEL] = DEFILER_CLASS, LEVEL
    obj = bytearray(chunks[("OJFF", DINOS)])  # a person's object (not a fighter's), with his picture
    obj[OJFF_PICTURE:OJFF_PICTURE + 2] = chunks[("OJFF", DEFILER)][OJFF_PICTURE:OJFF_PICTURE + 2]
    out = {("OJFF", OBJECT): bytes(obj), ("RDFF", OBJECT): bytes(rec)}
    if ("OJFF", SCROLL_FROM) in chunks:
        for k in range(len(SCROLLS)):
            out[("OJFF", SCROLL_OBJECT + k)] = chunks[("OJFF", SCROLL_FROM)]
    return out


# ---------------------------------------------------------------------------------------------
# His portrait

BRAND = (  # an X burned into the brow: "#" the groove, "o" its raised rim (lit from the upper right)
    "#...#",
    "o#.#o",
    ".o#o.",
    ".#o#.",
    "#o.o#",
)
BRAND_AT = (12, 3)  # its top left, on the left of the brow's highlight
BRAND_GROOVE, BRAND_RIM = 133, 152  # (portrait palette: a dark red-brown, a pale skin highlight)


def portrait(rows):
    """Portrait PORTRAIT_FROM's pixels (rows of palette indexes) with the brand."""
    out = [list(r) for r in rows]
    x0, y0 = BRAND_AT
    for dy, line in enumerate(BRAND):
        for dx, c in enumerate(line):
            if c != ".":
                out[y0 + dy][x0 + dx] = BRAND_GROOVE if c == "#" else BRAND_RIM
    return out


def portrait_chunk(chunks) -> Optional[bytes]:
    """His portrait as a PORT chunk, from the game's own (None without it)."""
    from . import icons
    source = chunks.get(("PORT", PORTRAIT_FROM))
    return icons.encode(portrait(icons.decode(source))) if source else None


# ---------------------------------------------------------------------------------------------
# The slave pens: his place

ENTITY = struct.Struct("<HHBBh")  # x, y, height, flags, object (negative: one of SEGOBJEX's)


def with_entity(etab: bytes) -> bytes:
    """The pens' entity table with Kalzith in his pen (once), at its end: the game's scripts name
    the pens' people by their place in it, so every entry of the game's keeps its own (an entry
    put in among them moved everyone after it: Kurzak vanished, others went missing)."""
    entries = [ENTITY.unpack_from(etab, i) for i in range(0, len(etab) - ENTITY.size + 1, ENTITY.size)]
    if any(e[4] == -OBJECT for e in entries):
        return etab
    return etab[:len(entries) * ENTITY.size] + ENTITY.pack(PEN[0], PEN[1], 0, ENTITY_FLAGS, -OBJECT)


# ---------------------------------------------------------------------------------------------
# His conversation

SPEAKS = 115  # the dialogue window's lines: his words (no narration: the game's talks have little)
LINE = 60  # the game's lines are no longer than this
REPLY = 40  # nor its replies (the reply window cuts a longer one off)
TITLE = ("var", 0x86, 1)  # a reply menu's title, as the game's own (the speaker)
MORE, CLEAR = ("var", 0x86, 2), ("var", 0x86, 3)  # wait for a click, then clear the window
MONEY = ("var", 0x89, 42)  # the party's ceramic pieces
ACTOR = ("var", 0x89, 37)
SPEAKER = ("var", 0x89, 39)  # the person being talked to (as the game's scripts name him)  # the character talking (who rolls an ability check)
CHA = 5


def _lines(text: str, width: int = LINE) -> List[str]:
    """TEXT in the game's line lengths (each ending in a space, as the game's own)."""
    out, line = [], ""
    for word in text.split():
        if line and len(line) + len(word) + 1 > width:
            out.append(line + " ")
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        out.append(line + " ")
    return out


class _Script:
    """A script built the way the game's are: structured, with no jump of its own.

    18h tests, 3Eh goes on to the "else" (3Fh) or the end (67h) when the test fails, 3Fh at the
    end of the "then" part skips the "else" part, 67h ends the "if" (once on each way through:
    one too many or too few ends the script with "BAD GPL EXIT"); a 3Fh anywhere else does
    nothing. Shared parts are subroutines: 13h calls one, 15h returns.

    Menus are the game's: a loop showing the menu until a local flag (DONE) is set, each reply
    a subroutine returning to it, doing its own part (calling what comes next) and setting DONE
    to end the talk. (Branching after the menu on a "which way" local went wrong in the game.)"""

    def __init__(self):
        self.items: List = []
        self.shown = 0  # lines in the window since it was last cleared (as laid out)
        self.subs: Dict[str, Callable[[], None]] = {}
        self._n = 0

    def op(self, code: int, *args) -> None:
        self.items.append((code, list(args)))

    def label(self, name: str) -> None:
        self.items.append(name)

    def _new(self, what: str) -> str:
        self._n += 1
        return f"{what} {self._n}"

    def say(self, text: str, who: int = SPEAKS) -> None:
        """TEXT in the window, a new page whenever the window (WINDOW lines) would run over."""
        for line in _lines(text):
            if self.shown == WINDOW:
                self.page()
            self.op(0x4F, ("n", who), ("str", line))
            self.shown += 1

    def page(self) -> None:
        """Wait for a click, then clear the window."""
        self.op(0x4F, ("n", SPEAKS), MORE)
        self.clear()

    def clear(self) -> None:
        self.op(0x4F, ("n", SPEAKS), CLEAR)
        self.shown = 0

    def set(self, var: int, value: int) -> None:
        self.op(0x16, ("n", value), ("var", 14, var))

    def flag(self, flag: int, value: int) -> None:
        self.op(0x16, ("n", value), ("var", 13, flag))

    def when(self, test, then: Callable[[], None], otherwise: Optional[Callable[[], None]] = None) -> None:
        """If TEST: THEN, else OTHERWISE."""
        other, done = self._new("else"), self._new("end if")
        self.op(0x18, test)
        self.op(0x3E, ("label", other if otherwise else done))
        shown = self.shown
        then()
        if otherwise:
            self.label(other)
            self.op(0x3F, ("label", done))
            self.shown = shown
            otherwise()
        self.label(done)
        self.op(0x67)
        self.shown = 0  # (either way)

    def sub(self, name: str, body: Callable[[], None]) -> None:
        """A subroutine NAME (laid out at the end, after the script's end)."""
        self.subs[name] = body

    def call(self, name: str) -> None:
        self.op(0x13, ("label", name))
        self.shown = 0

    def menu(self, replies: List[Tuple[str, Callable[[], None], object]]) -> None:
        """A menu, shown again until a reply leaves it (leave()). Each reply (REPLIES: text, body,
        shown when) is a subroutine doing its own part (calling the rest of the talk, as the
        game's replies do), so nothing branches after the menu."""
        loop, out = self._new("menu"), self._new("menu out")
        names = []
        for text, body, shown in replies:
            name = self._new("reply")
            names.append(name)
            self.sub(name, body)
        self.set(DONE, 0)
        self.label(loop)
        self.op(0x18, ("expr", [("var", 0x8E, DONE), "==", ("n", 0)]))
        self.op(0x63, ("label", out))
        self.op(0x48, {"before": [], "title": TITLE, "replies": [
            {"text": ("str", f"  {text}"), "goto": ("label", name), "if": shown, "before": [], "after": []}
            for (text, _, shown), name in zip(replies, names)]})
        self.op(0x64, ("label", loop))
        self.label(out)

    def leave(self) -> None:
        """(In a reply:) leave the menu once the reply is done (and any menu it went through)."""
        self.set(DONE, 1)

    def bytes(self) -> bytes:
        self.op(0x31)  # the talk's end
        done = set()
        while len(done) < len(self.subs):  # (subroutines may add subroutines)
            for name, body in list(self.subs.items()):
                if name in done:
                    continue
                done.add(name)
                self.label(name)
                self.shown = 0
                if name.startswith("reply"):
                    self.clear()
                body()
                self.op(0x15)

        def fill(x, at):
            if isinstance(x, tuple) and x and x[0] == "label":
                return ("n", at[x[1]])
            if isinstance(x, gpl.Op):
                return gpl.Op(x.at, x.code, fill(x.args, at))
            if isinstance(x, list):
                return [fill(y, at) for y in x]
            if isinstance(x, tuple):
                return tuple(fill(y, at) for y in x)
            if isinstance(x, dict):
                return {k: fill(v, at) for k, v in x.items()}
            return x
        # (a jump's place is 2 bytes whatever it is, so the lengths are known before the places)
        labels = {i: 0 for i in self.items if isinstance(i, str)}
        at, pos = {}, 0
        for item in self.items:
            if isinstance(item, str):
                at[item] = pos
            else:
                pos += len(gpl.encode_op(fill(item, labels)))
        return b"".join(gpl.encode_op(fill(item, at)) for item in self.items if not isinstance(item, str))


ALWAYS = ("n", 1)
DONE = 1  # the script's local ending a menu (as the game's merchants use 1 for the menu loop)
WINDOW = 4  # the lines the dialogue window shows


def _is(var, value) -> tuple:
    return ("expr", [var, "==", ("n", value)])


def conversation() -> bytes:
    """Kalzith's conversation (script SCRIPT)."""
    s = _Script()
    friendly, cold_, met = (("var", 0x8D, f) for f in (FRIENDLY, COLD, MET))

    def then_leave(*parts):
        def body():
            for part in parts:
                part()
            s.leave()
        return body

    def go():
        s.say("Go, then.")
        s.page()

    # -- the first meeting
    def first():
        s.menu([("We mean no harm. We're slaves too.", then_leave(lambda: s.call("respect")), ALWAYS),
                ("You're a defiler. You kill the land.", then_leave(lambda: s.call("accused")), ALWAYS),
                ("Who are you?", who, ALWAYS),
                ("Farewell.", then_leave(go), ALWAYS)])

    def who():
        s.say("Kalzith. Once a sorcerer's apprentice in Draj, now Pehtucl's property. The templars "
              "put a defiler in the arena now and then: the crowd loves to watch one burn. The rest of "
              "the time they chain me here, where the ground's already dead.")

    def respect():
        s.clear()
        s.flag(FRIENDLY, 1)
        s.flag(COLD, 0)
        s.say("Hm. Slaves with manners. Rarer than water. Keep your voice down.")
        s.page()
        s.say("I have something you might want. I scribe spells on scraps of hide, at night. A "
              "preserver could learn from them: the magic on the page doesn't care how you draw your "
              "power.")
        s.page()
        s.say("And I need ceramic for a guard who can look the other way.")
        s.call("friend")

    # -- a friend: the shop
    def friend():
        s.menu([("Show us what you have.", shop, ALWAYS),
                ("Why would a defiler help a preserver?", why, ALWAYS),
                ("Isn't this dangerous for you?", danger, ALWAYS),
                ("Farewell.", then_leave(see_you), ALWAYS)])

    def shop():
        s.say("Quietly, now. One of each, and they're not cheap.")
        s.page()
        s.op(0x24, SPEAKER)  # (his own place in the game's object table: where its shops are)
        s.say("Learn them well, and burn the hide when you're done.")

    def why():
        s.say("Because a preserver's coin buys the same bribe. And because I'm tired of being the "
              "only one in the pens the others fear.")

    def danger():
        s.say("Everything is dangerous for me. Pehtucl would flay me for this. So keep it quiet.")

    def see_you():
        s.say("Come back when you've earned some coin.")
        s.page()

    # -- accused, and cold
    def accused():
        s.clear()
        s.say("And the templars kill slaves with every order. We do what Athas lets us.")
        s.menu([("Fair enough. I spoke too quickly.", then_leave(lambda: s.call("respect")), ALWAYS),
                ("We'll tell the templars about you.", then_leave(turn_cold), ALWAYS),
                ("Farewell.", then_leave(go), ALWAYS)])

    def turn_cold():
        s.flag(COLD, 1)
        s.say("Then go and tell them, and see whom they believe. I have nothing more to say to you.")
        s.page()

    def cold():
        s.say("I have nothing to say to you. Go and tell your templars.")
        s.menu([("Here's 50 ceramic, as an apology.", then_leave(paid), ("expr", [MONEY, ">=", ("n", 50)])),
                ("We're all slaves. Let's be friends.", then_leave(plead), ALWAYS),
                ("Farewell.", then_leave(lambda: None), ALWAYS)])

    def plead():
        s.when(("op", gpl.Op(0, gpl.ABILITY_CHECK, [ACTOR, ("n", 1), ("n", CHA)])), won_over, not_won)

    def paid():
        s.op(0x0C, ("n", -50))
        s.say("Coin that rings. That's an apology I'll take.")
        s.page()
        s.call("respect")

    def won_over():
        s.say("Hm. Fine. We're all slaves here.")
        s.page()
        s.call("respect")

    def not_won():
        s.say("Words are cheap in the pens.")
        s.page()

    # (every menu in a subroutine of its own: one laid out in the greeting's "if"s hung the game
    # when a reply went back to it, "Who are you?")
    for name, body in (("first", first), ("cold", cold), ("respect", respect), ("friend", friend),
                       ("accused", accused)):
        s.sub(name, body)

    def meeting():
        s.say("New faces in the pens. Mind the dust: the ground in here died the day they chained me "
              "to it. What do you want?")
        s.flag(MET, 1)

    s.op(BEGIN)  # (every script of the game's opens so; its talk commands start after it)
    s.op(0x54, ("n", PORTRAIT))
    s.when(_is(cold_, 1), lambda: s.call("cold"),
           lambda: s.when(_is(friendly, 1),
                          lambda: (s.say("Back again? Keep your voice down."), s.call("friend")),
                          lambda: (s.when(_is(met, 1), lambda: s.say("You again. Well?"), meeting),
                                   s.call("first"))))
    return s.bytes()


# ---------------------------------------------------------------------------------------------
# The scripts file: his conversation, and the command that runs it

TALK = 0x6E  # (place in a script, script, object): what talking to the object runs
END = 0x31


def with_talk(master: bytes, field_types: bytes = b"") -> bytes:
    """The pens' master script with Kalzith's talk command (once), last, just before its end: the
    script's "if" at 302 skips on to an offset in it, so nothing of the game's may move (his
    command put in after the other talk commands sent that skip into the middle of a command,
    and Merzol, the doors, the gate and the water were lost to whatever it read there)."""
    ops = gpl.decode(master, field_types)
    talk = gpl.encode_op((TALK, [("n", START), ("n", SCRIPT), ("n", -OBJECT)]))
    if talk in master:
        return master
    if ops[-1].code != END:
        raise gpl.ScriptError("the master script doesn't end as expected")
    end = ops[-1].at
    return master[:end] + talk + master[end:]


ENTRY = struct.Struct("<HHH")  # GPLI: (entry number, place in the script, script), numbered from 0
ENTRIES = ("GPLI", 1)


def with_entry(entries: bytes) -> bytes:
    """The game's table of script entry points with his talk's (once). A save keeps each talk
    command as its entry's number, and loading turns the number back into place and script: one
    not in the table is saved as 0 and comes back as entry 0, a dead one."""
    table = [ENTRY.unpack_from(entries, i) for i in range(0, len(entries) - ENTRY.size + 1, ENTRY.size)]
    if any(e[1:] == (START, SCRIPT) for e in table):
        return entries
    return entries + ENTRY.pack(max((e[0] for e in table), default=-1) + 1, START, SCRIPT)


def script_chunks(gpldata: bytes) -> Dict[Tuple[str, int], bytes]:
    """For the Ledger's copy of GPLDATA: his conversation, and the master script running it."""
    chunks = read_gff(gpldata)
    if ("MAS ", MASTER) not in chunks:
        return {}
    field_types = next((v for k, v in chunks.items() if k[0] == "GPLX"), b"")[gpl.FIELD_TYPES_AT:]
    out = {("GPL ", SCRIPT): conversation(), ("MAS ", MASTER): with_talk(chunks[("MAS ", MASTER)], field_types)}
    if ENTRIES in chunks:
        out[ENTRIES] = with_entry(chunks[ENTRIES])
    face = portrait_chunk(chunks)
    if face and ("PORT", PORTRAIT) not in chunks:
        out[("PORT", PORTRAIT)] = face
    return out


def region_chunks(rgn: bytes) -> Dict[Tuple[str, int], bytes]:
    """For the Ledger's copy of RGN29.GFF: the pens' entity table with him in it."""
    chunks = read_gff(rgn)
    if ("ETAB", ETAB_ID) not in chunks:
        return {}
    return {("ETAB", ETAB_ID): with_entity(chunks[("ETAB", ETAB_ID)])}


# ---------------------------------------------------------------------------------------------
# His stock, given once a game

CREATURES_SEEN = 128  # creature records searched for him (the pens have 34)


def stock(gd, cats_grace: bool) -> List[str]:
    """In the pens, once a game, Kalzith gets his scrolls (Cat's Grace only with its rule on);
    the game's flag STOCKED marks it done (a save keeps it, a new game starts without it). The
    scrolls given, by name."""
    from . import npcitems
    if gd.region() != REGION or gd.flag(STOCKED):
        return []
    # (found by name among the region's creatures: not among the first 256 objects, where he
    # is not - the pens' last, past the 256th)
    table = gd.creatures(CREATURES_SEEN)
    name = NAME.encode("ascii") + b"\0"
    for index in range(game.PARTY_SIZE, len(table) // game.CREATURE_SIZE):
        at = index * game.CREATURE_SIZE
        if table[at + game.CREATURE_NAME:at + game.CREATURE_NAME + len(name)] != name:
            continue
        out = [name_ for k, (spell, name_, price) in enumerate(SCROLLS)
               if (cats_grace or spell != game.FLAMING_SPHERE)
               and npcitems.add_to(gd, index, scroll(spell, price, k))]
        gd.set_flag(STOCKED)
        return out
    return []


def mend(gd) -> int:
    """His scrolls stocked before SCROLL_SPELL_FROM (each teaching the spell before its own),
    wherever they are now (his things, the party's, the ground: each scroll is its own object),
    made to teach their own. How many were."""
    from . import ring
    it = ring.Items(gd)
    want = {-(SCROLL_OBJECT + k): spell + SCROLL_SPELL_FROM for k, (spell, _, _) in enumerate(SCROLLS)}
    done = set()
    for thing in range(ring.THING_COUNT):
        for index, rec in it.chain(thing):
            spell = want.get(struct.unpack_from("<h", rec, ITEM_OBJECT)[0])
            if spell is None or index in done:
                continue
            done.add(index)
            if struct.unpack_from("<H", rec, ITEM_SPELL)[0] != spell or rec[ITEM_SPELL_AGAIN] != spell:
                at = it.items + index * game.ITEM_SIZE
                gd.guest.write(at + ITEM_SPELL, struct.pack("<H", spell))
                gd.guest.write(at + ITEM_SPELL_AGAIN, bytes([spell]))
            else:
                done.discard(index)
    return len(done)


# ---------------------------------------------------------------------------------------------
# The copies

def _write(source: str, dest: str, added) -> None:
    import os
    from .icons import with_chunks
    with open(source, "rb") as f:
        data = f.read()
    out = with_chunks(data, added(data))
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(out)
    os.replace(tmp, dest)


def write_scripts(source: str, dest: str) -> None:
    """The game's GPLDATA.GFF (SOURCE, only read) with Kalzith's conversation, to DEST."""
    _write(source, dest, script_chunks)


def write_region(source: str, dest: str) -> None:
    """The game's RGN29.GFF (SOURCE, only read) with Kalzith in his pen, to DEST."""
    _write(source, dest, region_chunks)
