"""Kalzith, a defiler in the slave pens who sells spell scrolls to a party that treats him well.

He is the defiler the party fights in the arena at the start of the game, dragged back to the pens
afterwards and kept chained in an empty pen. He secretly scribes spells on scraps of hide, to buy a
guard's blind eye; a preserver can learn from them (the game's own scrolls: right-click one, click
its spell). Insult him or threaten to report him and he won't trade until the party makes amends:
50 ceramic pieces, or a Charisma check.

He is the game's own kind of person, added to the Ledger's copies of three of its files (the game
folder is never changed; DSCLOG has the game open the copies):

  * SEGOBJEX.GFF: object OBJECT, his OJFF (a person's, with the arena Defiler's picture) and RDFF (a slave's record,
    Dinos's, with his name and a defiler's class);
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
from typing import Dict, List, Optional, Tuple

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

# his state, in two of the game's global flags (it uses 1-755): met him; 1 friendly, 2 cold
MET, ATTITUDE = 760, 761
FRIENDLY, COLD = 1, 2

# The scrolls: (spell, its name, price in ceramic pieces). Cat's Grace is the game's Flaming Sphere
# (14) under the companion's rule, so it is sold only while the rule is on.
SCROLLS = ((8, "Magic Missile", 100), (4, "Color Spray", 100), (12, "Blur", 250),
           (game.FLAMING_SPHERE, "Cat's Grace", 250), (32, "Lightning Bolt", 500), (29, "Haste", 500))
SCROLL_TYPE = 0x60  # the game's spell scrolls (its objects 1400-1418)
SCROLL_TEMPLATE = "88fa010000000000000060000000000105ff7f0000"  # its scroll of spell 1 (object 1400)
ITEM_SPELL, ITEM_SPELL_AGAIN, ITEM_VALUE = 0x02, 0x0F, 0x06


def scroll(spell: int, price: int) -> bytes:
    """A spell scroll item (the game's own kind) teaching SPELL, priced PRICE."""
    rec = bytearray.fromhex(SCROLL_TEMPLATE)
    struct.pack_into("<H", rec, ITEM_SPELL, spell)
    rec[ITEM_SPELL_AGAIN] = spell
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
    """The pens' entity table with Kalzith in his pen (once), kept in order down the map."""
    entries = [ENTITY.unpack_from(etab, i) for i in range(0, len(etab) - ENTITY.size + 1, ENTITY.size)]
    if any(e[4] == -OBJECT for e in entries):
        return etab
    entries.append((PEN[0], PEN[1], 0, ENTITY_FLAGS, -OBJECT))
    entries.sort(key=lambda e: e[1])
    return b"".join(ENTITY.pack(*e) for e in entries)


# ---------------------------------------------------------------------------------------------
# His conversation

SPEAKS = 115  # the dialogue window's lines: his words (no narration: the game's talks have little)
LINE = 60  # the game's lines are no longer than this
REPLY = 40  # nor its replies (the reply window cuts a longer one off)
TITLE = ("var", 0x86, 1)  # a reply menu's title, as the game's own (the speaker)
MORE, CLEAR = ("var", 0x86, 2), ("var", 0x86, 3)  # wait for a click, then clear the window
MONEY = ("var", 0x89, 42)  # the party's ceramic pieces
ACTOR = ("var", 0x89, 37)  # the character talking (who rolls an ability check)
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
    """A script built from commands and labels; jumps to labels are filled in once laid out.

    Menus are the game's: a loop showing the menu until a local flag (DONE) is set, each reply
    a subroutine ending in a return (15h) to the loop. A reply that leaves the menu sets DONE and
    NEXT (where the talk goes on) and returns; after the loop, the talk goes on at NEXT's place."""

    def __init__(self):
        self.items: List = []
        self.shown = 0  # lines in the window since it was last cleared (as laid out)
        self.after: Dict[str, List[str]] = {}  # menu: the places its replies may lead on to

    def op(self, code: int, *args) -> None:
        self.items.append((code, list(args)))

    def label(self, name: str, mark: bool = True) -> None:
        self.items.append(name)
        if mark:
            self.op(0x67)  # (the game marks each place a jump lands; not a menu's loop or replies)

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

    def goto(self, name: str) -> None:
        self.op(0x3F, ("label", name))

    def unless(self, test, name: str) -> None:
        """Go on if TEST holds, else to NAME."""
        self.op(0x18, test)
        self.op(0x3E, ("label", name))

    def set(self, var: int, value: int) -> None:
        self.op(0x16, ("n", value), ("var", 14, var))

    def menu(self, name: str, replies: List[Tuple[str, str, object]], leads_to: List[str]) -> None:
        """Menu NAME (the replies' subroutines are labelled f"{NAME}:{target}"); when it is
        left, the talk goes on at the one of LEADS_TO its reply chose (by number in NEXT)."""
        self.after[name] = leads_to
        self.set(DONE, 0)
        self.label(f"{name}:loop", mark=False)
        self.op(0x18, ("expr", [("var", 0x8E, DONE), "==", ("n", 0)]))
        self.op(0x63, ("label", f"{name}:out"))
        self.op(0x48, {"before": [], "title": TITLE, "replies": [
            {"text": ("str", f"  {text}"), "goto": ("label", f"{name}:{target}"), "if": shown,
             "before": [], "after": []} for text, target, shown in replies]})
        self.op(0x64, ("label", f"{name}:loop"))
        self.label(f"{name}:out")
        for k, place in enumerate(leads_to):
            self.unless(("expr", [("var", 0x8E, NEXT), "!=", ("n", k)]), place)
        self.op(0x31)  # (none chosen: can't be)

    def reply(self, menu: str, target: str) -> None:
        """The subroutine for a reply of MENU: the window cleared for what it says."""
        self.label(f"{menu}:{target}", mark=False)
        self.clear()

    def back(self) -> None:
        """Back to the menu, which shows again."""
        self.op(0x15)
        self.shown = 0

    def leave(self, menu: str, place: str) -> None:
        """Leave the menu, the talk going on at PLACE (one of its LEADS_TO)."""
        self.set(NEXT, self.after[menu].index(place))
        self.set(DONE, 1)
        self.back()

    def end(self) -> None:
        self.page()
        self.op(0x31)

    def bytes(self) -> bytes:
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
        at, pos = {}, 0
        for item in self.items:
            if isinstance(item, str):
                at[item] = pos
            else:
                pos += len(gpl.encode_op(fill(item, {k: 0 for k in self._labels()})))
        return b"".join(gpl.encode_op(fill(item, at)) for item in self.items if not isinstance(item, str))

    def _labels(self) -> List[str]:
        return [i for i in self.items if isinstance(i, str)]


ALWAYS = ("n", 1)
DONE, NEXT = 1, 2  # the script's locals (as the game's merchants use 1 for the menu loop): a menu left; where the talk goes on
WINDOW = 4  # the lines the dialogue window shows


def conversation() -> bytes:
    """Kalzith's conversation (script SCRIPT)."""
    s = _Script()
    s.op(BEGIN)  # (every script of the game's opens so; its talk commands start after it)
    s.op(0x54, ("n", PORTRAIT))
    s.unless(("expr", [("var", 0x8D, ATTITUDE), "!=", ("n", COLD)]), "cold")
    s.unless(("expr", [("var", 0x8D, ATTITUDE), "!=", ("n", FRIENDLY)]), "friend again")
    s.unless(("expr", [("var", 0x8D, MET), "!=", ("n", 1)]), "again")
    s.say("Ah. The arena's champions. You broke my spell before I could finish it. Come to "
          "finish me? Mind the dust: the ground in here died the day they chained me to it.")
    s.op(0x16, ("n", 1), ("var", 13, MET))
    s.goto("first")

    s.label("again")
    s.say("You again. Well?")
    s.label("first")
    s.menu("first", [("You fought well. No hard feelings.", "respect", ALWAYS),
                     ("You're a defiler. You kill the land.", "accused", ALWAYS),
                     ("Who are you?", "who", ALWAYS),
                     ("Farewell.", "bye", ALWAYS)],
           ["respect", "accused", "go"])
    s.reply("first", "respect")
    s.leave("first", "respect")
    s.reply("first", "accused")
    s.leave("first", "accused")
    s.reply("first", "who")
    s.say("Kalzith. Once a sorcerer's apprentice in Draj, now Pehtucl's prize slave. The templars "
          "like a defiler in the arena: the crowd loves to watch one burn. Afterwards they chain "
          "me here, where the ground's already dead.")
    s.back()
    s.reply("first", "bye")
    s.leave("first", "go")

    s.label("respect")
    s.clear()
    s.op(0x16, ("n", FRIENDLY), ("var", 13, ATTITUDE))
    s.say("Hm. Slaves with manners. Rarer than water. Keep your voice down.")
    s.page()
    s.say("I have something you might want. I scribe spells on scraps of hide, at night. A "
          "preserver could learn from them: the magic on the page doesn't care how you draw your "
          "power.")
    s.page()
    s.say("And I need ceramic for a guard who can look the other way.")
    s.goto("friend")

    s.label("friend again")
    s.say("Back again? Keep your voice down.")
    s.label("friend")
    s.menu("friend", [("Show us what you have.", "shop", ALWAYS),
                      ("Why would a defiler help a preserver?", "why", ALWAYS),
                      ("Isn't this dangerous for you?", "danger", ALWAYS),
                      ("Farewell.", "bye", ALWAYS)],
           ["see you"])
    s.reply("friend", "shop")
    s.say("Quietly, now. One of each, and they're not cheap.")
    s.page()
    s.op(0x24, ("n", -OBJECT))
    s.say("Learn them well, and burn the hide when you're done.")
    s.back()
    s.reply("friend", "why")
    s.say("Because a preserver's coin buys the same bribe. And because I'm tired of being the "
          "only one in the pens the others fear.")
    s.back()
    s.reply("friend", "danger")
    s.say("Everything is dangerous for me. Pehtucl would flay me for this. So keep it quiet.")
    s.back()
    s.reply("friend", "bye")
    s.leave("friend", "see you")
    s.label("see you")
    s.clear()
    s.say("Come back when you've earned some coin.")
    s.end()

    s.label("accused")
    s.clear()
    s.say("And the templars kill slaves with every order. We do what Athas lets us.")
    s.menu("accused", [("Fair enough. I spoke too quickly.", "sorry", ALWAYS),
                       ("We'll tell the templars about you.", "threat", ALWAYS),
                       ("Farewell.", "bye", ALWAYS)],
           ["respect", "turn cold", "go"])
    s.reply("accused", "sorry")
    s.leave("accused", "respect")
    s.reply("accused", "threat")
    s.leave("accused", "turn cold")
    s.reply("accused", "bye")
    s.leave("accused", "go")

    s.label("turn cold")
    s.clear()
    s.op(0x16, ("n", COLD), ("var", 13, ATTITUDE))
    s.say("Then go and tell them, and see whom they believe. I have nothing more to say to you.")
    s.end()

    s.label("cold")
    s.say("I have nothing to say to you. Go and tell your templars.")
    s.menu("cold", [("Here's 50 ceramic, as an apology.", "pay", ("expr", [MONEY, ">=", ("n", 50)])),
                    ("We're all slaves. Let's be friends.", "plead", ALWAYS),
                    ("Farewell.", "bye", ALWAYS)],
           ["paid", "won over", "not won", "gone"])
    s.reply("cold", "pay")
    s.leave("cold", "paid")
    s.reply("cold", "plead")
    s.unless(("op", gpl.Op(0, gpl.ABILITY_CHECK, [ACTOR, ("n", 1), ("n", CHA)])), "cold:plead fails")
    s.leave("cold", "won over")
    s.label("cold:plead fails")
    s.leave("cold", "not won")
    s.reply("cold", "bye")
    s.leave("cold", "gone")

    s.label("paid")
    s.clear()
    s.op(0x0C, ("n", -50))
    s.say("Coin that rings. That's an apology I'll take.")
    s.page()
    s.goto("respect")

    s.label("won over")
    s.clear()
    s.say("Hm. Fine. We're all slaves here.")
    s.page()
    s.goto("respect")

    s.label("not won")
    s.clear()
    s.say("Words are cheap in the pens.")
    s.end()

    s.label("go")
    s.clear()
    s.say("Go, then.")
    s.end()

    s.label("gone")
    s.op(0x31)
    return s.bytes()


# ---------------------------------------------------------------------------------------------
# The scripts file: his conversation, and the command that runs it

TALK = 0x6E  # (place in a script, script, object): what talking to the object runs
END = 0x31


def with_talk(master: bytes, field_types: bytes = b"") -> bytes:
    """The pens' master script with Kalzith's talk command after the others' (once), as the game
    sets its own: all of them first, before its other commands."""
    ops = gpl.decode(master, field_types)
    talk = gpl.encode_op((TALK, [("n", START), ("n", SCRIPT), ("n", -OBJECT)]))
    if talk in master:
        return master
    if ops[-1].code != END:
        raise gpl.ScriptError("the master script doesn't end as expected")
    after = next(o for o in ops if o.code != TALK)  # (the end, at the latest)
    return master[:after.at] + talk + master[after.at:]


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

def _has_scroll(gd, it, index: int, spell: int) -> bool:
    lists = [struct.unpack_from("<h", gd.creature(index), o)[0] for o in game.CREATURE_ITEM_LISTS]
    return any(struct.unpack_from("<H", data, game.ITEM_TYPE)[0] == SCROLL_TYPE
               and struct.unpack_from("<H", data, ITEM_SPELL)[0] == spell
               for t in lists for _, data in it.chain(t))


CREATURES_SEEN = 128  # creature records searched for him (the pens have 34)


def stock(gd, given: set, cats_grace: bool) -> List[str]:
    """In the pens, Kalzith gets those of his scrolls not yet given this game (GIVEN: a key for
    each, updated; Cat's Grace only with its rule on). The scrolls given, by name."""
    from . import npcitems, ring
    if gd.region() != REGION:
        return []
    out = []
    # (found by name among the region's creatures: not among the first 256 objects, where he
    # is not - the pens' 304th)
    table = gd.creatures(CREATURES_SEEN)
    name = NAME.encode("ascii") + b"\0"
    for index in range(game.PARTY_SIZE, len(table) // game.CREATURE_SIZE):
        at = index * game.CREATURE_SIZE
        if table[at + game.CREATURE_NAME:at + game.CREATURE_NAME + len(name)] != name:
            continue
        it = ring.Items(gd)
        for spell, name, price in SCROLLS:
            if spell == game.FLAMING_SPHERE and not cats_grace:
                continue
            key = f"{gd.creature_name(0)}|kalzith:{spell}"
            if key in given:
                continue
            if _has_scroll(gd, it, index, spell):
                given.add(key)
                continue
            if npcitems.add_to(gd, index, scroll(spell, price)):
                given.add(key)
                out.append(name)
                it = ring.Items(gd)
    return out


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
