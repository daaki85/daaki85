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
CREATURE_PSP = 0x02  # word: PSP now
CREATURE_THAC0 = 0x1F
CREATURE_SIDE = 0x1D  # creatures on the same side share this value
CREATURE_ABILITIES = 0x22
CREATURE_NAME = 0x28
# +1Ch: the character's condition, as the party screen shows it (the game shows the most
# important active effect instead of "Okay")
CREATURE_STATUS = 0x1C
OUT_COLD = 3
STATUS_NAMES = {1: "Okay", 2: "Stunned", 3: "Out Cold", 4: "Dying", 5: "Dead", 6: "Animated",
                7: "Petrified", 8: "Gone"}
PARTY_SIZE = 4  # the party are the first creatures in the table

# Segments relative to the load segment
COMBATANTS_SEG, COMBATANTS_OFF = 0x3972, 0xC36  # 3 bytes per combatant: kind (2 = creature), creature index
# The same table holds every object the game tracks ("things": kind 1 an item, 2 a creature).
# A creature's items: three lists, each starting at an object number in the creature's record;
# each item names the next by item number (9999 ends the list). An item's slot is where it is
# worn (the game's own slot names, in this order), 255 if only carried.
THING_ITEM = 1
CREATURE_ITEM_LISTS = (0x08, 0x0A, 0x0C)  # (+0Ch: where the game puts items handed to a character)
ITEM_NEXT, ITEM_SLOT, ITEM_TYPE, ITEM_NAME, ITEM_PLUS = 0x04, 0x11, 0x0A, 0x12, 0x14
NO_ITEM = 9999
# (as the inventory screen shows them: a ring on each hand, 4 and 11; the cloak 12, the feet 13)
EQUIP_SLOTS = ("arm", "ammo", "missile", "right hand", "finger", "waist", "legs", "head", "neck", "chest",
               "left hand", "finger", "cloak", "foot")
FINGERS = tuple(n for n, s in enumerate(EQUIP_SLOTS) if s == "finger")
FINGER = FINGERS[0]
FOOT = EQUIP_SLOTS.index("foot")
CLOAK_SLOT = EQUIP_SLOTS.index("cloak")
# The plain "Ring" item type. With the dice log's patched game, a worn one's plus betters AC
# and saving throws (DSCLOG's PROBE_RING_AC and PROBE_RING_SAVE); the game has no such ring of
# its own, and the companion can put a Ring +1 in the arena (ring.py).
RING_TYPE = 102
# Item types of the companion's own, which DSCLOG adds after the game's 115 (npcitems.py): a
# metal short sword, and a cloak of protection, whose plus counts for AC and, worn (CLOAK),
# on saves as a ring's does
GAME_TYPES = 115
SHORT_SWORD_TYPE, CLOAK_TYPE = GAME_TYPES, GAME_TYPES + 1
# The companion's rule changes (DSCLOG's RULES): helms count AC 1, boots add a move in a fight;
# AD&D's two-weapon penalties; spells saved against with the spell save; no doubled d20
RULE_HELMS, RULE_BOOTS, RULE_TWO_WEAPONS, RULE_SPELL_SAVE, RULE_NO_DOUBLE = 1, 2, 4, 8, 16
RULE_CATS_GRACE = 32  # Cat's Grace in Flaming Sphere's place
RULE_STEALTH = 64  # a thief hiding in shadows and moving silently backstabs (stealth.py)
RULE_LEVEL_10 = 128  # class levels go up to 10 (the game stops at 9)
# the Options' setting for each, all on unless unticked
RULE_SETTINGS = (("helm_ac", RULE_HELMS), ("boots_move", RULE_BOOTS), ("two_weapons", RULE_TWO_WEAPONS),
                 ("spell_save", RULE_SPELL_SAVE), ("no_doubled_save", RULE_NO_DOUBLE),
                 ("cats_grace", RULE_CATS_GRACE), ("stealth", RULE_STEALTH), ("level_10", RULE_LEVEL_10))
# Cat's Grace (RULE_CATS_GRACE): Flaming Sphere (wizard level 2) gets Strength's record and the
# name, and DSCLOG sends it to Strength's code, which rolls 1d6 into an effect of its own (54,
# a number the game leaves unused) that adds to DEX, at most 24, as Strength's adds to STR.
FLAMING_SPHERE, STRENGTH_SPELL, GRACE_EFFECT = 14, 23, 54
GRACE_NAME, SPHERE_NAME = b"CAT'S GRACE", b"FLAMING SPHERE"  # (in the game's capitals)
# Flaming Sphere's own record, from DSUN.EXE, to put back when the rule is off
SPHERE_RECORD = bytes.fromhex("067800000000003c0014000001ffff4dff004049ffff6106ff000202001104a1")
# The game turns a spell's kind of save (bits 5-7 of its +0Fh) into one of the sheet's five
# saves (1-5: paralysis/poison/death ... spell) with a table of words at DS:1E75h, read afresh
# for each save. Kind 5, what almost every spell is marked with, is petrification/polymorph
# (3); RULE_SPELL_SAVE makes it the spell save (5). Kind 1 (paralysis/poison/death: the
# clouds, Poison, Slay Living, the psionic attacks) and kind 4 (petrification/polymorph:
# three monsters' powers) stay as they are.
SAVE_KINDS = 0x1E75
KIND_TO_SAVE = (1, 1, 1, 2, 3, 3, 4, 5, 5, 5)
SPELL_KIND, SPELL_SAVE = 5, 5
# AD&D's two weapons: -2 with the main (right) hand, -4 with the off (left) hand, the DEX
# reaction adjustment (the game's initiative table, the same numbers) added and no better than
# 0; rangers have none
TWO_WEAPON_PENALTY = {3: -2, 10: -4}


# A spell's category word (its rules' +01h, the record's +11h; WIS counts against 0x1E, ...):
# with bit 40h set, the game's saving throw adds the target's DEX defensive adjustment (its
# DEX AC table, sign flipped: +4 at DEX 18, -4 at DEX 3), AD&D's rule for attacks that can be
# dodged. The game marks no spell so; with RULE_NO_DOUBLE the Ledger marks the fire, cold and
# electricity spells (DOUBLED_KINDS), in place of the doubled d20 (set_dodge).
CATEGORY_DODGE = 0x40
DOUBLED_FLAGS = 0x86


def rules_from_settings(settings: dict) -> int:
    return sum(bit for key, bit in RULE_SETTINGS if settings.get(key, True))


def kind_to_save(kind: int, rules: int) -> int:
    if kind == SPELL_KIND and rules & RULE_SPELL_SAVE:
        return SPELL_SAVE
    return KIND_TO_SAVE[kind]


# The rules in force (DiceLog.set_rules): GameData objects made without rules of their own use these
RULES_IN_FORCE = 0
EFFECTS_SEG, EFFECTS_OFF = 0x3BF6, 0x106  # 10 bytes per active effect
# The game's clock and event queue: a far pointer to the time (a dword, divided by the byte at
# GAME_TIME_SCALE); the first queue's entries (17 bytes: due time, kind, then the event's data),
# sorted by time, with their count. An effect ending is kind 7, its data the owner and handle.
GAME_TIME_PTR, GAME_TIME_SCALE = 0x9B72, 0x9B70
WHOSE_TURN = 0x4979  # DS word: the combatant whose turn it is (outside a fight: the leader)
REGION = 0x117C  # DS word: the region the party is in
# The party's money, in ceramic pieces (the inventory screen's bottom bar): a dword the game's
# script command for giving money (0Ch) adds to
MONEY_SEG, MONEY = 0x3781, 0x357
# Speakers the game names in its own text (the dialogue window shows only a portrait):
# 119 is asked about as "Yell something back at the Announcer?"
SPEAKERS = {119: "The Announcer"}
# The object a script was started on, e.g. the person clicked to talk to (a combatant number):
# the game's script trigger (DSUN.EXE 9520h) puts it here before running the script.
TALK_SEG, TALK_TARGET = 0x3781, 0x365
# The dialogue window's replies: the game copies each into DS:5537 + n * 33h; the row the
# player clicks goes in DS:1F0A (FFh until then), plus the list's scroll position at DS:5502
REPLY_CHOSEN, REPLY_SCROLL, REPLY_TEXTS, REPLY_SIZE = 0x1F0A, 0x5502, 0x5537, 0x33
EVENT_QUEUE, EVENT_COUNT, EVENT_SIZE, EVENT_EFFECT_ENDS = 0x2FBE, 0x2FC6, 0x11, 7
# Each round, per creature (4 bytes each): the initiative score (-1 once it has
# acted) and the 0-199 roll that breaks ties
INITIATIVE_SEG, INITIATIVE_OFF = 0x37BD, 0xD9
# Wizard and cleric spells, 7 bytes each from id 1: level, ..., DS offset of the name (+5)
SPELL_INFO_OFF, SPELL_INFO_SIZE, SPELL_COUNT = 0x3FD33, 7, 137
# Psionic powers are numbered after the spells (Detonate 138 ... Thought Shield 171) and share
# the spells' records and casting code; higher numbers are monsters' own powers
PSIONIC_FIRST, PSIONIC_COUNT = 138, 34
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
LEVEL_HP_CON_BONUS = 0x52  # +52h + CON: hit points per level (a warrior's; others get at most +2)
# Character creation. DS:119Ch is a far pointer to the character being made, a sheet whose
# classes (+21h) are numbered as in the creation screen's list (CREATION_CLASS_NAMES).
CREATION_SHEET_PTR = 0x119C
# Its tables (segment relative to the load segment): +14Dh + race * 6 + ability = the race's
# adjustment (signed); +180h + class * 3 = the class's prime requisite (a word: its ability
# index), then the least any other ability may be
CREATION_SEG, CREATION_RACE_OFF, CREATION_CLASS_OFF = 0x38D4, 0x14D, 0x180
CREATION_PRIME_MINIMUM = 17
ITEM_NAME_SIZE = 25
BROKEN_ITEM_TYPE = 0x6B  # what a broken weapon becomes

MATERIALS = ("Wooden", "Bone", "Stone", "Obsidian", "Metal", "Leather")
NO_MATERIAL = 0x40  # in the type's material byte, with material 0: things with none (rings, bodies)
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
    73: "Prayer", GRACE_EFFECT: "Cat's Grace",
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
    60: "AC 5, 1 better per 3 caster levels above 5", 63: "higher STR", 64: "STR + the amount borrowed, at most 24",
    67: "STR + 1d6, at most 24", 68: "STR - the amount, at least 3", GRACE_EFFECT: "DEX + 1d6, at most 24",
    73: "+1 to hit and saves for the caster's side, -1 for the other",
    # what the game's turn, movement, casting and damage code does with the rest
    1: "2d4 acid damage each round",
    3: "fights for a side picked at random each turn; can't cast spells",
    9: "ends fear, and the next fear fails (which ends it)",
    10: "joins the caster's side, the computer controlling it",
    11: "each turn a d10: 1 runs off, 2-6 does nothing, 7-9 fights for a random side, 10 acts normally",
    17: "the computer controls it; can't attack or cast spells (undead are immune; Bravery stops it)",
    18: "whoever hits the wearer has Cause Fear cast on them (once)",
    19: "can't cast spells",
    21: "can't be Paralyzed, Slowed or Stuck",
    # attacking uses a charge, and only effects with charges end that way: Invisibility has
    # one, Improved Invisibility (timed) has none
    23: "attacking or casting at an enemy ends it, unless it is Improved Invisibility",
    24: "ends when it attacks or casts at an enemy",
    25: "each weapon attack has a 75% chance to hit an image instead, using one up",
    29: "can't be Paralyzed or Slowed",
    33: "can't attack or cast harmful spells",
    34: "loses its turns, can't move, fails every saving throw",
    35: "fatal (1000 damage) if time passes out of combat, such as resting, before it ends or is cured",
    44: "turns spells cast at it back on their caster, one per charge",
    48: "no damage from weapons; any damage uses up one charge",
    50: "can't cast spells",
    51: "can't move (Free Action prevents it; some creatures are immune)",
    53: "no damage from weapons, using up one charge each time",
    # psionic powers' effects
    31: "magic resistance halved",
    32: "+75% magic resistance against mind-affecting spells (charms, holds, fear, confusion...)",
    61: "unarmed attacks do at least 1d10",
    62: "unarmed attacks do 2d4 (the arm is the weapon)",
}
# Effects that change a rule already listed above, from the same code
EFFECT_RULES[8] += "; can't cast spells that need sight"
EFFECT_RULES[47] += ", half movement and attacks, loses every other turn; ends Haste (Free Action and " \
                    "Protection from Paralysis prevent it)"
EFFECT_RULES[22] = "double movement and attacks; ends Slow"
# AD&D 2e strength damage adjustments (Dark Sun has no exceptional strength). The
# game adds these after rolling melee damage; seen in play for STR 20 and 24.
STR_DAMAGE = {1: -4, 2: -2, 3: -1, 4: -1, 5: -1, 16: 1, 17: 1, 18: 2, 19: 7, 20: 8, 21: 9,
              22: 10, 23: 11, 24: 12, 25: 14}


RACE_NAMES = {1: "human", 2: "dwarf", 3: "elf", 4: "half-elf", 5: "half-giant", 6: "halfling", 7: "mul",
              8: "thri-kreen"}
CREATION_CLASS_NAMES = {1: "Cleric", 2: "Druid", 3: "Fighter", 4: "Gladiator", 5: "Preserver",
                        6: "Psionicist", 7: "Ranger", 8: "Thief"}

SMALL_WORDS = {"of", "from", "to", "the", "and", "or", "in"}


def signed_text(n: int) -> str:
    return f"+{n}" if n >= 0 else str(n)


def effect_text(effect: "Effect", charges: Optional[int], seconds: Optional[int]) -> str:
    """ "Blur (23 rounds)", "Stoneskin (5 charges)", or just the name."""
    name = EFFECT_NAMES.get(effect.id, f"effect {effect.id}")
    if charges:
        return f"{name} ({charges} charge{'' if charges == 1 else 's'})"
    if seconds is not None:
        rounds = -(-seconds // 60)  # a round started counts
        return f"{name} ({rounds} round{'' if rounds == 1 else 's'})"
    return name


def ordinal(n: int) -> str:
    return f"{n}{'st' if n == 1 else 'nd' if n == 2 else 'rd' if n == 3 else 'th'}"


def slots_text(levels) -> str:
    """ "1st 3/5, 2nd 2/3": spell slots left and the most, by spell level."""
    return ", ".join(f"{ordinal(level)} {left}/{most}" for level, left, most in levels)


def game_time(seconds: int) -> str:
    """Game time: seconds, 60 to a round (AD&D's one-minute round)."""
    if seconds % 60 == 0:
        rounds = seconds // 60
        return f"{rounds} round{'' if rounds == 1 else 's'}"
    return f"{seconds} seconds ({seconds / 60:.1f} rounds)"


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


# A saving throw's modifiers, as the game's routine (79D3Ch in DSUN.EXE) adds them to the d20:
# effects on the target, its class, race and WIS or CON, and who cast the spell
SAVE_CON, SAVE_WIS = 0x810, 0x82A  # DS: a byte per ability score (CON for paralysis/poison/death saves)
PPD_SAVE = 1  # the sheet's paralysis/poison/death save
EVIL_ALIGNMENTS = (3, 6, 9)  # lawful, neutral and chaotic evil
SAVE_WIS_CATEGORY = 0x1E  # spells WIS counts against: mind-affecting, charms and holds, fear, illusions
SAVE_PSIONICIST_CATEGORY = 0x06  # ... and psionicists' +2: mind-affecting, charms and holds
DRUID_CLASSES, PSIONICIST = range(5, 9), 12
DWARF, HALFLING, UNDEAD = 2, 6, 9
EFFECT_BLESSED, EFFECT_BLIND, EFFECT_DETECT_INVIS, EFFECT_INVISIBLE, EFFECT_INVIS_UNDEAD = 7, 8, 15, 23, 24
EFFECT_PROT_EVIL, EFFECT_PROT_COLD, EFFECT_PROT_FIRE, EFFECT_PROT_LIGHTNING = 38, 36, 40, 41
EFFECT_SAVE_PENALTY, EFFECT_SPIRIT_ARMOR, EFFECT_BARKSKIN, EFFECT_PRAYER = 45, 56, 57, 73
SHEET_SAVES = 0x37  # the five saves, in SAVE_NAMES order
SAVE_SHORT = ("PPD", "RSW", "PP", "BW", "SP")  # as the game's inventory screen labels them
# To hit, as the game's attack setup adds it: STR (melee) or DEX (missiles) from these tables,
# the attacker's effects, the weapon's plus or its material's penalty
STR_TO_HIT, DEX_MISSILE = 0x7C2, 0x7DC  # DS: a byte per ability score
HIT_EFFECTS = ((7, 1), (12, -1), (47, -4), (49, 1))  # Blessed, Cursed, Slowed, Graft Weapon
WEAPON_HANDS = (EQUIP_SLOTS.index("right hand"), EQUIP_SLOTS.index("left hand"))
MISSILE_SLOT = EQUIP_SLOTS.index("missile")


class WeaponHit(NamedTuple):
    item: int  # its item number
    slot: int
    name: str
    thac0: int  # with this weapon, now
    parts: List[Tuple[str, int]]  # what is taken off the base THAC0 for it


class SaveNow(NamedTuple):
    base: int  # the character sheet's
    needs: int  # the d20 needed now (2-20: a 1 always fails, a 20 always saves)
    parts: List[Tuple[int, str]]  # the modifiers that always count (not the situational ones)


class Effect(NamedTuple):
    owner: int  # combatant id
    caster: int  # combatant id
    id: int


# Class numbers: a cleric, druid and ranger class for each element, in the order air, earth,
# fire, water (from the spheres in the game's class and spell tables: Flame Blade and Flame
# Strike belong to the third, Blood Flow and Dehydrate to the fourth, Deflection to the first)
CLASS_NAMES = {1: "Cleric (air)", 2: "Cleric (earth)", 3: "Cleric (fire)", 4: "Cleric (water)",
               5: "Druid (air)", 6: "Druid (earth)", 7: "Druid (fire)", 8: "Druid (water)", 9: "Fighter",
               10: "Gladiator", 11: "Preserver", 12: "Psionicist", 13: "Ranger (air)", 14: "Ranger (earth)",
               15: "Ranger (fire)", 16: "Ranger (water)", 17: "Thief"}


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


class LevelHp(NamedTuple):
    sides: int  # the hit die
    dice_levels: int  # levels up to this one roll it
    fixed: int  # hit points per level after that


class SpellDamage(NamedTuple):
    """A spell's damage, from its record (+0Ch..+0Eh): base dice, then per step some dice and a
    flat bonus; steps = (caster level, at most 10, + adjust) // per_levels, at least 1."""
    base_dice: int
    step_dice: int
    step_bonus: int
    per_levels: int
    adjust: int
    sides: int

    def steps(self, level: int) -> int:
        return max(1, (min(level, SPELL_LEVEL_CAP) + self.adjust) // self.per_levels)


SPELL_LEVEL_CAP = 10  # damage stops growing at caster level 10
PERMANENT = -9999  # a spell record's time unit for effects that last until removed
MIND_AFFECTING = 0x26  # flags in the spell record's word at +11h

# Spell slots. What's left: a byte for each spell level (index 1-9) for each party member,
# 1Eh apart, wizard and priest apart; casting takes one, resting refills them.
SLOTS_LEFT = {"Wizard": 0x4B08, "Priest": 0x4B11}
SLOTS_STRIDE, SPELL_LEVELS = 0x1E, 9
MAGIC_KINDS = (("Wizard", 1), ("Priest", 2))
# The most: each class's magic (bit 1 wizard, bit 2 priest; a byte every 4, by class number)...
CLASS_MAGIC_SEG, CLASS_MAGIC_OFF = 0x3800, 0x118
# ...and its slot rules: DS byte per class number, a rule number in each nibble (low first:
# class level, then WIS), and the rule words, a DS word each
SLOT_CLASS_RULES, SLOT_RULES = 0x664, 0x678
# Each spell's spheres (a dword, 7 bytes a spell), matched against each class's (above)
SPELL_SPHERES_SEG, SPELL_SPHERES_OFF, SPELL_SPHERES_SIZE = 0x3FB9, 0x19D, 7
RANGER_CLASSES = range(13, 17)
SLOTS_ALL_19 = 0x1164  # a DS word the game checks: 1 gives the party 19 of everything
HUMAN = 1

# Thief skills (the game's routine at 8023Bh in DSUN.EXE). Their order is AD&D's; the game
# never names them, but its checks fit: blindness stops all but hearing noise, Fire Shield
# and Mirror Image stop hiding, Graft Weapon stops picking pockets, opening locks and
# climbing, Detect Traps lets anyone find traps, Feeblemind stops reading languages.
THIEF_SKILLS = ("pick pockets", "open locks", "find/remove traps", "move silently", "hide in shadows",
                "hear noise", "climb walls", "read languages")
# the ones shown: those the game ever rolls (no script asks for the other three), and move
# silently, which the Templar's Ledger rolls when a pocket isn't picked (pickpocket.py)
ROLLED_SKILLS = (0, 1, 2, 3, 5, 6)
# the ones the game's inventory screen shows (DSCLOG's STATS): hide in shadows, which the Ledger's
# stealth rule rolls, in hear noise's place (one script check in the game, and no room for both)
PANEL_SKILLS = (0, 1, 2, 3, 4, 6)
# ... and the ones the Ledger's own screens show (room for all that are ever rolled)
LEDGER_SKILLS = (0, 1, 2, 3, 4, 5, 6)
THIEF = 17  # class number
# Tables (a byte per skill): base; then 8 per race (race 1 first); DEX below which each point
# costs 5, above which each gives 5, above which each costs 3 again; the armour penalty
THIEF_TABLE_SEG = 0x3FAA
THIEF_BASE, THIEF_RACE, THIEF_DEX_LOW, THIEF_DEX_HIGH, THIEF_DEX_TOP, THIEF_ARMOUR = 0, 8, 0x90, 0x98, 0xA0, 0xA8
THIEF_PER_LEVEL = 4
# The equipment the thief routine checks for its penalty (anything at all in these slots): a
# list of words at the thief table's +D0h, ended by 13. The game's has the legs and the quiver
# too; the dice log's copy of the game leaves those out (gamepatch.py), so the Ledger reads it
THIEF_PENALTY_LIST, PENALTY_LIST_END = 0xD0, 13
THIEF_PENALTY_SLOTS = tuple(EQUIP_SLOTS.index(s) for s in ("legs", "ammo", "left hand", "right hand"))
# AD&D's ranger: hide in shadows and move silently by ranger level (1-10), the Ledger's own
# (the game gives rangers no thief skills); race and DEX adjust them as a thief's
RANGER_HIDE = (10, 15, 20, 25, 31, 37, 43, 49, 56, 63)
RANGER_MOVE = (15, 21, 27, 33, 40, 47, 55, 62, 70, 78)
# Effects that rule skills out (the chance can't come up), and ones that make a skill certain
THIEF_BLOCKED = {8: (0, 1, 2, 3, 4, 6, 7), 17: tuple(range(8)), 11: tuple(range(8)), 3: tuple(range(8)),
                 34: tuple(range(8)), 47: (1, 2, 3, 4, 5, 6, 7), 20: (0, 4), 25: (4,), 49: (0, 1, 6), 19: (7,)}
THIEF_CERTAIN = {14: (2,), 23: (4,)}  # Detect Traps, Invisible
STATUS_OKAY = 1


# The spell's damage kinds (its flags word): the saving throw doubles the d20 against fire,
# cold and electricity, and no other kind
DOUBLED_KINDS = {0x02: "fire", 0x04: "cold", 0x80: "electricity"}


class SpellRules(NamedTuple):
    doubles_roll: bool  # the saving throw's d20 counts double
    save_modifier: int  # added to every saving throw against the spell
    doubled_for: str = ""  # the damage kind that doubles it: "fire", "cold" or "electricity"


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

    def __init__(self, guest: GuestMemory, ds: int, rules: Optional[int] = None):
        self.guest = guest
        self.ds = ds
        self.load_seg = ds - DGROUP
        self.rules = RULES_IN_FORCE if rules is None else rules

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

    def talk_target(self) -> Optional[str]:
        """The name of the creature the current script was started on (the person being talked to),
        when it is a living, named creature outside the party."""
        combatant, = struct.unpack("<h", self.guest.read((self.load_seg + TALK_SEG) * 16 + TALK_TARGET, 2))
        if combatant < PARTY_SIZE:
            return None
        index = self.combatant_creature(combatant)
        if index is None:
            return None
        rec = self.creature(index)
        name = rec[CREATURE_NAME:CREATURE_NAME + 16].split(b"\0", 1)[0].decode("cp437", "replace").strip()
        if not name or struct.unpack_from("<h", rec, 0)[0] <= 0:
            return None
        return name

    def living_npc(self, index: int) -> bool:
        """A creature outside the party, named and alive."""
        rec = self.creature(index)
        return index >= PARTY_SIZE and len(rec) >= CREATURE_SIZE and bool(rec[CREATURE_NAME]) \
            and struct.unpack_from("<h", rec, 0)[0] > 0

    def talk_target_creature(self) -> Optional[int]:
        """The creature index of the person being talked to (see talk_target), or None."""
        combatant, = struct.unpack("<h", self.guest.read((self.load_seg + TALK_SEG) * 16 + TALK_TARGET, 2))
        if combatant < PARTY_SIZE:
            return None
        index = self.combatant_creature(combatant)
        if index is None or index < PARTY_SIZE:
            return None
        rec = self.creature(index)
        if not rec[CREATURE_NAME] or struct.unpack_from("<h", rec, 0)[0] <= 0:
            return None
        return index

    def money(self) -> int:
        return struct.unpack("<I", self.guest.read((self.load_seg + MONEY_SEG) * 16 + MONEY, 4))[0]

    def add_money(self, amount: int) -> None:
        self.guest.write((self.load_seg + MONEY_SEG) * 16 + MONEY,
                         struct.pack("<I", max(0, self.money() + amount) & 0xFFFFFFFF))

    def region(self) -> int:
        """The region the party is in (its RGNxx.GFF)."""
        return self._word(REGION)

    def item_type_record(self, item: bytes) -> bytes:
        types = far_pointer(self.guest, self.ds, ITEM_TYPES_PTR)
        return self.guest.read(types + struct.unpack_from("<H", item, ITEM_TYPE)[0] * ITEM_TYPE_SIZE, ITEM_TYPE_SIZE)

    def combatant_name(self, combatant: int) -> str:
        index = self.combatant_creature(combatant)
        return self.creature_name(index) if index is not None else "?"

    def difficulty(self) -> int:
        return self._word(DIFFICULTY)

    def effects_left(self) -> List[Tuple[Effect, Optional[int], Optional[int]]]:
        """Each active effect with its charges left (None if it has none) and its game seconds
        left (None if untimed). A timed effect sits in the game's event queue as an entry of
        type 7 holding its owner and handle (the effect's byte +7), due at a game time."""
        count = self._word(EFFECT_COUNT)
        if not 0 <= count <= 400:
            return []
        data = self.guest.read((self.load_seg + EFFECTS_SEG) * 16 + EFFECTS_OFF, count * 10)
        due = {}
        queued = self._word(EVENT_COUNT)
        if 0 <= queued <= 500:
            events = self.guest.read(far_pointer(self.guest, self.ds, EVENT_QUEUE), queued * EVENT_SIZE)
            for i in range(queued):
                at, kind, owner, handle = struct.unpack_from("<iBhB", events, i * EVENT_SIZE)
                if kind == EVENT_EFFECT_ENDS:
                    due[(owner, handle)] = at
        now = self.game_time()
        out = []
        for i in range(count):
            rec = data[i * 10:i * 10 + 10]
            effect = Effect(*struct.unpack_from("<hh", rec), rec[6])
            at = due.get((effect.owner, rec[7]))
            charges = rec[8] or None
            spell, = struct.unpack_from("<h", rec, 4)
            spell_rec = self.spell_record(spell) if 0 < spell < 256 else b""
            if len(spell_rec) >= SPELL_SIZE and struct.unpack_from("<h", spell_rec, 7)[0] == PERMANENT:
                charges = None  # a permanent effect keeps a meaningless 15 there
            out.append((effect, charges, max(at - now, 0) if at is not None and now is not None else None))
        return out

    def effect_spells(self) -> List[Tuple[Effect, int]]:
        """Each active effect with the spell (or power) that made it."""
        count = self._word(EFFECT_COUNT)
        if not 0 <= count <= 400:
            return []
        data = self.guest.read((self.load_seg + EFFECTS_SEG) * 16 + EFFECTS_OFF, count * 10)
        return [(Effect(*struct.unpack_from("<hh", data, i * 10), data[i * 10 + 6]),
                 struct.unpack_from("<h", data, i * 10 + 4)[0]) for i in range(count)]

    def reply_chosen(self) -> Optional[Tuple[int, str]]:
        """The reply the player has just clicked (its place in the list, and its text), while
        the game flashes it; None the rest of the time."""
        row = self.guest.read(self.ds * 16 + REPLY_CHOSEN, 1)[0]
        if row == 0xFF:
            return None
        n = row + self.guest.read(self.ds * 16 + REPLY_SCROLL, 1)[0]
        text = self.guest.read(self.ds * 16 + REPLY_TEXTS + n * REPLY_SIZE, REPLY_SIZE)
        return n, text.split(b"\0", 1)[0].decode("cp437", "replace").strip()

    def whose_turn(self) -> Optional[int]:
        """The combatant whose turn it is in a fight (the game's word at WHOSE_TURN)."""
        turn = self._word(WHOSE_TURN)
        return turn if 0 <= turn < 256 else None

    def game_time(self) -> Optional[int]:
        """Game seconds since the start (60 to a round): the dword the game keeps its clock in."""
        scale = self.guest.read(self.ds * 16 + GAME_TIME_SCALE, 1)[0]
        raw = self.guest.read(far_pointer(self.guest, self.ds, GAME_TIME_PTR), 4)
        return struct.unpack("<i", raw)[0] // scale if scale and len(raw) == 4 else None

    def effects(self) -> List[Effect]:
        count = self._word(EFFECT_COUNT)
        if not 0 <= count <= 400:
            return []
        data = self.guest.read((self.load_seg + EFFECTS_SEG) * 16 + EFFECTS_OFF, count * 10)
        return [Effect(*struct.unpack_from("<hh", data, i * 10), data[i * 10 + 6]) for i in range(count)]

    def spell_name(self, spell: int) -> str:
        if PSIONIC_FIRST <= spell < PSIONIC_FIRST + PSIONIC_COUNT:
            # the psionic powers' names come first in the names list, in number order
            names = self.guest.read(self.ds * 16 + SPELL_NAMES, 0x400).split(b"\0")
            text = names[spell - PSIONIC_FIRST].decode("cp437", "replace") if spell - PSIONIC_FIRST < len(names) else ""
            return title(text) if text else f"psionic power {spell}"
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
        flags = struct.unpack_from("<H", rec, 0x0A)[0]
        kinds = " and ".join(name for bit, name in DOUBLED_KINDS.items() if flags & bit)
        doubled = bool(kinds) and not self.rules & RULE_NO_DOUBLE
        return SpellRules(doubled, nibble - 16 if nibble & 8 else nibble, kinds if doubled else "")

    def set_dodge(self, on: bool) -> int:
        """Mark the fire, cold and electricity spells for DEX on their saves (CATEGORY_DODGE),
        or unmark them. Returns how many records changed."""
        changed = 0
        for spell in range(1, 256):
            at = (self.load_seg + SPELLS_SEG) * 16 + SPELLS_OFF + spell * SPELL_SIZE
            rec = self.guest.read(at, SPELL_SIZE)
            if len(rec) < SPELL_SIZE:
                break
            want = on and bool(struct.unpack_from("<H", rec, 0x0A)[0] & DOUBLED_FLAGS)
            byte = rec[0x01]
            new = byte | CATEGORY_DODGE if want else byte & ~CATEGORY_DODGE
            if new != byte:
                self.guest.write(at + 0x01, bytes((new,)))
                changed += 1
        return changed

    def set_cats_grace(self, on: bool) -> bool:
        """Put Cat's Grace in Flaming Sphere's place (Strength's record, the name), or Flaming
        Sphere back. Only over what's there now being one or the other. True if it is as asked."""
        sphere = (self.load_seg + SPELLS_SEG) * 16 + SPELLS_OFF - 0x10 + FLAMING_SPHERE * SPELL_SIZE
        info = self.load_seg * 16 + SPELL_INFO_OFF + (FLAMING_SPHERE - 1) * SPELL_INFO_SIZE
        name_at = self.ds * 16 + struct.unpack("<H", self.guest.read(info + 5, 2))[0]
        name = self.guest.read(name_at, len(SPHERE_NAME) + 1)
        if name.rstrip(b"\0") not in (SPHERE_NAME, GRACE_NAME):
            return False  # not the name it should be: leave it
        strength = self.spell_record(STRENGTH_SPELL)
        want = strength if on else SPHERE_RECORD
        mine = self.guest.read(sphere, SPELL_SIZE)
        if mine != want:  # (the category's dodge flag aside, which set_dodge sees to)
            self.guest.write(sphere, want)
        text = GRACE_NAME if on else SPHERE_NAME
        self.guest.write(name_at, text.ljust(len(SPHERE_NAME), b"\0") + b"\0")
        return True

    def spell_record(self, spell: int) -> bytes:
        """The spell's whole 32-byte record (it starts 10h before the fields SPELLS_OFF names)."""
        if not 0 <= spell < 256:
            return b""
        return self.guest.read((self.load_seg + SPELLS_SEG) * 16 + SPELLS_OFF - 0x10 + spell * SPELL_SIZE,
                               SPELL_SIZE)

    def spell_duration(self, spell: int, level: int, roll: int) -> Optional[Tuple[int, str]]:
        """(game seconds, how) for a spell cast at `level` whose duration dice came up `roll`:
        ((level + adjust) * per_level // per_levels + dice) * unit. 60 seconds are a round."""
        rec = self.spell_record(spell)
        if len(rec) < SPELL_SIZE:
            return None
        unit, = struct.unpack_from("<h", rec, 7)
        if unit <= 0:
            return None  # not timed: charges (see spell_charges), or -9999: permanent
        return self._spell_amount(rec, spell, level, roll, unit)

    def spell_charges(self, spell: int, level: int, roll: int) -> Optional[Tuple[int, str]]:
        """(charges, how) for an effect that lasts a number of uses rather than a time: the
        game stores a negative duration as that many charges (Stoneskin's blows, Mirror
        Image's images, Invisibility's one attack)."""
        rec = self.spell_record(spell)
        if len(rec) < SPELL_SIZE:
            return None
        unit, = struct.unpack_from("<h", rec, 7)
        if not PERMANENT < unit < 0:
            return None
        found = self._spell_amount(rec, spell, level, roll, -unit)
        return (found[0], found[1]) if found[0] > 0 else None

    def _spell_amount(self, rec: bytes, spell: int, level: int, roll: int, unit: int) -> Tuple[int, str]:
        per_level, = struct.unpack_from("<H", rec, 5)
        rule = self.spell_damage(spell)
        per_levels, adjust = (rule.per_levels, rule.adjust) if rule else (1, 0)
        levels = (max(level, 1) + adjust) * per_level // per_levels
        total = min((levels + roll) * unit, 0x7FFF)
        how = []
        if per_level:
            how.append(f"{per_level} for each " + ("caster level" if per_levels == 1 else f"{per_levels} caster levels")
                       + (f" ({signed_text(adjust)})" if adjust else "") + f" = {levels}")
        how.append(f"{roll} from the dice")
        return total, " + ".join(how)

    def save_negates_damage(self, spell: int) -> bool:
        """A successful save stops all the damage (else it halves it): flag 8000h of the word at +11h."""
        rec = self.spell_record(spell)
        return len(rec) >= SPELL_SIZE and bool(struct.unpack_from("<H", rec, 0x11)[0] & 0x8000)

    def spell_damage(self, spell: int) -> Optional[SpellDamage]:
        if not 0 <= spell < 256:
            return None
        rec = self.guest.read((self.load_seg + SPELLS_SEG) * 16 + SPELLS_OFF + spell * SPELL_SIZE, SPELL_SIZE)
        if len(rec) < SPELL_SIZE:
            return None
        b0, b1, b2 = rec[0x0C], rec[0x0D], rec[0x0E]
        adjust = (b2 >> 4) - 16 if b2 & 0x80 else b2 >> 4
        return SpellDamage(b1 >> 3, b0 >> 5, b0 & 0x1F, (b1 & 7) or 1, adjust, b2 & 0x0F)

    def mind_affecting(self, spell: int) -> bool:
        """A mind-affecting spell (charms, fear, feeblemind...): bits 26h of the word at +11h."""
        rec = self.spell_record(spell)
        return len(rec) >= SPELL_SIZE and bool(struct.unpack_from("<H", rec, 0x11)[0] & MIND_AFFECTING)

    def save_modifiers(self, target: int, caster: int, spell: int, save: int) -> List[Tuple[int, str]]:
        """What the game adds to a saving throw's d20 (besides the spell's own modifier), as
        [(amount, why), ...]: the target's rings (with the patched game), effects, class, race
        and WIS or CON, and whether the caster is evil or can see the target."""
        ti, ci = self.combatant_creature(target), self.combatant_creature(caster)
        if ti is None:
            return []
        rec, sheet, creature = self.spell_record(spell), self.sheet(ti), self.creature(ti)
        if len(rec) < SPELL_SIZE or len(sheet) < SHEET_SIZE or len(creature) < CREATURE_SIZE:
            return []
        category, = struct.unpack_from("<H", rec, 0x11)
        kinds, = struct.unpack_from("<H", rec, 0x1A)
        area = rec[0x17] != 0xFF  # a spell with an area (a table entry for it)
        effects = self.effects()
        mine = {x.id for x in effects if x.owner == target}
        theirs = {x.id for x in effects if x.owner == caster} if caster != target else set()
        caster_sheet = self.sheet(ci) if ci is not None else b""
        out: List[Tuple[int, str]] = []
        ring = self.ring_plus(ti)
        if ring:
            out.append((ring, "Ring of Protection"))
        if EFFECT_SAVE_PENALTY in mine:
            out.append((-1, EFFECT_NAMES[EFFECT_SAVE_PENALTY]))
        if EFFECT_SPIRIT_ARMOR in mine and save != PPD_SAVE:
            out.append((3, EFFECT_NAMES[EFFECT_SPIRIT_ARMOR]))
        if EFFECT_BARKSKIN in mine:
            out.append((1, EFFECT_NAMES[EFFECT_BARKSKIN]))
        if EFFECT_BLESSED in mine:
            out.append((1, EFFECT_NAMES[EFFECT_BLESSED]))
        if EFFECT_PROT_EVIL in mine and len(caster_sheet) >= SHEET_SIZE and caster_sheet[0x1A] in EVIL_ALIGNMENTS:
            out.append((2, "Prot Evil against an evil caster"))
        for bit, eff, amount in ((0x80, EFFECT_PROT_LIGHTNING, 4), (0x04, EFFECT_PROT_COLD, 3),
                                 (0x02, EFFECT_PROT_FIRE, 3)):
            if kinds & bit and eff in mine:
                out.append((amount, EFFECT_NAMES[eff]))
        prayer = next((x for x in effects if x.id == EFFECT_PRAYER and x.owner == target), None)
        if prayer is not None:
            source = self.combatant_creature(prayer.caster)
            same = source is not None and self.creature(source)[CREATURE_SIDE] == creature[CREATURE_SIDE]
            out.append((1 if same else -1, "Prayer, " + ("its caster's side" if same else "the other side's")))
        if not area and caster != target:
            undead_caster = len(caster_sheet) >= SHEET_SIZE and caster_sheet[SHEET_RACE] == UNDEAD
            if EFFECT_BLIND in theirs:
                out.append((4, "the caster is Blind"))
            elif EFFECT_DETECT_INVIS not in theirs and (EFFECT_INVISIBLE in mine
                                                         or (EFFECT_INVIS_UNDEAD in mine and undead_caster)):
                out.append((4, "Invisible to the caster"))
        if kinds & 0x82 and any(self.class_level(ti, c) for c in DRUID_CLASSES):
            out.append((2, "druid against fire and electricity"))
        if self.class_level(ti, PSIONICIST) and category & SAVE_PSIONICIST_CATEGORY:
            out.append((2, "psionicist against the mind"))
        abilities = creature[CREATURE_ABILITIES:CREATURE_ABILITIES + 6]
        if category & SAVE_WIS_CATEGORY:
            wis = abilities[4]
            adjust = struct.unpack("b", self.guest.read(self.ds * 16 + SAVE_WIS + wis, 1))[0]
            if adjust:
                out.append((adjust, f"WIS {wis}"))
        if category & CATEGORY_DODGE:  # (the game's rule; see CATEGORY_DODGE)
            dex = abilities[1]
            adjust = -struct.unpack("b", self.guest.read(self.ds * 16 + DEX_AC + dex, 1))[0] if dex < 26 else 0
            if adjust:
                out.append((adjust, f"DEX {dex} dodging"))
        if save == PPD_SAVE:
            con = abilities[2]
            if sheet[SHEET_RACE] in (DWARF, HALFLING):
                out.append((con * 2 // 7, f"{'dwarf' if sheet[SHEET_RACE] == DWARF else 'halfling'} CON {con}"))
            adjust = struct.unpack("b", self.guest.read(self.ds * 16 + SAVE_CON + con, 1))[0]
            if adjust:
                out.append((adjust, f"CON {con}"))
        return [(amount, why) for amount, why in out if amount]

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
            rec = self.guest.read(far_pointer(self.guest, self.ds, ITEM_NAMES_PTR) + name_index * ITEM_NAME_SIZE,
                                  ITEM_NAME_SIZE)
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

    def spell_slots(self, member: int) -> List[Tuple[str, List[Tuple[int, int, int]]]]:
        """A party member's spell slots: [(kind, [(spell level, left, most), ...]), ...] for
        the kinds of magic (Wizard, Priest) their classes cast, at the spell levels their class
        levels reach. (The game gives WIS's bonus slots at spell levels the class can't cast yet
        too: no use to them, so not shown.)"""
        out = []
        for kind, bit in MAGIC_KINDS:
            left = self.guest.read(self.ds * 16 + SLOTS_LEFT[kind] + member * SLOTS_STRIDE, SPELL_LEVELS + 1)
            levels = [(lvl, left[lvl], self.max_spell_slots(member, bit, lvl)) for lvl in range(1, SPELL_LEVELS + 1)
                      if self.max_spell_slots(member, bit, lvl, wis=False)]
            if levels:
                out.append((kind, levels))
        return out

    def max_spell_slots(self, member: int, bit: int, spell_level: int, wis: bool = True) -> int:
        """The slots the game gives on resting (its routine at 5E0ACh in DSUN.EXE): for each class
        casting this kind of magic, rules from its tables applied to the class level and then WIS.
        A rule word: bits 8-11 the most it gives, bits 4-7 one more than the spell level it
        starts below, bit 0 how odd values round. A human's later (dual) classes count only while
        their level is below the first class's. Without `wis`, the class levels' alone."""
        if member < 4 and self._word(SLOTS_ALL_19) == 1:  # the game's own test switch
            return 19
        sheet = self.sheet(member)
        if len(sheet) < SHEET_SIZE:
            return 0
        ability = self.creature(member)[CREATURE_ABILITIES + 4]
        magic = self.guest.read((self.load_seg + CLASS_MAGIC_SEG) * 16 + CLASS_MAGIC_OFF, 4 * 32)
        total = 0
        for n in range(3):
            cls, level = sheet[SHEET_CLASSES + n], sheet[SHEET_LEVELS + n]
            if not cls or cls >= 32 or not magic[cls * 4] & bit:
                continue
            if n and sheet[SHEET_RACE] == HUMAN and level >= sheet[SHEET_LEVELS]:
                continue
            rules = self.guest.read(self.ds * 16 + SLOT_CLASS_RULES + cls, 1)[0]
            for value in (level, ability) if wis else (level,):
                if not rules:
                    break
                word, = struct.unpack("<H", self.guest.read(self.ds * 16 + SLOT_RULES + (rules & 0x0F) * 2, 2))
                start, odd, most = ((word >> 4) & 0x0F) - 1, word & 1, (word >> 8) & 0x0F
                count = value - (value + odd) // 2 - (spell_level + start)
                if count == 1 and (value & 1) == odd:
                    count += 1
                total += min(max(count, 0), most)
                rules >>= 4
        return total

    def class_level(self, creature: int, cls: int) -> int:
        """The creature's level in one class (0 if it hasn't that class)."""
        sheet = self.sheet(creature)
        if len(sheet) < SHEET_SIZE:
            return 0
        return next((sheet[SHEET_LEVELS + n] for n in range(3) if sheet[SHEET_CLASSES + n] == cls), 0)

    def effect_caster_level(self, creature: int, spell: int) -> Optional[int]:
        """The level a spell effect counts as having been cast at, as Dispel Magic weighs it (the
        game's routine at 81B16h): the caster's best level in a class sharing a sphere with the
        spell, rangers 7 levels less. None for psionic powers and monsters' own powers."""
        if not 0 < spell < PSIONIC_FIRST:
            return None
        spheres, = struct.unpack("<I", self.guest.read(
            (self.load_seg + SPELL_SPHERES_SEG) * 16 + SPELL_SPHERES_OFF + spell * SPELL_SPHERES_SIZE, 4))
        classes = self.guest.read((self.load_seg + CLASS_MAGIC_SEG) * 16 + CLASS_MAGIC_OFF, 4 * 20)
        best = 0
        for cls in range(1, 20):
            if struct.unpack_from("<I", classes, cls * 4)[0] & spheres:
                level = self.class_level(creature, cls) - (7 if cls in RANGER_CLASSES else 0)
                best = max(best, level)
        return best

    def thief_skill_parts(self, creature: int, skill: int) -> Optional[List[Tuple[str, int]]]:
        """What a thief skill's chance (percent) is made of, before armour, effects and the
        situation: [(what, amount), ...], or None for a character without thief levels."""
        sheet = self.sheet(creature)
        rec = self.creature(creature)
        if len(sheet) < SHEET_SIZE or len(rec) < CREATURE_SIZE or not 0 <= skill < len(THIEF_SKILLS):
            return None
        level = next((sheet[SHEET_LEVELS + n] for n in range(3) if sheet[SHEET_CLASSES + n] == THIEF), 0)
        if not level:
            return None
        table = self.guest.read((self.load_seg + THIEF_TABLE_SEG) * 16, THIEF_ARMOUR + 8)
        signed_byte = lambda offset: struct.unpack_from("b", table, offset)[0]
        race, dex = sheet[SHEET_RACE], rec[CREATURE_ABILITIES + 1]
        parts = [("base", signed_byte(THIEF_BASE + skill)),
                 (f"thief level {level}", level * THIEF_PER_LEVEL)]
        if 1 <= race <= 8:
            parts.append((RACE_NAMES[race], signed_byte(THIEF_RACE + race * 8 + skill)))
        low, high, top = (table[o + skill] for o in (THIEF_DEX_LOW, THIEF_DEX_HIGH, THIEF_DEX_TOP))
        dex_part = -5 * max(low - dex, 0) + 5 * max(dex - high, 0) - 3 * max(dex - top, 0)
        parts.append((f"DEX {dex}", dex_part))
        return [(what, n) for what, n in parts if n or what == "base"]

    def thief_skills(self, creature: int) -> List[Tuple[str, int]]:
        """[(skill, chance before armour and the situation), ...] for a thief, else []: the skills
        the game ever rolls, and move silently (hide in shadows and read languages never are)."""
        out = []
        for skill in ROLLED_SKILLS:
            name = THIEF_SKILLS[skill]
            parts = self.thief_skill_parts(creature, skill)
            if parts is None:
                return []
            out.append((name, sum(n for _, n in parts)))
        return out

    def thief_penalty_slots(self) -> Tuple[int, ...]:
        """The slots where anything at all brings the thief skills' equipment penalty: the game's
        list, as it is in memory (THIEF_PENALTY_SLOTS if it can't be read)."""
        data = self.guest.read((self.load_seg + THIEF_TABLE_SEG) * 16 + THIEF_PENALTY_LIST, 16)
        slots = []
        for (slot,) in struct.iter_unpack("<H", data):
            if slot >= PENALTY_LIST_END:  # (as the game's loop: 13 and up end it)
                return tuple(slots)
            slots.append(slot)
        return THIEF_PENALTY_SLOTS  # (no end: not the game's list)

    def ranger_level(self, creature: int) -> int:
        return max((self.class_level(creature, cls) for cls in RANGER_CLASSES), default=0)

    def ranger_skill_parts(self, creature: int, skill: int) -> Optional[List[Tuple[str, int]]]:
        """A ranger's hide in shadows (4) or move silently (3), as thief_skill_parts: AD&D's
        chance for the ranger level, the race's and DEX's adjustments. None without ranger levels."""
        sheet, rec = self.sheet(creature), self.creature(creature)
        level = self.ranger_level(creature) if len(sheet) >= SHEET_SIZE else 0
        if not level or len(rec) < CREATURE_SIZE or skill not in (3, 4):
            return None
        table = self.guest.read((self.load_seg + THIEF_TABLE_SEG) * 16, THIEF_ARMOUR + 8)
        signed_byte = lambda offset: struct.unpack_from("b", table, offset)[0]
        race, dex = sheet[SHEET_RACE], rec[CREATURE_ABILITIES + 1]
        parts = [(f"ranger level {level}", (RANGER_HIDE if skill == 4 else RANGER_MOVE)[min(level, 10) - 1])]
        if 1 <= race <= 8:
            parts.append((RACE_NAMES[race], signed_byte(THIEF_RACE + race * 8 + skill)))
        low, high, top = (table[o + skill] for o in (THIEF_DEX_LOW, THIEF_DEX_HIGH, THIEF_DEX_TOP))
        parts.append((f"DEX {dex}", -5 * max(low - dex, 0) + 5 * max(dex - high, 0) - 3 * max(dex - top, 0)))
        return [(what, n) for what, n in parts if n or what.startswith("ranger")]

    def ranger_skill_now(self, creature: int, skill: int) -> Optional[int]:
        """A ranger's chance as it stands: effects that rule hiding out or make it certain count
        as for a thief (no equipment penalty). None without ranger levels."""
        parts = self.ranger_skill_parts(creature, skill)
        if parts is None:
            return None
        ids = {e.id for e in self._mine(creature, self.effects())}
        if any(skill in THIEF_CERTAIN.get(e, ()) for e in ids):
            return 100
        if self.creature(creature)[CREATURE_STATUS] != STATUS_OKAY or any(skill in THIEF_BLOCKED.get(e, ()) for e in ids):
            return 0
        return max(0, min(255, sum(n for _, n in parts)))

    def ranger_skills_now(self, creature: int) -> List[Tuple[str, int]]:
        """[(skill, chance), ...]: a ranger's move silently and hide in shadows as they stand
        (the stealth rule's), or [] without ranger levels."""
        out = [(THIEF_SKILLS[skill], self.ranger_skill_now(creature, skill)) for skill in (3, 4)]
        return [(name, n) for name, n in out if n is not None]

    def thief_skills_now(self, creature: int, skills: Tuple[int, ...] = ROLLED_SKILLS) -> List[Tuple[str, int]]:
        """[(skill, chance), ...] for the skills the game rolls, as they stand now: with the
        equipment penalty, 0 for a skill an effect rules out (or when the thief isn't Okay), 100
        for one an effect makes certain. Not the situation's bonus (a hard lock...). [] for
        someone without thief levels. `skills`: which (numbers in THIEF_SKILLS)."""
        rec = self.creature(creature)
        if len(rec) < CREATURE_SIZE:
            return []
        table = self.guest.read((self.load_seg + THIEF_TABLE_SEG) * 16 + THIEF_ARMOUR, 8)
        slots = self.thief_penalty_slots()
        penalty = any(item[ITEM_SLOT] in slots for _, item, _ in self._worn(creature))
        ids = {e.id for e in self._mine(creature, self.effects())}
        okay = rec[CREATURE_STATUS] == STATUS_OKAY
        out = []
        for skill in skills:
            parts = self.thief_skill_parts(creature, skill)
            if parts is None:
                return []
            chance = sum(n for _, n in parts) - (table[skill] if penalty and len(table) == 8 else 0)
            if any(skill in THIEF_CERTAIN.get(e, ()) for e in ids):
                chance = 100
            elif not okay or any(skill in THIEF_BLOCKED.get(e, ()) for e in ids):
                chance = 0
            out.append((THIEF_SKILLS[skill], max(0, min(255, chance))))
        return out

    def item_label(self, item: bytes, typ: bytes) -> str:
        """"Metal Long Sword +1": an item's material (when it has one), name and plus."""
        material = typ[0x08] & 0x0F if len(typ) == ITEM_TYPE_SIZE else len(MATERIALS)
        if len(typ) == ITEM_TYPE_SIZE and typ[0x08] & NO_MATERIAL and not material:
            material = len(MATERIALS)  # a ring, a body...: no material to name
        plus = struct.unpack("b", item[ITEM_PLUS:ITEM_PLUS + 1])[0]
        name = self.item_name(struct.unpack_from("<H", item, ITEM_NAME)[0])
        if plus and not name.endswith(f"{plus:+d}"):  # (a name such as "Sling +2" has it)
            name += f" {plus:+d}"
        return (f"{MATERIALS[material]} " if material < len(MATERIALS) else "") + name

    def equipment(self, creature: int) -> List[Tuple[Optional[str], str]]:
        """A creature's items: [(slot it's worn in or None if only carried, "Leather Chest Armor"), ...],
        worn items first, in the game's slot order."""
        out = [(item[ITEM_SLOT], self.item_label(item, typ)) for _, item, typ in self._worn(creature)]
        out.sort(key=lambda x: x[0])
        return [(EQUIP_SLOTS[slot] if slot < len(EQUIP_SLOTS) else None, name) for slot, name in out]

    def _worn(self, creature: int):
        """(item number, item record, type record) for each of a creature's items."""
        rec = self.creature(creature)
        if len(rec) < CREATURE_SIZE:
            return
        things = (self.load_seg + COMBATANTS_SEG) * 16 + COMBATANTS_OFF
        items = far_pointer(self.guest, self.ds, ITEMS_PTR)
        types = far_pointer(self.guest, self.ds, ITEM_TYPES_PTR)
        seen = set()
        for field in CREATURE_ITEM_LISTS:
            thing, = struct.unpack_from("<H", rec, field)
            if thing >= NO_ITEM:
                continue
            kind, index = struct.unpack("<Bh", self.guest.read(things + thing * 3, 3))
            if kind != THING_ITEM:
                continue
            while 0 <= index < NO_ITEM and index not in seen and len(seen) < 100:
                seen.add(index)
                item = self.guest.read(items + index * ITEM_SIZE, ITEM_SIZE)
                typ = self.guest.read(types + struct.unpack_from("<H", item, ITEM_TYPE)[0] * ITEM_TYPE_SIZE,
                                      ITEM_TYPE_SIZE)
                yield index, item, typ
                index, = struct.unpack_from("<h", item, ITEM_NEXT)

    def _mine(self, creature: int, effects: List[Effect]) -> List[Effect]:
        """The effects on a creature (effects name combatants)."""
        combatants = {c for c, i in self.combatants().items() if i == creature}
        if creature < PARTY_SIZE:
            combatants.add(creature)  # the party's combatant numbers are theirs
        return [e for e in effects if e.owner in combatants]

    def _prayer(self, creature: int, mine: List[Effect]) -> Optional[int]:
        """+1 under a Prayer from its own side, -1 from the other side's, None without."""
        prayer = next((e for e in mine if e.id == EFFECT_PRAYER), None)
        if prayer is None:
            return None
        source = self.combatant_creature(prayer.caster)
        same = source is not None and self.creature(source)[CREATURE_SIDE] == self.creature(creature)[CREATURE_SIDE]
        return 1 if same else -1

    def saves_now(self, creature: int) -> List[SaveNow]:
        """The five saves as the d20 roll needed now: the sheet's number less the modifiers the
        game's saving throw adds whatever the spell (rings, Blessed, Prayer, Barkskin, Spirit
        Armor, the save penalty, and CON on paralysis/poison/death saves). The rest depend on
        the spell or the caster (WIS against the mind, Protection from Fire...): see save_modifiers."""
        sheet, rec = self.sheet(creature), self.creature(creature)
        if len(sheet) < SHEET_SIZE or len(rec) < CREATURE_SIZE:
            return []
        mine = self._mine(creature, self.effects())
        ids = {e.id for e in mine}
        prayer = self._prayer(creature, mine)
        ring = self.ring_plus(creature)
        con = rec[CREATURE_ABILITIES + 2]
        out = []
        for save in range(1, 6):
            parts: List[Tuple[int, str]] = []
            if ring:
                parts.append((ring, "Ring of Protection"))
            if EFFECT_SAVE_PENALTY in ids:
                parts.append((-1, EFFECT_NAMES[EFFECT_SAVE_PENALTY]))
            if EFFECT_SPIRIT_ARMOR in ids and save != PPD_SAVE:
                parts.append((3, EFFECT_NAMES[EFFECT_SPIRIT_ARMOR]))
            if EFFECT_BARKSKIN in ids:
                parts.append((1, EFFECT_NAMES[EFFECT_BARKSKIN]))
            if EFFECT_BLESSED in ids:
                parts.append((1, EFFECT_NAMES[EFFECT_BLESSED]))
            if prayer is not None:
                parts.append((prayer, "Prayer"))
            if save == PPD_SAVE:
                if sheet[SHEET_RACE] in (DWARF, HALFLING):
                    parts.append((con * 2 // 7, f"{'dwarf' if sheet[SHEET_RACE] == DWARF else 'halfling'} CON {con}"))
                adjust = struct.unpack("b", self.guest.read(self.ds * 16 + SAVE_CON + con, 1))[0] if con < 26 else 0
                if adjust:
                    parts.append((adjust, f"CON {con}"))
            parts = [(n, why) for n, why in parts if n]
            base = sheet[SHEET_SAVES + save - 1]
            out.append(SaveNow(base, min(20, max(2, base - sum(n for n, _ in parts))), parts))
        return out

    def weapon_hits(self, creature: int) -> List[WeaponHit]:
        """THAC0 with each weapon the creature has ready (right hand, left hand, missile), as the
        game's attack works it out before the target is known (not from behind or backstabbing,
        nor the target's Blur); unarmed (item -1) when it has none."""
        rec = self.creature(creature)
        if len(rec) < CREATURE_SIZE:
            return []
        base = struct.unpack("b", rec[CREATURE_THAC0:CREATURE_THAC0 + 1])[0]
        mine = self._mine(creature, self.effects())
        ids = {e.id for e in mine}
        common = [(EFFECT_NAMES[eid], n) for eid, n in HIT_EFFECTS if eid in ids]
        prayer = self._prayer(creature, mine)
        if prayer is not None:
            common.append(("Prayer", prayer))
        strength, dex = rec[CREATURE_ABILITIES], rec[CREATURE_ABILITIES + 1]
        table = lambda off, score: struct.unpack("b", self.guest.read(self.ds * 16 + off + score, 1))[0] \
            if score < 26 else 0
        weapons = []
        for index, item, typ in self._worn(creature):
            slot = item[ITEM_SLOT]
            if slot in WEAPON_HANDS + (MISSILE_SLOT,) and typ[0x0C] and typ[0x0D]:  # it has damage dice
                weapons.append((index, item, typ, slot))
        two_weapons = all(self.melee_weapon_in(creature, hand) for hand in WEAPON_HANDS)
        out = []
        order = {WEAPON_HANDS[0]: 0, WEAPON_HANDS[1]: 1, MISSILE_SLOT: 2}
        for index, item, typ, slot in sorted(weapons, key=lambda w: order[w[3]]):
            missile = slot == MISSILE_SLOT
            parts = [("DEX", table(DEX_MISSILE, dex))] if missile else [("STR", table(STR_TO_HIT, strength))]
            parts += common
            plus = struct.unpack("b", item[ITEM_PLUS:ITEM_PLUS + 1])[0]
            material = typ[0x08] & 0x0F
            if plus:
                parts.append(("weapon", plus))
            elif not typ[0x08] & 0x80 and material in MATERIAL_TO_HIT:
                parts.append((MATERIALS[material].lower(), MATERIAL_TO_HIT[material]))
            if two_weapons and not missile:
                parts.append(self.two_weapons(creature, slot))
            parts = [(why, n) for why, n in parts if n]
            out.append(WeaponHit(index, slot, self.item_label(item, typ), base - sum(n for _, n in parts), parts))
        if not out:
            parts = [(why, n) for why, n in [("STR", table(STR_TO_HIT, strength))] + common if n]
            out.append(WeaponHit(-1, -1, "unarmed", base - sum(n for _, n in parts), parts))
        return out

    def two_weapons(self, creature: int, slot: int) -> Tuple[str, int]:
        """The to-hit adjustment for an attack with the weapon in SLOT while two are ready (in
        melee), and what it's called. The game's: its DEX table for initiative, sign flipped and
        never below 0 (a bonus at DEX 5 or less). With RULE_TWO_WEAPONS, AD&D's: -2 main hand,
        -4 off hand, plus the DEX reaction adjustment, never above 0. Rangers: none either way."""
        dex = self.creature(creature)[CREATURE_ABILITIES + 1]
        sheet = self.sheet(creature)
        ranger = len(sheet) >= SHEET_FLAGS + 2 and struct.unpack_from("<H", sheet, SHEET_FLAGS)[0] & SHEET_FLAG_RANGER
        if not self.rules & RULE_TWO_WEAPONS:
            return f"two weapons at DEX {dex}", 0 if ranger else max(0, -self.dex_initiative(dex))
        hand = "off hand" if slot == WEAPON_HANDS[1] else "main hand"
        if ranger:
            return f"two weapons, {hand} (ranger)", 0
        if slot not in WEAPON_HANDS or not self.melee_weapon_in(creature, sum(WEAPON_HANDS) - slot):
            return "two weapons", 0  # not a hand's weapon, or nothing to fight with in the other hand
        return (f"two weapons, {hand} at DEX {dex}",
                min(0, TWO_WEAPON_PENALTY.get(slot, -2) + self.dex_initiative(dex)))

    def melee_weapon_in(self, creature: int, slot: int) -> bool:
        """A melee weapon (its type's class 1, as the game counts weapons ready) in SLOT: not
        a shield, a bow or a sling."""
        return any(item[ITEM_SLOT] == slot and len(typ) > 0x0A and typ[0x0A] == 1
                   for _, item, typ in self._worn(creature))

    def wears_boots(self, creature: int) -> bool:
        """Something worn on the feet (with the Options' rule, a move more in a fight)."""
        return any(item[ITEM_SLOT] == FOOT for _, item, _ in self._worn(creature))

    def ring_plus(self, creature: int) -> int:
        """The pluses of the rings a creature wears (see RING_TYPE), and of a cloak of
        protection (CLOAK_TYPE)."""
        total = 0
        for _, item, _ in self._worn(creature):
            plus = struct.unpack("b", item[ITEM_PLUS:ITEM_PLUS + 1])[0]
            kind, slot = struct.unpack_from("<H", item, ITEM_TYPE)[0], item[ITEM_SLOT]
            if plus > 0 and (kind == RING_TYPE and slot in FINGERS or kind == CLOAK_TYPE and slot == CLOAK_SLOT):
                total += plus
        return total

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

    def level_hp_group(self, cls: int) -> Optional[int]:
        """The class's hit point group: 0 priests, 1 warriors, 2 wizards, 3 rogues and psionicists."""
        if not 0 < cls < 32:
            return None
        group = self.guest.read((self.load_seg + LEVEL_HP_SEG) * 16 + 0x10 + cls, 1)[0]
        return group if group < 4 else None

    def level_hp_rule(self, cls: int) -> Optional[LevelHp]:
        group = self.level_hp_group(cls)
        if group is None:
            return None
        return LevelHp(*self.guest.read((self.load_seg + LEVEL_HP_SEG) * 16 + group * 4, 3))

    def level_hp_minimum(self, con: int) -> int:
        return self.guest.read((self.load_seg + LEVEL_HP_SEG) * 16 + 0x38 + min(max(con, 0), 25), 1)[0]

    def level_hp_con_bonus(self, con: int) -> int:
        """Hit points a warrior gains per level for a CON score (others get at most +2)."""
        base = (self.load_seg + LEVEL_HP_SEG) * 16 + LEVEL_HP_CON_BONUS
        return struct.unpack("b", self.guest.read(base + min(max(con, 0), 25), 1))[0]

    def sheet_at(self, index: int) -> bytes:
        """Character sheet number `index`."""
        return self.guest.read(far_pointer(self.guest, self.ds, SHEETS_PTR) + index * SHEET_SIZE, SHEET_SIZE)

    def creation_sheet(self) -> bytes:
        """The character being made on the creation screen."""
        return self.guest.read(far_pointer(self.guest, self.ds, CREATION_SHEET_PTR), SHEET_SIZE)

    def race_adjustment(self, race: int, ability: int) -> int:
        if not 0 < race < 16 or not 0 <= ability < 6:
            return 0
        addr = (self.load_seg + CREATION_SEG) * 16 + CREATION_RACE_OFF + race * 6 + ability
        return struct.unpack("b", self.guest.read(addr, 1))[0]

    def class_minimum(self, cls: int, ability: int) -> int:
        """The least an ability may be for a class on the creation screen (17 for its prime requisite)."""
        if not 0 < cls < 16:
            return 0
        prime, least = struct.unpack("<hB", self.guest.read(
            (self.load_seg + CREATION_SEG) * 16 + CREATION_CLASS_OFF + cls * 3, 3))
        return CREATION_PRIME_MINIMUM if prime == ability else least

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
        return Weapon(self.item_name(struct.unpack_from("<H", rec, ITEM_NAME)[0]), typ[0x0D], typ[0x0C], struct.unpack("b", typ[0x0E:0x0F])[0],
                      struct.unpack("b", rec[0x14:0x15])[0], typ[0x08] & 0x0F, bool(typ[0x08] & 0x80))

    def weapon_name(self, w: Weapon) -> str:
        material = MATERIALS[w.material] + " " if w.material < len(MATERIALS) and w.material != 4 else ""
        return f"{material}{w.name}" + (f" {w.plus:+d}" if w.plus else "")
