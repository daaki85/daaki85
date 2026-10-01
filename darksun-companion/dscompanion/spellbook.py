"""The Spells tab: what each spell and psionic power really does, from the game's own records
(the same ones the dice log reads), which in places differ from the manual and AD&D."""

import struct
from typing import List, NamedTuple, Optional

from .game import (CATEGORY_DODGE, KIND_TO_SAVE, EFFECT_NAMES, EFFECT_RULES, PARTY_SIZE, PERMANENT, PSIONIC_COUNT, PSIONIC_FIRST, SAVE_NAMES,
                   SPELL_COUNT, SPELL_INFO_OFF, SPELL_INFO_SIZE, SPELL_LEVEL_CAP, SPELL_SIZE, GameData, kind_to_save,
                   ordinal)

WIZARD_LAST = 68  # spells 1-68 are wizard spells, 69-137 priest spells
# a spell record's save byte (+1Fh): bit 0 a save is allowed, bits 5-7 its kind; the game's
# table at DS:1E75h turns the kind into one of the sheet's five saves (kind 6: none;
# game.kind_to_save, with the companion's spell save rule)
NO_SAVE_KIND = 6
DAMAGE_KINDS = ((0x02, "fire"), (0x04, "cold"), (0x80, "electricity"), (0x40, "acid"), (0x01, "poison"),
                (0x08, "crushing"), (0x10, "edged"), (0x20, "pointed"), (0x100, "draining"),
                (0x400, "psionic"), (0x800, "death"))
# rolled by code of their own rather than from the record (see the README's dice log table)
OWN_DICE = {"Magic Missile", "Flame Arrow", "Minute Meteors"}
ROUND = 60  # game seconds


class SpellInfo(NamedTuple):
    spell: int
    name: str
    magic: str  # "Wizard", "Priest" or "Psionic"
    level: Optional[int]  # the spell level (None for psionic powers)
    damage: str
    save: str
    effect: str
    lasts: str
    casters: List[str]  # party members' caster levels for it

    def lines(self) -> List[str]:
        head = f"{self.name} ({self.magic.lower()}" + (f" {self.level}" if self.level else "") + ")"
        out = [head]
        for label, text in (("Damage", self.damage), ("Save", self.save), ("Effect", self.effect),
                            ("Lasts", self.lasts)):
            if text:
                out.append(f"    {label}: {text}")
        if self.casters:
            out.append(f"    Caster level in the party: {', '.join(self.casters)}")
        return out


def damage_text(gd: GameData, spell: int, rec: bytes) -> str:
    rule = gd.spell_damage(spell)
    if rule is None or (rule.sides <= 1 and not rule.step_bonus):
        return ""
    parts = []
    if rule.base_dice and rule.sides > 1:
        parts.append(f"{rule.base_dice}d{rule.sides}")
    step = (f"{rule.step_dice}d{rule.sides}" if rule.step_dice and rule.sides > 1 else "") \
        + (f"{'+' if rule.step_dice else ''}{rule.step_bonus}" if rule.step_bonus else "")
    if step:
        unit = "caster level" if rule.per_levels == 1 else f"{rule.per_levels} caster levels"
        adjust = f" (level {rule.adjust:+d})" if rule.adjust else ""
        parts.append(f"{step} for each {unit}{adjust}")
    text = " + ".join(parts)
    if step:
        text += f", counting at most level {SPELL_LEVEL_CAP}"
    kinds = struct.unpack_from("<H", rec, 0x1A)[0]
    names = [name for bit, name in DAMAGE_KINDS if kinds & bit]
    if names:
        text += f" [{', '.join(names)}]"
    if gd.spell_name(spell) in OWN_DICE:
        text += "; rolled by its own code, which leaves out the caster's level"
    return text


def save_text(gd: GameData, spell: int, rec: bytes, damages: bool) -> str:
    byte = rec[0x1F]
    kind = byte >> 5
    if not byte & 1 or kind == NO_SAVE_KIND or kind >= len(KIND_TO_SAVE):
        return "none"
    text = SAVE_NAMES.get(kind_to_save(kind, gd.rules), f"kind {kind}")
    rules = gd.spell_rules(spell)
    if rules and rules.save_modifier:
        text += f" {rules.save_modifier:+d}"
    if rules and rules.doubles_roll:
        text += f", d20 doubled (against {rules.doubled_for})"
    if len(rec) > 0x11 and rec[0x11] & CATEGORY_DODGE:
        text += ", DEX defensive adjustment counts (dodging)"
    if damages:
        text += "; saving stops the damage" if gd.save_negates_damage(spell) else "; saving halves the damage"
    return text


def effect_text(rec: bytes) -> str:
    eff = struct.unpack_from("b", rec, 0x19)[0]
    if eff > 0:
        name = EFFECT_NAMES.get(eff, f"effect {eff}")
        return name + (f": {EFFECT_RULES[eff]}" if eff in EFFECT_RULES else "")
    if eff < 0:
        return "removes " + EFFECT_NAMES.get(-eff, f"effect {-eff}")
    return ""


def lasts_text(gd: GameData, spell: int, rec: bytes) -> str:
    per_level, unit = struct.unpack_from("<Hh", rec, 5)
    if unit <= PERMANENT:  # (-9999 and -10000 both appear)
        return "until removed"
    if unit == 0:
        return ""
    rule = gd.spell_damage(spell)
    per_levels, adjust = (rule.per_levels, rule.adjust) if rule else (1, 0)
    count, sides = rec[4] & 0x0F, rec[4] >> 4
    if not per_level and not count:
        return ""  # instant
    each = "caster level" if per_levels == 1 else f"{per_levels} caster levels"
    each += f" (level {adjust:+d})" if adjust else ""
    dice = (f"{count}d{sides}" if sides > 1 else str(count)) if count else ""
    if unit < 0:  # a number of uses: blows stopped, images, one attack...
        what, times = "charge", -unit
    elif unit % ROUND == 0:
        what, times = "round", unit // ROUND
    else:
        what, times = "game second", unit
    if times == 1:
        parts = ([f"{per_level} {what}{'s' if per_level != 1 else ''} for each {each}"] if per_level else []) \
            + ([f"{dice} {what}{'s' if dice != '1' else ''}"] if dice else [])
        return " + ".join(parts)
    parts = ([f"{per_level} for each {each}"] if per_level else []) + ([dice] if dice else [])
    return f"({' + '.join(parts)}) x {times} {what}s"


def spell_level(gd: GameData, spell: int) -> Optional[int]:
    if not 1 <= spell <= SPELL_COUNT:
        return None
    return gd.guest.read(gd.load_seg * 16 + SPELL_INFO_OFF + (spell - 1) * SPELL_INFO_SIZE, 1)[0] or None


def spell_info(gd: GameData, spell: int, party: List[int]) -> Optional[SpellInfo]:
    rec = gd.spell_record(spell)
    if len(rec) < SPELL_SIZE:
        return None
    if spell >= PSIONIC_FIRST:
        magic = "Psionic"
    else:
        magic = "Wizard" if spell <= WIZARD_LAST else "Priest"
    damage = damage_text(gd, spell, rec)
    casters = []
    if magic != "Psionic":
        for creature in party:
            level = gd.effect_caster_level(creature, spell)
            if level:
                casters.append(f"{gd.creature_name(creature)} {ordinal(level)}")
    return SpellInfo(spell, gd.spell_name(spell), magic, spell_level(gd, spell), damage,
                     save_text(gd, spell, rec, bool(damage)), effect_text(rec), lasts_text(gd, spell, rec), casters)


def all_spells(gd: GameData, party: Optional[List[int]] = None) -> List[SpellInfo]:
    """Every wizard and priest spell (by level) and psionic power, from the running game."""
    party = list(range(PARTY_SIZE)) if party is None else party
    out = []
    for spell in list(range(1, SPELL_COUNT + 1)) + list(range(PSIONIC_FIRST, PSIONIC_FIRST + PSIONIC_COUNT)):
        info = spell_info(gd, spell, party)
        if info:
            out.append(info)
    order = {"Wizard": 0, "Priest": 1, "Psionic": 2}
    return sorted(out, key=lambda s: (order[s.magic], s.level or 0, s.name))
