"""Templar's Ledger's colours: sampled from Shattered Lands' own screens.

Every colour was sampled from the game (GOG release, in DOSBox): the grey stone
of its panels and buttons, the amber of dialogue text, the yellow of the
character screen's numbers, the dark red rock of the arena walls and the sand.

Accessibility (AODA, whose standard is WCAG 2.0 level AA): every colour used
for text has a contrast ratio of at least 4.5:1 with the background it is used
on (TEXT_PAIRS lists them; tests/test_theme.py checks each one). The game's
lighter stone is kept for bevels and edges, not behind text.
"""

from typing import Dict, Tuple

NAME = "Templar's Ledger"
SUBTITLE = "a companion for Dark Sun: Shattered Lands"

# Stone, darkest to lightest (panels, buttons, frames)
SHADOW = "#202038"  # outlines and text shadows
DEEP = "#30304D"  # recessed panels: the character screen's stats box
DARK = "#454561"
PANEL = "#4D4D69"
STONE = "#595971"
BUTTON = "#71718A"
BUTTON_LIT = "#7D7D96"
EDGE_LIT = "#A6A6BE"
PALE = "#D7D7E3"  # light text and bevel highlights
# Text colours
AMBER = "#FFA600"  # dialogue text
YELLOW = "#E7EB18"  # the character screen's numbers
PSI_BLUE = "#86ABFF"
GREEN = "#8FD16A"
MUTED = "#B4B4C8"  # misses: quieter than the rest, still 4.5:1 on the dark stone
DETAIL = "#C8C8D8"
# Arena rock and sand
ROCK = ("#380C00", "#450C00", "#510C00", "#5D0C00", "#690400", "#750400", "#820000")
SAND = "#D3A28A"
SAND_DARK = "#B26D55"
FOCUS = YELLOW  # keyboard focus

# Dice log line kinds -> colour on the dark stone. The words carry the meaning too
# ("HIT", "miss", "saves"), so nothing depends on telling the colours apart.
LOG_COLOURS = {
    "hit": GREEN,
    "miss": MUTED,
    "damage": AMBER,
    "save": PSI_BLUE,
    "detail": DETAIL,
    "round": PALE,
    "turn": SAND,
    "other": YELLOW,
}

# Every (text, background) pair the window uses
TEXT_PAIRS: Dict[str, Tuple[str, str]] = {
    **{f"log {k}": (v, DEEP) for k, v in LOG_COLOURS.items()},
    "log text": (PALE, DEEP),
    "dialogue": (AMBER, DEEP),
    "speaker": (YELLOW, DEEP),
    "dialogue, chosen reply": (GREEN, DEEP),
    "label": (PALE, STONE),
    "status": (YELLOW, STONE),
    "section title": (YELLOW, STONE),
    "button": (PALE, DARK),
    "button, pointer over it": (YELLOW, STONE),
    "button, pressed": (YELLOW, DEEP),
    "tab": (PALE, DARK),
    "tab, selected": (AMBER, DEEP),
    "table": (YELLOW, DEEP),
    "table, selected row": (AMBER, DARK),
    "table heading": (PALE, DARK),
    "entry": (YELLOW, DEEP),
    "character card text": (PALE, DEEP),
    "character card name and numbers": (YELLOW, DEEP),
    "character card PSP": (PSI_BLUE, DEEP),
    "character card condition": (AMBER, DEEP),
    "selected text": (YELLOW, PANEL),
    "hex, changed byte": (SHADOW, AMBER),
    "hex, selected byte": (SHADOW, PSI_BLUE),
    "title": (AMBER, ROCK[-1]),
    "subtitle": (SAND, ROCK[-1]),
}


def luminance(colour: str) -> float:
    """WCAG 2.0 relative luminance of "#rrggbb"."""
    channels = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG 2.0 contrast ratio, 1 to 21."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
