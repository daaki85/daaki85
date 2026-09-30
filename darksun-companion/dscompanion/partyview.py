"""The party as the game's own View Character screen shows it: a card for each character.

Each card has the character's figure (the creation screen's picture for their
race and sex, from the installed game), name, HP and PSP as "54/54" (PSP in
blue, as in the game), their condition, and then the character sheet: scores,
race, sex and alignment, classes and levels, experience, AC, THAC0, movement
and attacks. All of it is ordinary text in the window's fonts, so it grows with
the text size.
"""

import re
import tkinter as tk
from tkinter import ttk
from typing import Dict, List, Optional, Tuple

from . import art, game, theme

SCORES = ("STR", "DEX", "CON", "INT", "WIS", "CHA")
_NUMBER = re.compile(r"\s*\((-?\d+)\)$")


def plain(display: str) -> str:
    """ "Half-giant (5)" -> "Half-giant"."""
    return _NUMBER.sub("", display)


def number(display: str) -> Optional[int]:
    """ "Half-giant (5)" -> 5; "12" -> 12."""
    m = _NUMBER.search(display)
    if m:
        return int(m.group(1))
    try:
        return int(display)
    except ValueError:
        return None


def classes_text(fields: Dict[str, str]) -> str:
    """ "Fighter 2 / Druid 2 / Psionicist 2", from the Class and Level fields."""
    parts = []
    for i in (1, 2, 3):
        cls, level = fields.get(f"Class {i}", ""), fields.get(f"Level {i}", "")
        if cls and number(cls) not in (None, 0):
            parts.append(f"{plain(cls)} {level}".strip())
    return " / ".join(parts)


class Card(ttk.Frame):
    """One character, laid out like the game's View Character screen."""

    def __init__(self, parent, index: int):
        super().__init__(parent, style="Card.TFrame", padding=8)
        self.index = index
        self.figure_key: Optional[Tuple[int, int]] = None
        self.image: Optional[tk.PhotoImage] = None
        self.vars: Dict[str, tk.StringVar] = {}

        self.figure = ttk.Label(self, style="Card.TLabel", anchor="n")
        self.figure.grid(row=0, column=0, rowspan=4, sticky="n", padx=(0, 10))
        self._label("name", 0, 1, "CardName.TLabel")
        self._label("hp", 1, 1, "CardStat.TLabel")
        self._label("psp", 2, 1, "CardPsp.TLabel")
        self._label("status", 3, 1, "CardStatus.TLabel", wrap=True)

        sheet = ttk.Frame(self, style="CardBody.TFrame")
        sheet.grid(row=4, column=0, columnspan=2, sticky="we", pady=(8, 0))
        for i, score in enumerate(SCORES):
            ttk.Label(sheet, text=f"{score}:", style="Card.TLabel").grid(row=i, column=0, sticky="w")
            var = self.vars[score] = tk.StringVar()
            ttk.Label(sheet, textvariable=var, style="CardStat.TLabel").grid(row=i, column=1, sticky="w",
                                                                           padx=(4, 16))
        right = ("who", "alignment", "classes", "xp", "ac", "thac0", "saves", "move", "attacks", "equipment", "slots",
                 "thief")
        labels = []
        for row, key in enumerate(right):
            var = self.vars[key] = tk.StringVar()
            label = ttk.Label(sheet, textvariable=var, style="Card.TLabel")
            label.grid(row=row, column=2, sticky="nw")
            labels.append(label)
        # long lines (three classes) wrap at the card's edge rather than being cut off
        sheet.bind("<Configure>", lambda e: [l.configure(wraplength=max(e.width - l.winfo_x() - 6, 80))
                                             for l in labels])
        sheet.columnconfigure(2, weight=1)
        self.columnconfigure(1, weight=1)

    def _label(self, key: str, row: int, column: int, style: str, wrap: bool = False) -> None:
        var = self.vars[key] = tk.StringVar()
        label = ttk.Label(self, textvariable=var, style=style)
        label.grid(row=row, column=column, sticky="nw")
        if wrap:
            label.bind("<Configure>", lambda e: label.configure(wraplength=max(e.width, 120)))

    def show(self, name: str, fields: Dict[str, str], status: str, current_ac: Optional[int],
             game_art: Optional["art.GameArt"], slots=(), thief=(), equipment=(), hits=(), saves=(), boots=False) -> None:
        """`slots`: [(kind, [(spell level, left, most), ...]), ...], as GameData.spell_slots gives;
        `thief`: [(skill, percent), ...], as GameData.thief_skills gives; `hits` and `saves`,
        THAC0 with each weapon and the saves as they stand now (GameData.weapon_hits, saves_now)."""
        get = fields.get
        self.vars["name"].set(name.upper() if name else f"SLOT {self.index + 1}")
        pair = lambda cur, top: f"{get(cur, '')}/{get(top, '')}" if get(cur) else ""
        self.vars["hp"].set(f"HP: {pair('HP', 'Max HP')}")
        self.vars["psp"].set(f"PSP: {pair('PSP', 'Max PSP')}")
        self.vars["status"].set(status)
        for score in SCORES:
            self.vars[score].set(get(score, ""))
        sex, race = plain(get("Gender", "")), plain(get("Race", ""))
        self.vars["who"].set(f"{sex} {race}".strip())
        self.vars["alignment"].set(plain(get("Alignment", "")))
        self.vars["classes"].set(classes_text(fields))
        self.vars["xp"].set(f"EXP: {get('XP', '')}")
        base = get("Base AC", "")
        self.vars["ac"].set(f"AC: {current_ac}" + (f" (base {base})" if base else "")
                            if current_ac is not None else f"AC: {base} (base; no fight yet)")
        base = get("THAC0", "")
        if hits:
            each = ", ".join(f"{h.thac0} with {h.name}" for h in hits)
            self.vars["thac0"].set(f"THAC0: {each}" + (f" (base {base})" if base else ""))
        else:
            self.vars["thac0"].set(f"THAC0: {base}")
        self.vars["saves"].set(("Saves (d20 needed now): " + ", ".join(
            f"{short} {s.needs}" for short, s in zip(game.SAVE_SHORT, saves))) if len(saves) == 5 else "")
        move = get("Move", "")
        fight = number(move) + 1 if boots and number(move) is not None else None
        self.vars["move"].set(f"Move: {move}" + (f" ({fight} in a fight: boots)" if fight else ""))
        self.vars["attacks"].set(f"Attacks: {get('Attacks/round', '')} a round")
        self.vars["equipment"].set("\n".join(f"{slot.capitalize() if slot else 'Carried'}: {item}"
                                              for slot, item in equipment))
        self.vars["thief"].set(("Thief skills (before armour): " + ", ".join(f"{name} {n}%" for name, n in thief))
                               if thief else "")
        self.vars["slots"].set("\n".join(f"{kind} spells left: {game.slots_text(levels)}" for kind, levels in slots))
        key = (number(get("Race", "")) or 0, number(get("Gender", "")) or 0)
        zoom = 2 if theme.scale() >= 1.6 else 1
        if game_art and (key, zoom) != self.figure_key:
            self.figure_key = (key, zoom)
            pixels = game_art.figure(*key)
            self.image = art.photo(self, pixels, zoom, background=theme.DEEP) if pixels else None
            self.figure.configure(image=self.image or "")


class PartyCards(ttk.Frame):
    """Four cards, two by two like the game's party screen, scrolling when the text is large."""

    def __init__(self, parent, count: int):
        super().__init__(parent)
        # the cards scroll with the wheel, and with the arrow and page keys once the
        # area has the keyboard focus (outlined in yellow, like the other controls)
        self.canvas = tk.Canvas(self, background=theme.STONE, takefocus=1, highlightthickness=2,
                                highlightbackground=theme.STONE, highlightcolor=theme.FOCUS)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas, padding=4)
        window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))
        for key, amount, what in (("<Up>", -1, "units"), ("<Down>", 1, "units"), ("<Prior>", -1, "pages"),
                                  ("<Next>", 1, "pages")):
            self.canvas.bind(key, lambda _e, a=amount, w=what: self.canvas.yview_scroll(a, w))
        self.canvas.bind("<Home>", lambda _e: self.canvas.yview_moveto(0))
        self.canvas.bind("<End>", lambda _e: self.canvas.yview_moveto(1))
        self.bind_all("<MouseWheel>", self._wheel, add="+")
        self.bind_all("<Button-4>", self._wheel, add="+")
        self.bind_all("<Button-5>", self._wheel, add="+")
        self.cards: List[Card] = []
        for i in range(count):
            card = Card(self.inner, i)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=4, pady=4)
            self.cards.append(card)
        for c in (0, 1):
            self.inner.columnconfigure(c, weight=1, uniform="card")

    def _wheel(self, event) -> None:
        """Scroll the cards when the pointer is over them."""
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None and widget is not self:
            widget = widget.master
        if widget is None:
            return
        step = -1 if getattr(event, "num", 0) == 4 or getattr(event, "delta", 0) > 0 else 1
        self.canvas.yview_scroll(step, "units")
