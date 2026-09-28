"""Watches the party and the monsters for kills, experience and level-ups.

The log notes each kill (with the creature's XP value from its character
sheet) and, when the party's XP goes up (right after a kill the party makes),
lists what each character gained and for which kills.
"""

import struct
from typing import Dict, List, NamedTuple, Optional, Tuple

from . import game
from .game import CLASS_NAMES, GameData, ordinal

MAX_COMBATANTS = 256
XP_SETTLE = 0.5  # seconds to wait for every party member's XP to change
KILL_WINDOW = 5.0  # seconds before an XP award in which kills count towards it


class Member(NamedTuple):
    name: str
    xp: int
    max_hp: int
    levels: Tuple[int, int, int]
    classes: Tuple[int, int, int]


class Kill(NamedTuple):
    name: str
    xp: int
    at: float


class PartyTracker:
    def __init__(self, game_data: GameData):
        self.game = game_data
        self.members: Optional[List[Optional[Member]]] = None
        self.monsters: Dict[int, Tuple[int, str, int]] = {}  # combatant -> (creature, name, HP)
        self.kills: List[Kill] = []
        self.xp_before: Optional[List[Optional[Member]]] = None
        self.xp_changed_at = 0.0
        self.xp_started_at = 0.0

    def reset(self) -> None:
        """Forget everything (a game was loaded)."""
        self.members = None
        self.monsters = {}
        self.kills = []
        self.xp_before = None

    def _member(self, index: int) -> Optional[Member]:
        name = self.game.creature_name(index)
        sheet = self.game.sheet(index)
        if len(sheet) < game.SHEET_SIZE or not self.game.creature(index)[game.CREATURE_NAME]:
            return None
        return Member(name, struct.unpack_from("<I", sheet, game.SHEET_XP)[0],
                      struct.unpack_from("<h", sheet, game.SHEET_MAX_HP)[0],
                      tuple(sheet[game.SHEET_LEVELS:game.SHEET_LEVELS + 3]),
                      tuple(sheet[game.SHEET_CLASSES:game.SHEET_CLASSES + 3]))

    def check(self, now: float) -> List[str]:
        out = self._check_monsters(now)
        members = [self._member(i) for i in range(game.PARTY_SIZE)]
        if self.members is None:
            self.members = members
            return out
        for old, new in zip(self.members, members):
            if old and new and old.name == new.name:
                out += self._level_changes(old, new)
        if any(old and new and old.name == new.name and new.xp != old.xp for old, new in zip(self.members, members)):
            if self.xp_before is None:
                self.xp_before = self.members
                self.xp_started_at = now
            self.xp_changed_at = now
        self.members = members
        if self.xp_before is not None and now - self.xp_changed_at >= XP_SETTLE:
            out += self._xp_line(self.xp_before, members)
            self.xp_before = None
        return out

    def _check_monsters(self, now: float) -> List[str]:
        out = []
        combatants = {c: i for c, i in self.game.combatants().items() if c >= game.PARTY_SIZE and i >= game.PARTY_SIZE}
        count = max(list(combatants.values()) + [i for i, _, _ in self.monsters.values()] + [0]) + 1
        table = self.game.creatures(count)

        def hp(index: int) -> Optional[int]:
            at = index * game.CREATURE_SIZE
            return struct.unpack_from("<h", table, at)[0] if at + 2 <= len(table) else None

        seen = {c: (i, self.game.creature_name(i) if c not in self.monsters else self.monsters[c][1], hp(i))
                for c, i in combatants.items() if hp(i) is not None}
        for combatant, (index, name, old_hp) in self.monsters.items():
            current = seen.get(combatant)
            now_hp = current[2] if current and current[0] == index else hp(index)  # gone: its record may remain
            if now_hp is not None and old_hp > 0 >= now_hp:
                out.append(self._killed(index, name, now))
        self.monsters = seen
        return out

    def _killed(self, index: int, name: str, now: float) -> str:
        sheet = self.game.sheet(index)
        xp = struct.unpack_from("<I", sheet, game.SHEET_XP_VALUE)[0] if len(sheet) >= 8 else 0
        self.kills.append(Kill(name, xp, now))
        return f"{name} is killed ({xp} XP)"

    def _level_changes(self, old: Member, new: Member) -> List[str]:
        out = []
        for slot in range(3):
            if new.levels[slot] > old.levels[slot] and new.classes[slot]:
                cls = CLASS_NAMES.get(new.classes[slot], f"class {new.classes[slot]}")
                out.append(f"{new.name} is now a {ordinal(new.levels[slot])} level {cls}")
        if new.max_hp != old.max_hp and out:
            out.append(f"    max HP {old.max_hp} -> {new.max_hp} ({new.max_hp - old.max_hp:+d})")
        elif out and max(new.levels) <= max(old.levels):
            # the game rolls hit points only when the highest of the class levels goes up
            out.append(f"    no hit point roll: that comes only when the highest class level rises "
                       f"(still {ordinal(max(new.levels))})")
        return out

    def _xp_line(self, before: List[Optional[Member]], after: List[Optional[Member]]) -> List[str]:
        gains = [f"{new.name} {new.xp - old.xp:+d}" for old, new in zip(before, after)
                 if old and new and old.name == new.name and new.xp != old.xp]
        if not gains:
            return []
        kills = [k for k in self.kills if self.xp_started_at - KILL_WINDOW <= k.at]
        self.kills = []
        line = "XP: " + ", ".join(gains)
        if kills:
            total = sum(k.xp for k in kills)
            line += f" (for {', '.join(f'{k.name} {k.xp}' for k in kills)}" + \
                (f": {total} XP)" if len(kills) > 1 else ")")
        return [line]
