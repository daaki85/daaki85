"""What the game knows about a monster that it never shows: what hurts it, what doesn't, what
its hits do besides damage.

From DSUN.EXE's damage code:

* Every creature record has a kind (a word at +16h: 0 for people, other numbers for the
  monster kinds). A table at MONSTER_KINDS_SEG gives each kind a dword of properties (bits
  the code asks about one at a time) and a resistance class.
* A resistance class is up to four rules, each a mask of damage kinds and the percent of the
  damage the creature takes when a hit has any of those kinds. The largest percent that
  applies counts; with none, the creature takes it all.
* Every hit has damage kinds: a spell's from its record, a weapon's from its item type
  (crushing, slashing or piercing), plus bits for how magical the weapon is (+1 or better,
  +2 or better, +3 or better). So "0% from crushing, slashing and piercing, 100% from +1 or
  better" is a monster only magical weapons hurt.
* Undead (race 9 on the character sheet) take nothing from poison and draining, and mind-
  affecting spells and charms and holds don't work on them.
"""

import struct
from typing import Dict, List, NamedTuple, Optional, Tuple

CREATURE_KIND = 0x16  # word: the monster's kind (0 for people)
MONSTER_KINDS_SEG = 0x3E45  # from the load segment
KIND_COUNT = 42
KIND_PROPERTIES_OFF = 0x00  # dword per kind
KIND_CLASS_OFF = 0xA8  # byte per kind: its resistance class (0: none)
CLASS_MASKS_OFF, CLASS_PERCENTS_OFF, CLASS_SIZE, CLASS_RULES = 0xD2, 0xDA, 12, 4
CLASS_COUNT = 16
UNDEAD_RACE = 9

# damage kinds (the word at +1Ah of a spell record, and what a weapon's hit carries)
POISON, FIRE, COLD, CRUSHING, SLASHING, PIERCING = 0x1, 0x2, 0x4, 0x8, 0x10, 0x20
ACID, ELECTRICITY, DRAINING, MAGIC, PSIONIC, DEATH = 0x40, 0x80, 0x100, 0x200, 0x400, 0x800
PLUS1, PLUS2, PLUS3 = 0x1000, 0x2000, 0x8000  # a weapon's magic (+3 also for Disintegrate)
WEAPON_KINDS = ((CRUSHING, "crushing"), (SLASHING, "edged"), (PIERCING, "pointed"))
# what spells and powers do, as the game's own spells carry them (0x200: a spell)
OTHER_KINDS = ((POISON | MAGIC, "poison"), (FIRE | MAGIC, "fire"), (COLD | MAGIC, "cold"),
               (ELECTRICITY | MAGIC, "electricity"), (ACID | MAGIC, "acid"),
               (DRAINING | MAGIC, "draining"), (PSIONIC, "psionic attacks"), (DEATH | MAGIC, "death spells"))

# property bits, as the damage and effect code uses them
PROPERTY_TEXT = {
    0: "unaffected by spells left on the ground (fogs, clouds, walls, Web, Grease...)",
    1: "unaffected by spells left on the ground (fogs, clouds, walls, Web, Grease...)",
    5: "can't be charmed or held",
    9: "not held by Grease, Web, Entangle, Solid Fog, Quicksand or walls",
    21: "unaffected by Wall of Fog",
}
# its hits cast one of the monsters' powers on the target as well
SPECIAL_ATTACKS = {
    2: "2d6 cold", 3: "paralysis", 4: "2d6 acid", 13: "poison (10 damage)", 14: "poison (30 damage)",
    15: "deadly poison", 16: "20 acid", 25: "disease (1 hit in 10)", 24: "a special touch",
}
# the short forms for the game's small Look box
SHORT_KINDS = {"poison": "POISON", "fire": "FIRE", "cold": "COLD", "electricity": "ELEC", "acid": "ACID",
               "draining": "DRAIN", "psionic attacks": "PSI", "death spells": "DEATH"}


class Rule(NamedTuple):
    mask: int
    percent: int


def damage_percent(rules: List[Rule], kinds: int) -> int:
    """The percent of a hit's damage a creature with these rules takes, as the game works it
    out: the largest percent among the rules whose mask the hit's kinds touch, else 100."""
    best = -1
    for rule in rules:
        if rule.mask & kinds and rule.percent > best:
            best = rule.percent
    return 100 if best < 0 else best


def weapon_kinds(kind: int, plus: int) -> int:
    """The damage kinds of a weapon's hit: its own kind and its magic."""
    return kind | (PLUS1 if plus >= 1 else 0) | (PLUS2 if plus >= 2 else 0) | (PLUS3 if plus >= 3 else 0)


class Defences(NamedTuple):
    weapon_plus: int  # the least plus a weapon needs to hurt it (0: any, None-like 4: none do)
    weapons_immune: List[str]  # weapon kinds that never hurt it, whatever their plus ("crushing")
    weapons_half: bool  # non-magical weapons do half
    immune: List[str]  # other damage it takes none of ("fire")
    half: List[str]  # other damage it takes half of
    notes: List[str]  # other things its properties do
    special: List[str]  # what its hits do besides damage
    undead: bool


def defences(rules: List[Rule], properties: int, undead: bool) -> Defences:
    """What a monster's resistance rules and properties come to."""
    # weapons: the least plus that does any damage, for each kind of weapon
    need = {}
    for bit, name in WEAPON_KINDS:
        need[name] = next((plus for plus in range(4) if damage_percent(rules, weapon_kinds(bit, plus)) > 0), 4)
    immune_kinds = [name for name, plus in need.items() if plus == 4]
    hurting = [plus for plus in need.values() if plus < 4]
    weapon_plus = min(hurting) if hurting else 0
    if immune_kinds and len(immune_kinds) == len(need):  # nothing hurts it: say so once
        weapon_plus = 4
    half = all(damage_percent(rules, weapon_kinds(bit, 0)) == 50 for bit, _ in WEAPON_KINDS)
    immune, halved = [], []
    for kinds, name in OTHER_KINDS:
        pct = damage_percent(rules, kinds)
        if undead and kinds & (POISON | DRAINING):
            pct = 0
        if pct == 0:
            immune.append(name)
        elif pct < 100:
            halved.append(name)
    notes = []
    for bit, text in sorted(PROPERTY_TEXT.items()):
        if properties & (1 << bit) and text not in notes:
            notes.append(text)
    if undead:
        notes.insert(0, "undead: mind-affecting spells, charms and holds don't work on it")
    special = [text for bit, text in sorted(SPECIAL_ATTACKS.items()) if properties & (1 << bit)]
    return Defences(weapon_plus, [] if weapon_plus == 4 else immune_kinds, half, immune, halved,
                    notes, special, undead)


def describe(d: Defences) -> List[str]:
    """Sentences for the Ledger and the game's dialogue window."""
    out = []
    if d.weapon_plus == 4:
        out.append("Weapons can't hurt it.")
    elif d.weapon_plus:
        out.append(f"Only +{d.weapon_plus} or better weapons hurt it.")
    if d.weapons_immune:
        out.append(f"{' and '.join(d.weapons_immune).capitalize()} weapons can't hurt it.")
    if d.weapons_half:
        out.append("Half damage from non-magical weapons.")
    if d.immune:
        out.append(f"Immune to {', '.join(d.immune)}.")
    if d.half:
        out.append(f"Half damage from {', '.join(d.half)}.")
    out += [note[0].upper() + note[1:] + "." for note in d.notes]
    if d.special:
        out.append(f"Its hits also bring {', '.join(d.special)}.")
    return out


def weapon_reason(d: Defences) -> Optional[str]:
    """Why a weapon's hit may do less than its dice, if the monster's defences say (else None)."""
    if d.weapon_plus == 4:
        return "weapons can't hurt it"
    if d.weapon_plus:
        return f"only +{d.weapon_plus} or better weapons hurt it"
    if d.weapons_immune:
        return f"{' and '.join(d.weapons_immune)} weapons can't hurt it"
    if d.weapons_half:
        return "non-magical weapons do half"
    return None


def creature_defences(gd, tables: "MonsterTables", creature: int) -> Optional[Defences]:
    """A creature's defences, from its record's kind and its sheet's race (None: unreadable)."""
    rec, sheet = gd.creature(creature), gd.sheet(creature)
    if len(rec) < 0x3A or len(sheet) < 0x47:
        return None
    return tables.defences(struct.unpack_from("<H", rec, CREATURE_KIND)[0], sheet[0x18] == UNDEAD_RACE)


def short_line(d: Defences, width: int = 15) -> str:
    """The most important defence in a few capitals, for the game's Look box."""
    if d.weapon_plus == 4:
        return "NO WEAPON HURTS"
    if d.weapon_plus:
        return f"NEEDS +{d.weapon_plus} WEAPON"
    if d.weapons_immune:
        return ("NO " + "/".join(k.upper()[:5] for k in d.weapons_immune))[:width]
    if d.immune:
        text = "IMM " + " ".join(SHORT_KINDS.get(k, k.upper()) for k in d.immune)
        return text if len(text) <= width else text[:width].rsplit(" ", 1)[0]
    if d.weapons_half:
        return "HALF FROM WPNS"
    if d.undead:
        return "UNDEAD"
    return ""


class MonsterTables:
    """The kinds table, read once from the running game (it's filled when the game starts)."""

    def __init__(self, read, load_seg: int):
        base = (load_seg + MONSTER_KINDS_SEG) * 16
        data = read(base, CLASS_MASKS_OFF + CLASS_SIZE * CLASS_COUNT)
        self.properties = list(struct.unpack_from(f"<{KIND_COUNT}I", data, KIND_PROPERTIES_OFF))
        self.classes = list(data[KIND_CLASS_OFF:KIND_CLASS_OFF + KIND_COUNT])
        self.rules: Dict[int, List[Rule]] = {}
        for c in range(1, CLASS_COUNT):
            masks = struct.unpack_from(f"<{CLASS_RULES}H", data, CLASS_MASKS_OFF + c * CLASS_SIZE)
            pcts = data[CLASS_PERCENTS_OFF + c * CLASS_SIZE:CLASS_PERCENTS_OFF + c * CLASS_SIZE + CLASS_RULES]
            self.rules[c] = [Rule(m, p) for m, p in zip(masks, pcts) if m]

    def defences(self, kind: int, undead: bool) -> Defences:
        if not 0 <= kind < KIND_COUNT:
            return defences([], 0, undead)
        return defences(self.rules.get(self.classes[kind], []), self.properties[kind], undead)


def monster_lines(gd, tables: MonsterTables, creature: int, ac: Optional[int]) -> Tuple[List[str], List[str]]:
    """(the Look box's three short lines, the full description) for a creature."""
    rec = gd.creature(creature)
    sheet = gd.sheet(creature)
    if len(rec) < 0x3A or len(sheet) < 0x47:
        return [], []
    hp = struct.unpack_from("<h", rec, 0)[0]
    kind = struct.unpack_from("<H", rec, CREATURE_KIND)[0]
    max_hp = struct.unpack_from("<h", sheet, 0x08)[0]
    thac0 = rec[0x1F]
    mr = sheet[0x29]
    attacks = sheet[0x2A]
    undead = sheet[0x18] == UNDEAD_RACE
    d = tables.defences(kind, undead)
    ac_text = str(ac) if ac is not None else str(struct.unpack_from("b", sheet, 0x27)[0])
    short = [f"HP {hp}/{max_hp} AC {ac_text}", f"THAC0 {thac0}" + (f" MR {mr}" if mr else "")]
    line = short_line(d)
    if line:
        short.append(line)
    per_round = f"{attacks // 2}" if attacks % 2 == 0 else f"{attacks}/2"  # the sheet keeps it doubled
    head = f"{gd.creature_name(creature)}: HP {hp}/{max_hp}, AC {ac_text}, THAC0 {thac0}"
    if attacks:  # monsters' sheets leave it 0: their attacks come from elsewhere
        head += f", {per_round} attack{'s' if attacks != 2 else ''} a round"
    full = [head + (f", magic resistance {mr}%" if mr else "") + "."]
    full += describe(d)
    return short, full
