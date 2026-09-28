"""The look of Templar's Ledger: widgets styled like Shattered Lands' own screens.

The colours are in palette.py. No artwork of the game's is copied; the
banner's rock is drawn from those colours at start-up.

Accessibility (AODA, whose standard is WCAG 2.0 level AA): text colours meet
4.5:1 contrast (see palette.py), keyboard focus is drawn in bright yellow, and
all text can be enlarged (Ctrl + / Ctrl -).
"""

import random
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Tuple

from .palette import (AMBER, BUTTON, BUTTON_LIT, DARK, DEEP, EDGE_LIT, FOCUS, LOG_COLOURS, NAME, PALE,  # noqa: F401
                      PANEL, PSI_BLUE, ROCK, SAND, SHADOW, STONE, SUBTITLE, YELLOW)

# Named fonts, so Ctrl + / Ctrl - can enlarge all text at once
BASE_SIZES = {"TkDefaultFont": 10, "TkTextFont": 10, "TkFixedFont": 10, "TkHeadingFont": 10,
              "TkMenuFont": 10, "LedgerHeading": 10, "LedgerTitle": 20, "LedgerSmall": 9}
_scale = 1.0
_fonts = {}  # tkinter deletes a named font when its Font object goes, so keep them


def _family(*preferred: str) -> str:
    available = set(tkfont.families())
    return next((f for f in preferred if f in available), preferred[-1])


def make_fonts(root: tk.Misc) -> None:
    serif = _family("Georgia", "Times New Roman", "DejaVu Serif", "Liberation Serif", "Times")
    for name, family, weight, slant in (("LedgerHeading", serif, "bold", "roman"),
                                        ("LedgerTitle", serif, "bold", "roman"),
                                        ("LedgerSmall", "TkDefaultFont", "normal", "italic")):
        if name not in _fonts:
            family = tkfont.nametofont("TkDefaultFont").actual("family") if family == "TkDefaultFont" else family
            _fonts[name] = tkfont.Font(root, name=name, family=family, weight=weight, slant=slant,
                                       size=BASE_SIZES[name])
    set_scale(root, _scale)


def set_scale(root: tk.Misc, scale: float) -> float:
    """Make all text `scale` times its usual size (0.8 to 2.5)."""
    global _scale
    _scale = min(max(scale, 0.8), 2.5)
    for name, size in BASE_SIZES.items():
        try:
            tkfont.nametofont(name).configure(size=round(size * _scale))
        except tk.TclError:
            pass
    style = ttk.Style(root)
    style.configure("Treeview", rowheight=round(20 * _scale))
    return _scale


def scale() -> float:
    return _scale


def fonts() -> Tuple[str, str, str]:
    """(title, heading, text) fonts: a heavy serif like the game's screen titles."""
    return "LedgerTitle", "LedgerHeading", "TkFixedFont"


def apply(root: tk.Tk) -> None:
    """Style the ttk widgets like the game's stone panels and buttons."""
    root.configure(background=STONE)
    make_fonts(root)
    style = ttk.Style(root)
    style.theme_use("clam")  # the theme whose bevels can be coloured
    _, heading, _ = fonts()
    # the game's stone buttons, a shade darker behind the text so it stays readable;
    # the lighter stone is kept for the bevel
    bevel = dict(background=DARK, foreground=PALE, lightcolor=EDGE_LIT, darkcolor=SHADOW,
                 bordercolor=SHADOW, focuscolor=FOCUS)
    style.configure(".", background=STONE, foreground=PALE, fieldbackground=DEEP, troughcolor=SHADOW,
                    selectbackground=PANEL, selectforeground=YELLOW, insertcolor=PALE, focuscolor=FOCUS,
                    lightcolor=STONE, darkcolor=STONE, bordercolor=SHADOW, arrowcolor=PALE)
    style.configure("TFrame", background=STONE)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("TLabel", background=STONE, foreground=PALE)
    style.configure("Status.TLabel", background=STONE, foreground=YELLOW)
    style.configure("TButton", padding=(10, 3), **bevel)
    style.map("TButton", background=[("pressed", DEEP), ("active", STONE)],
              foreground=[("pressed", YELLOW), ("active", YELLOW)],
              lightcolor=[("pressed", SHADOW)], darkcolor=[("pressed", EDGE_LIT)])
    style.configure("TCheckbutton", background=STONE, foreground=PALE, indicatorbackground=DEEP,
                    indicatorforeground=YELLOW, focuscolor=FOCUS)
    style.map("TCheckbutton", background=[("active", STONE)], foreground=[("active", YELLOW)],
              indicatorbackground=[("active", DARK)])
    style.configure("TEntry", fieldbackground=DEEP, foreground=YELLOW, insertcolor=PALE)
    style.configure("TCombobox", fieldbackground=DEEP, foreground=YELLOW, background=BUTTON,
                    arrowcolor=PALE)
    style.map("TCombobox", fieldbackground=[("readonly", DEEP)], foreground=[("readonly", YELLOW)],
              selectbackground=[("readonly", DEEP)], selectforeground=[("readonly", YELLOW)])
    root.option_add("*TCombobox*Listbox.background", DEEP)
    root.option_add("*TCombobox*Listbox.foreground", YELLOW)
    root.option_add("*TCombobox*Listbox.selectBackground", PANEL)
    root.option_add("*TCombobox*Listbox.selectForeground", YELLOW)
    style.configure("TLabelframe", background=STONE, bordercolor=SHADOW, lightcolor=EDGE_LIT, darkcolor=DARK)
    style.configure("TLabelframe.Label", background=STONE, foreground=YELLOW, font=heading)
    style.configure("TNotebook", background=STONE, bordercolor=SHADOW, tabmargins=(2, 4, 2, 0))
    style.configure("TNotebook.Tab", padding=(14, 4), font=heading, **bevel)
    # the open tab sinks into the dark panel below it, its name in the game's amber
    style.map("TNotebook.Tab", background=[("selected", DEEP), ("active", STONE)],
              foreground=[("selected", AMBER), ("active", YELLOW)],
              lightcolor=[("selected", EDGE_LIT)])
    style.configure("TPanedwindow", background=SHADOW)
    style.configure("Sash", sashthickness=6, background=DARK, lightcolor=EDGE_LIT, bordercolor=SHADOW)
    style.configure("TScrollbar", background=BUTTON, troughcolor=SHADOW, lightcolor=EDGE_LIT,
                    darkcolor=DARK, bordercolor=SHADOW, arrowcolor=PALE, gripcount=0)
    style.map("TScrollbar", background=[("active", BUTTON_LIT)])
    # the party table: yellow numbers on the dark stats panel, like the character screen
    style.configure("Treeview", background=DEEP, fieldbackground=DEEP, foreground=YELLOW,
                    bordercolor=SHADOW, lightcolor=DEEP, darkcolor=DEEP, rowheight=round(20 * _scale))
    style.map("Treeview", background=[("selected", DARK)], foreground=[("selected", AMBER)])
    style.configure("Treeview.Heading", font=heading, **bevel)
    style.map("Treeview.Heading", background=[("active", STONE)], foreground=[("active", YELLOW)])


def style_text(widget: tk.Text) -> None:
    """A log or list on the dark stone of the game's recessed panels. The border turns
    yellow while it has the keyboard focus."""
    widget.configure(background=DEEP, foreground=PALE, selectbackground=PANEL,
                     selectforeground=YELLOW, relief="flat", borderwidth=0, highlightthickness=2,
                     highlightbackground=SHADOW, highlightcolor=FOCUS)
    if isinstance(widget, tk.Text):  # a list has no insertion cursor or padding
        widget.configure(insertbackground=PALE, padx=8, pady=6)


def _rock(width: int, height: int, seed: int = 7) -> tk.PhotoImage:
    """A tile of mottled dark red rock, like the arena's walls."""
    rnd = random.Random(seed)
    # a coarse random field, smoothed, so the rock has blotches rather than static
    cw, ch = width // 4 + 2, height // 4 + 2
    coarse = [[rnd.random() for _ in range(cw)] for _ in range(ch)]
    rows = []
    for y in range(height):
        row = []
        for x in range(width):
            fx, fy = x / 4, y / 4
            ix, iy = int(fx), int(fy)
            tx, ty = fx - ix, fy - iy
            v = (coarse[iy][ix] * (1 - tx) * (1 - ty) + coarse[iy][ix + 1] * tx * (1 - ty)
                 + coarse[iy + 1][ix] * (1 - tx) * ty + coarse[iy + 1][ix + 1] * tx * ty)
            v = min(max(v + rnd.uniform(-0.12, 0.12), 0), 0.999)
            row.append(ROCK[int(v * len(ROCK))])
        rows.append("{" + " ".join(row) + "}")
    image = tk.PhotoImage(width=width, height=height)
    image.put(" ".join(rows))
    return image


class Banner(tk.Canvas):
    """The title strip: the name in amber over arena rock."""

    HEIGHT = 50

    def __init__(self, parent):
        super().__init__(parent, height=self.HEIGHT, highlightthickness=0, background=ROCK[0])
        self.tile = _rock(96, self.HEIGHT)
        title, _, _ = fonts()
        self.title_font = title
        self.bind("<Configure>", lambda _e: self.redraw())

    def redraw(self) -> None:
        """Draw at the current text size (the strip grows with the title)."""
        height = round(self.HEIGHT * _scale)
        if int(self.cget("height")) != height:
            self.configure(height=height)  # the <Configure> this causes draws again
        self.delete("all")
        width = max(self.winfo_width(), 1)
        for y in range(0, height, self.tile.height()):
            for x in range(0, width, self.tile.width()):
                self.create_image(x, y, image=self.tile, anchor="nw")
        self.create_line(0, height - 2, width, height - 2, fill=SHADOW, width=3)
        middle = height // 2
        for dx, dy, colour in ((2, 2, SHADOW), (0, 0, AMBER)):
            self.create_text(14 + dx, middle + dy, text=NAME.upper(), anchor="w", fill=colour, font=self.title_font)
        right = 14 + tkfont.nametofont(self.title_font).measure(NAME.upper()) + 14
        self.create_text(right, middle + round(4 * _scale), text=SUBTITLE, anchor="w", fill=SAND,
                         font="LedgerSmall")
