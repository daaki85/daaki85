"""Where Shattered Lands (GOG release, DSUN.EXE) keeps things in memory.

The game is a 16-bit Borland C++ program. Its data segment (DS) starts with
Borland's copyright string at DS:0004, which makes DS easy to find; the
creature and character-sheet tables are reached through far pointers in DS.

Other data lives in segments at fixed distances from the load segment (DS -
0x4356). The game's overlaid code names these segments with different
numbers; the real ones are given here.
"""

import re
import string
import struct
from typing import Dict, List, NamedTuple, Optional, Tuple

from .guestmem import GuestMemory

CONVENTIONAL_AND_UPPER = 0x110000  # real-mode programs live below this

BORLAND_SIG = b"Borland C++ - Copyright 1991 Borland Intl."
BORLAND_SIG_OFFSET = 4  # the string's offset in DS
DGROUP = 0x4356  # DS relative to the load segment

CREATURES_PTR = 0x1665  # DS offset of a far pointer to the creature table
SHEETS_PTR = 0x1661  # DS offset of a far pointer to the character sheet table
ITEMS_PTR = 0x165D  # far pointer to the item table (21-byte records)
ITEM_TYPES_PTR = 0x1669  # far pointer to the item type table (20-byte records)
ITEM_NAMES_PTR = 0x166D  # far pointer to the item names (GPLDATA's NAME list, 25 bytes each)
DEX_AC = 0x07F6  # DS: AC adjustment for each DEX score (bytes)
DEX_INITIATIVE = 0x07DC  # DS: initiative adjustment for each DEX score (bytes)
DIFFICULTY = 0x11AE  # DS word: game difficulty (monsters get difficulty-1 to hit)
EFFECT_COUNT = 0x1E24  # DS word: number of active effects
SPELL_NAMES = 0x254E  # DS offset of the NUL-separated spell and psionic names
SPELL_NAMES_END = 0x2F00

CREATURE_SIZE = 0x3A
SHEET_SIZE = 0x47
ITEM_SIZE = 0x15
ITEM_TYPE_SIZE = 0x14
CREATURE_SHEET_INDEX = 0x04
CREATURE_THAC0 = 0x1F
CREATURE_SIDE = 0x1D  # creatures on the same side share this value
CREATURE_ABILITIES = 0x22
CREATURE_NAME = 0x28
PARTY_SIZE = 4  # the party are the first creatures in the table

# Segments relative to the load segment
COMBATANTS_SEG, COMBATANTS_OFF = 0x3972, 0xC36  # 3 bytes per combatant: kind (2 = creature), creature index
EFFECTS_SEG, EFFECTS_OFF = 0x3BF6, 0x106  # 10 bytes per active effect
# Each round, per creature (4 bytes each): the initiative score (-1 once it has
# acted) and the 0-199 roll that breaks ties
INITIATIVE_SEG, INITIATIVE_OFF = 0x37BD, 0xD9
# Wizard and cleric spells, 7 bytes each from id 1: level, ..., DS offset of the name (+5)
SPELL_INFO_OFF, SPELL_INFO_SIZE, SPELL_COUNT = 0x3FD33, 7, 137
# The spells' rules, 32 bytes each; the saving throw reads a flags word at +0Ah
# (0x86: the d20 is doubled) and a byte at +0Fh (bits 1-4: a save modifier,
# bits 5-7: the kind of save)
SPELLS_SEG, SPELLS_OFF, SPELL_SIZE = 0x3CB4, 0x40, 0x20
SHEET_MAGIC_RESISTANCE = 0x29
SHEET_XP, SHEET_XP_VALUE, SHEET_MAX_HP = 0x00, 0x04, 0x08  # a monster's sheet holds its XP value at +4
SHEET_RACE, SHEET_ABILITIES = 0x18, 0x1B
SHEET_CLASSES, SHEET_LEVELS, SHEET_BASE_AC = 0x21, 0x24, 0x27
# sheet +0x12: a word of flags, one bit per class the character has (druid 0x10, fighter
# 0x20, gladiator 0x40, preserver 0x80, psionicist 0x100, ranger 0x200, thief 0x400)
SHEET_FLAGS = 0x12
SHEET_FLAG_RANGER = 0x200
RACE_HALF_GIANT = 5
# Hit points per level (segment relative to the load segment): +10h + class = the class's
# group; group * 4 = (die, levels that roll it, fixed gain after that); +38h + CON = the
# least a roll counts for
LEVEL_HP_SEG = 0x40B1
ITEM_NAME_SIZE = 25
BROKEN_ITEM_TYPE = 0x6B  # what a broken weapon becomes

MATERIALS = ("Wooden", "Bone", "Stone", "Obsidian", "Metal", "Leather")
# Dark Sun's to-hit penalty for non-magical weapons of weaker materials (from the game's code)
MATERIAL_TO_HIT = {0: -3, 1: -1, 2: -2, 3: -2}
# The character sheet's saving throws, in order (the game's own grouping: Fireball, for
# one, is saved against with petrification/polymorph)
SAVE_NAMES = {1: "paralysis/poison/death", 2: "rod/staff/wand", 3: "petrification/polymorph",
              4: "breath weapon", 5: "spell"}

# Effect ids, as the game names them (1-based, from its table in DSUN.EXE)
EFFECT_NAMES = {
    1: "Acid", 2: "Improved AC", 3: "Berserk", 4: "Biofeedback", 5: "Blink", 7: "Blessed", 8: "Blind",
    9: "Brave", 10: "Charmed", 11: "Confused", 12: "Cursed", 13: "Diseased", 14: "Detect Traps",
    15: "Detect Invis", 16: "Enlarged", 17: "Afraid", 18: "Cloak of Fear", 19: "Feeblemind",
    20: "Fire Shield", 21: "Free Action", 22: "Hasted", 23: "Invisible", 24: "Invis to Undead",
    25: "Mirror Images", 26: "Englobed", 28: "Prot Missile", 29: "Prot Paralysis",
    30: "Synaptic Static", 31: "Low Resistance", 32: "Mind Bar", 33: "Can't Attack", 34: "Paralyzed",
    35: "Poisoned", 36: "Prot Cold", 37: "Prot Energy", 38: "Prot Evil", 39: "Prot Evil 10'",
    40: "Prot Fire", 41: "Prot Lightning", 42: "Neg Plane Prot", 43: "Gaze Reflection",
    44: "Spell Turning", 45: "Save penalty", 46: "Shielded", 47: "Slowed", 48: "Stoneskin",
    49: "Graft Weapon", 50: "No spell use", 51: "Stuck", 52: "Dispelling evil", 53: "Ironskin",
    55: "Blur", 56: "Spirit Armor", 57: "Barkskin", 58: "Displacement", 59: "Flesh Armor",
    60: "Magical Vestments", 61: "Animal Affinity", 62: "Body Weaponry", 63: "Strength Enhanced",
    64: "Strength Borrowed", 65: "Strength Lent", 66: "Adrenalin Control", 67: "Strength",
    68: "Weakened", 69: "Extra Hitpoints", 70: "Flame Blade", 71: "Spirit. Hammer", 72: "Shillelagh",
    73: "Prayer",
}

# What effects do, where the game's own code shows it (to-hit, AC and saving throws)
EFFECT_RULES = {
    2: "armour AC at most 6", 4: "AC -1", 7: "+1 to hit, +1 on saves", 8: "AC 4 worse",
    12: "-1 to hit", 16: "+10% melee damage per level of the spell",
    36: "+3 on saves against cold spells", 38: "AC -2 and +2 on saves against evil",
    40: "+3 on saves against fire spells", 41: "+4 on saves against lightning spells",
    45: "-1 on saves", 46: "AC 4 except from behind", 47: "-4 to hit, AC 4 worse", 49: "+1 to hit",
    52: "AC -7 against evil", 55: "attackers -2 to hit", 56: "armour AC at most 4, +3 on saves",
    57: "AC at most 6 - level/4, +1 on saves", 58: "AC -2", 59: "AC at most 10 - level",
    60: "AC 5, 1 better per 3 caster levels above 5", 63: "higher STR", 64: "higher STR", 67: "higher STR",
    68: "lower STR",
    73: "+1 to hit and saves for the caster's side, -1 for the other",
}

# AD&D 2e strength damage adjustments (Dark Sun has no exceptional strength). The
# game adds these after rolling melee damage; seen in play for STR 20 and 24.
STR_DAMAGE = {1: -4, 2: -2, 3: -1, 4: -1, 5: -1, 16: 1, 17: 1, 18: 2, 19: 7, 20: 8, 21: 9,
              22: 10, 23: 11, 24: 12, 25: 14}


SMALL_WORDS = {"of", "from", "to", "the", "and", "or", "in"}


def title(text: str) -> str:
    """'CONE OF COLD' -> 'Cone of Cold'."""
    words = string.capwords(text).split(" ")
    return " ".join(w.lower() if i and w.lower() in SMALL_WORDS else w for i, w in enumerate(words))


def find_data_segment(guest: GuestMemory, low: Optional[bytes] = None) -> Optional[int]:
    """The game's DS, or None if the game isn't running."""
    low = guest.read(0, CONVENTIONAL_AND_UPPER) if low is None else low
    for m in re.finditer(re.escape(BORLAND_SIG), low):
        base = m.start() - BORLAND_SIG_OFFSET
        if base % 16 == 0:
            return base // 16
    return None


def far_pointer(guest: GuestMemory, ds: int, offset: int) -> int:
    off, seg = struct.unpack("<HH", guest.read(ds * 16 + offset, 4))
    return seg * 16 + off


def party_records(guest: GuestMemory, ds: int) -> List[Tuple[Optional[int], Optional[int]]]:
    """(creature record, character sheet) addresses for each party slot."""
    creatures = far_pointer(guest, ds, CREATURES_PTR)
    sheets = far_pointer(guest, ds, SHEETS_PTR)
    result = []
    for slot in range(PARTY_SIZE):
        creature = creatures + slot * CREATURE_SIZE
        record = guest.read(creature, CREATURE_SIZE)
        if len(record) < CREATURE_SIZE or not record[CREATURE_NAME]:
            result.append((None, None))
            continue
        sheet_index = struct.unpack_from("<H", record, CREATURE_SHEET_INDEX)[0]
        result.append((creature, sheets + sheet_index * SHEET_SIZE))
    return result


# Effects that change initiative (effect id -> adjustment), from the game's code
INITIATIVE_EFFECTS = {8: -2, 22: 2, 47: -2}  # Blind, Hasted, Slowed


class Effect(NamedTuple):
    owner: int  # combatant id
    caster: int  # combatant id
    id: int


CLASS_NAMES = {1: "Cleric", 2: "Cleric", 3: "Cleric", 4: "Cleric", 5: "Druid", 6: "Druid", 7: "Druid",
               8: "Druid", 9: "Fighter", 10: "Gladiator", 11: "Preserver", 12: "Psionicist",
               13: "Ranger", 14: "Ranger", 15: "Ranger", 16: "Ranger", 17: "Thief"}


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


class LevelHp(NamedTuple):
    sides: int  # the hit die
    dice_levels: int  # levels up to this one roll it
    fixed: int  # hit points per level after that


class SpellRules(NamedTuple):
    doubles_roll: bool  # the saving throw's d20 counts double
    save_modifier: int  # added to every saving throw against the spell


class Weapon(NamedTuple):
    name: str
    count: int
    sides: int
    bonus: int
    plus: int
    material: int
    nonmagical_flag: bool  # item type flag that exempts it from material penalties

    def dice(self) -> str:
        bonus = self.bonus + self.plus
        return f"{self.count}d{self.sides}" + (f"{bonus:+d}" if bonus else "")


class GameData:
    """Lookups into the running game's memory for one session."""

    def __init__(self, guest: GuestMemory, ds: int):
        self.guest = guest
        self.ds = ds
        self.load_seg = ds - DGROUP

    def _word(self, offset: int) -> int:
        return struct.unpack("<h", self.guest.read(self.ds * 16 + offset, 2))[0]

    def creature(self, index: int) -> bytes:
        if not 0 <= index < 512:
            return b""
        return self.guest.read(far_pointer(self.guest, self.ds, CREATURES_PTR) + index * CREATURE_SIZE,
                               CREATURE_SIZE)

    def creature_name(self, index: int) -> str:
        rec = self.creature(index)
        name = rec[CREATURE_NAME:CREATURE_NAME + 16].split(b"\0", 1)[0].decode("cp437", "replace")
        return name or f"creature {index}"

    def party_signature(self) -> bytes:
        """The party's names, which change when a game is loaded (from the main menu, at least)."""
        return b"".join(self.creature(i)[CREATURE_NAME:CREATURE_NAME + 16] for i in range(PARTY_SIZE))

    def combatant_creature(self, combatant: int) -> Optional[int]:
        if not 0 <= combatant < 256:
            return None
        kind, index = struct.unpack("<Bh", self.guest.read(
            (self.load_seg + COMBATANTS_SEG) * 16 + COMBATANTS_OFF + combatant * 3, 3))
        return index if kind == 2 else None

    def combatants(self) -> Dict[int, int]:
        """{combatant: creature index} for every creature in the fight (or the area)."""
        data = self.guest.read((self.load_seg + COMBATANTS_SEG) * 16 + COMBATANTS_OFF, 256 * 3)
        out = {}
        for combatant in range(len(data) // 3):
            kind, index = struct.unpack_from("<Bh", data, combatant * 3)
            if kind == 2 and 0 <= index < 512:
                out[combatant] = index
        return out

    def creatures(self, count: int) -> bytes:
        """The first `count` creature records, in one read."""
        return self.guest.read(far_pointer(self.guest, self.ds, CREATURES_PTR), count * CREATURE_SIZE)

    def combatant_name(self, combatant: int) -> str:
        index = self.combatant_creature(combatant)
        return self.creature_name(index) if index is not None else "?"

    def difficulty(self) -> int:
        return self._word(DIFFICULTY)

    def effects(self) -> List[Effect]:
        count = self._word(EFFECT_COUNT)
        if not 0 <= count <= 400:
            return []
        data = self.guest.read((self.load_seg + EFFECTS_SEG) * 16 + EFFECTS_OFF, count * 10)
        return [Effect(*struct.unpack_from("<hh", data, i * 10), data[i * 10 + 6]) for i in range(count)]

    def spell_name(self, spell: int) -> str:
        if spell > SPELL_COUNT:  # monsters' powers, such as a paralysing touch
            return f"special attack {spell}"
        if 1 <= spell <= SPELL_COUNT:
            info = self.load_seg * 16 + SPELL_INFO_OFF + (spell - 1) * SPELL_INFO_SIZE
            name = struct.unpack("<H", self.guest.read(info + 5, 2))[0]
            if SPELL_NAMES <= name < SPELL_NAMES_END:
                text = self.guest.read(self.ds * 16 + name, 40).split(b"\0", 1)[0].decode("cp437", "replace")
                if text:
                    return title(text)
        return f"spell {spell}"

    def spell_rules(self, spell: int) -> Optional[SpellRules]:
        if not 0 <= spell < 256:
            return None
        rec = self.guest.read((self.load_seg + SPELLS_SEG) * 16 + SPELLS_OFF + spell * SPELL_SIZE, SPELL_SIZE)
        if len(rec) < SPELL_SIZE:
            return None
        nibble = (rec[0x0F] >> 1) & 0x0F
        return SpellRules(bool(struct.unpack_from("<H", rec, 0x0A)[0] & 0x86), nibble - 16 if nibble & 8 else nibble)

    def magic_resistance(self, combatant: int) -> Optional[int]:
        """The base magic resistance (percent) on a creature's character sheet."""
        index = self.combatant_creature(combatant)
        if index is None:
            return None
        sheet = struct.unpack_from("<H", self.creature(index), CREATURE_SHEET_INDEX)[0]
        return self.guest.read(far_pointer(self.guest, self.ds, SHEETS_PTR) + sheet * SHEET_SIZE
                               + SHEET_MAGIC_RESISTANCE, 1)[0]

    def item_name(self, name_index: int) -> str:
        if 0 <= name_index < 0x400:
            rec = self.guest.read(far_pointer(self.guest, self.ds, ITEM_NAMES_PTR) + name_index * ITEM_NAME_SIZE, 22)
            name = rec.split(b"\0", 1)[0].decode("cp437", "replace")
            if name:
                return name
        return f"item {name_index}"

    def sheet(self, creature: int) -> bytes:
        """The character sheet of a creature (party members and monsters alike)."""
        rec = self.creature(creature)
        if len(rec) < CREATURE_SIZE:
            return b""
        index = struct.unpack_from("<H", rec, CREATURE_SHEET_INDEX)[0]
        return self.guest.read(far_pointer(self.guest, self.ds, SHEETS_PTR) + index * SHEET_SIZE, SHEET_SIZE)

    def dex_ac(self, dex: int) -> int:
        """The game's AC adjustment for a DEX score."""
        if not 0 <= dex < 26:
            return 0
        return struct.unpack("b", self.guest.read(self.ds * 16 + DEX_AC + dex, 1))[0]

    def dex_initiative(self, dex: int) -> int:
        """The game's initiative adjustment for a DEX score."""
        if not 0 <= dex < 26:
            return 0
        return struct.unpack("b", self.guest.read(self.ds * 16 + DEX_INITIATIVE + dex, 1))[0]

    def initiative(self, count: int) -> List[Tuple[int, int]]:
        """(score, tie-break roll) for the first `count` creatures."""
        data = self.guest.read((self.load_seg + INITIATIVE_SEG) * 16 + INITIATIVE_OFF, count * 4)
        return [struct.unpack_from("<hh", data, i * 4) for i in range(len(data) // 4)]

    def level_hp_rule(self, cls: int) -> Optional[LevelHp]:
        if not 0 < cls < 32:
            return None
        base = (self.load_seg + LEVEL_HP_SEG) * 16
        group = self.guest.read(base + 0x10 + cls, 1)[0]
        return LevelHp(*self.guest.read(base + group * 4, 3)) if group < 4 else None

    def level_hp_minimum(self, con: int) -> int:
        return self.guest.read((self.load_seg + LEVEL_HP_SEG) * 16 + 0x38 + min(max(con, 0), 25), 1)[0]

    def item_breaks(self, item: int, item_type: int) -> bool:
        """Whether a weapon can break: the game's rule for non-magical wood, bone, stone and obsidian."""
        rec = self.guest.read(far_pointer(self.guest, self.ds, ITEMS_PTR) + item * ITEM_SIZE, ITEM_SIZE)
        typ = self.guest.read(far_pointer(self.guest, self.ds, ITEM_TYPES_PTR) + item_type * ITEM_TYPE_SIZE,
                              ITEM_TYPE_SIZE)
        if len(rec) < ITEM_SIZE or len(typ) < ITEM_TYPE_SIZE:
            return False
        return not typ[0x08] & 0x80 and rec[0x14] == 0 and rec[0x0F] == 0 and typ[0x08] & 0x0F <= 3

    def weapon(self, item: int, item_type: int) -> Optional[Weapon]:
        if item < 0 or item_type < 0:
            return None
        rec = self.guest.read(far_pointer(self.guest, self.ds, ITEMS_PTR) + item * ITEM_SIZE, ITEM_SIZE)
        typ = self.guest.read(far_pointer(self.guest, self.ds, ITEM_TYPES_PTR) + item_type * ITEM_TYPE_SIZE,
                              ITEM_TYPE_SIZE)
        if len(rec) < ITEM_SIZE or len(typ) < ITEM_TYPE_SIZE:
            return None
        return Weapon(self.item_name(rec[0x12]), typ[0x0D], typ[0x0C], struct.unpack("b", typ[0x0E:0x0F])[0],
                      struct.unpack("b", rec[0x14:0x15])[0], typ[0x08] & 0x0F, bool(typ[0x08] & 0x80))

    def weapon_name(self, w: Weapon) -> str:
        material = MATERIALS[w.material] + " " if w.material < len(MATERIALS) and w.material != 4 else ""
        return f"{material}{w.name}" + (f" {w.plus:+d}" if w.plus else "")
