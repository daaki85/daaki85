"""Templar's Ledger's window (tkinter), in the colours of the game's own screens.

Left: one column per party slot showing the fields mapped in the layout. For
Shattered Lands the party is found automatically; other layouts locate a
character by name (linked records such as the character sheet are then found
automatically).
Right: the dice log (when the game was started with DSCLOG), and memory tools:
name search and a live hex view of a record that highlights bytes as they
change. Click a byte to see it decoded as each value type.
"""

import struct
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict, List, Optional, Tuple

from . import art, game, launch, partyview, spellbook, theme, values
from .dicelog import RULE_BOOTS, RULE_HELMS, DiceLog, DiceLogError
from .guestmem import GuestMemory
from .layout import Layout
from .process import ProcessError

REFRESH_MS = 500
DICE_MS = 50
RETRY_SECONDS = 2.0
MAX_LOG_LINES = 3000
HIGHLIGHT_SECONDS = 3.0
HEX_PREFIX = 17  # width of "+0040  0012a3f0  "
MAX_HITS = 500


def _printable(data: bytes) -> str:
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def _query_bytes(text: str) -> bytes:
    """Search text as bytes: plain text, or "hex:" followed by hex byte values."""
    if text.lower().startswith("hex:"):
        return bytes.fromhex(text[4:])
    return text.encode("cp437", errors="replace")


# the game window's sizes (DOSBox scales the game's 320x200, with the aspect corrected)
WINDOW_CHOICES = {"Double (640x480)": 2, "Triple (960x720)": 3, "Quadruple (1280x960)": 4, "Full screen": None}

class Viewer:
    def __init__(self, root: tk.Tk, layout: Layout, connect: Callable[[], GuestMemory]):
        self.root = root
        self.layout = layout
        self.connect = connect
        self.guest: Optional[GuestMemory] = None
        self.hits: List[int] = []
        self.hex_start = 0  # guest address of the first byte in the hex view
        self.hex_data = b""
        self.prev_hex: Dict[int, int] = {}  # guest address -> last byte value
        self.changed_at: Dict[int, float] = {}  # guest address -> time it last changed
        self.ds: Optional[int] = None  # the game's data segment, once found
        self.dice: Optional[DiceLog] = None
        self.next_try = 0.0  # when to retry connecting / attaching
        # the game's portraits and font, from the player's own install (if it can be found)
        self.art = art.GameArt(launch.find_game_dir())
        self._images: List[tk.PhotoImage] = []  # Tk shows an image only while it's referenced

        root.title(f"{theme.NAME} - {layout.game or 'party viewer'}")
        root.geometry("1320x780")
        theme.apply(root)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._build()
        self.reconnect()
        self._tick()
        self._dice_tick()

    # ---- layout of the window -------------------------------------------------

    def _build(self) -> None:
        self.banner = theme.Banner(self.root)
        self.banner.pack(fill="x")
        if self.art.font:
            self.banner.use_game_font(self.art.font)
        top = ttk.Frame(self.root, padding=(6, 6, 6, 0))
        top.pack(fill="x")
        self.status = tk.StringVar(value="Not connected")
        # on a line of its own, below the buttons, so it never pushes them off at larger text sizes
        ttk.Label(self.root, textvariable=self.status, style="Status.TLabel", padding=(8, 2)).pack(fill="x")
        ttk.Button(top, text="Save layout", command=self.save_layout).pack(side="right")
        ttk.Button(top, text="Reload layout", command=self.reload_layout).pack(side="right", padx=4)
        ttk.Button(top, text="Reconnect", command=self.reconnect).pack(side="right")
        # text size, also Ctrl + / Ctrl - / Ctrl 0
        ttk.Button(top, text="A+", width=3, command=lambda: self.zoom(1.15)).pack(side="right", padx=(4, 12))
        ttk.Button(top, text="A-", width=3, command=lambda: self.zoom(1 / 1.15)).pack(side="right")
        ttk.Label(top, text="Text size").pack(side="right", padx=4)
        # the size of DOSBox's window, for the next time the game is started from here
        self.window_choice = tk.StringVar(value=self._window_label(launch.load_settings()))
        box = ttk.Combobox(top, textvariable=self.window_choice, values=list(WINDOW_CHOICES), state="readonly",
                           width=24)
        box.pack(side="right", padx=(4, 12))
        box.bind("<<ComboboxSelected>>", self._window_chosen)
        ttk.Label(top, text="Game window").pack(side="right", padx=4)
        for key, factor in (("<Control-plus>", 1.15), ("<Control-equal>", 1.15), ("<Control-KP_Add>", 1.15),
                            ("<Control-minus>", 1 / 1.15), ("<Control-KP_Subtract>", 1 / 1.15),
                            ("<Control-0>", None)):
            self.root.bind_all(key, lambda _e, f=factor: self.zoom(f))

        self.panes = panes = ttk.PanedWindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        # room for all four characters' columns before the logs take the rest
        self.root.after(200, self._fit_party)

        party_tabs = ttk.Notebook(panes)
        party_tabs.enable_traversal()
        panes.add(party_tabs, weight=1)
        # the party as the game's View Character screen shows it
        self.cards = partyview.PartyCards(party_tabs, self.layout.count)
        party_tabs.add(self.cards, text="Characters", underline=0)
        # every field the layout maps, in a table
        party = ttk.Frame(party_tabs)
        party_tabs.add(party, text="All fields", underline=0)
        self.table = ttk.Treeview(party, show="headings")
        across = ttk.Scrollbar(party, orient="horizontal", command=self.table.xview)
        self.table.configure(xscrollcommand=across.set)
        across.pack(side="bottom", fill="x")
        self.table.pack(fill="both", expand=True)

        tabs = ttk.Notebook(panes)
        panes.add(tabs, weight=1)
        tabs.enable_traversal()  # Ctrl+Tab between tabs, Alt + the underlined letter

        dice = ttk.Frame(tabs, padding=6)
        tabs.add(dice, text="Dice log", underline=5)
        row = ttk.Frame(dice)
        row.pack(fill="x")
        ttk.Button(row, text="Clear", command=lambda: self.dice_text.delete("1.0", "end")).pack(side="right")
        ttk.Button(row, text="Save...", command=lambda: self.save_text(self.dice_text, "dice log")).pack(
            side="right", padx=4)
        # (the switches are on the Options tab, leaving this one to the log)
        self.dice_status = tk.StringVar(value="Waiting for the game...")
        ttk.Label(row, textvariable=self.dice_status).pack(side="left", fill="x")
        # the round's order stays here while the log scrolls on: who acts now, who is still to come
        self.round_line = tk.StringVar(value="")
        self.round_label = ttk.Label(dice, textvariable=self.round_line, style="Status.TLabel", wraplength=900,
                                     justify="left")
        self.round_label.pack(fill="x", pady=(4, 0))
        self.round_label.bind("<Configure>", lambda e: self.round_label.configure(wraplength=max(200, e.width - 8)))
        box = ttk.Frame(dice)
        box.pack(fill="both", expand=True, pady=(6, 0))
        self.dice_text = tk.Text(box, font="TkFixedFont", wrap="word", height=20)
        theme.style_text(self.dice_text)
        scroll = ttk.Scrollbar(box, command=self.dice_text.yview)
        self.dice_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.dice_text.pack(side="left", fill="both", expand=True)
        for tag, colour in theme.LOG_COLOURS.items():
            self.dice_text.tag_configure(tag, foreground=colour)
        self.dice_text.tag_configure("round", underline=True, spacing1=8)  # a gap before each round

        talk = ttk.Frame(tabs, padding=6)
        tabs.add(talk, text="Dialogue", underline=1)
        row = ttk.Frame(talk)
        row.pack(fill="x")
        ttk.Button(row, text="Clear", command=self.clear_dialogue).pack(side="right")
        ttk.Button(row, text="Save...", command=lambda: self.save_text(self.talk_text, "dialogue")).pack(
            side="right", padx=4)
        # the game shows only a face; the player can name it (right-click a name, or this button
        # for the latest speaker), and the name sticks for every line from that portrait
        ttk.Button(row, text="Name speaker...", command=lambda: self.name_speaker(self._last_portrait)).pack(
            side="right")
        box = ttk.Frame(talk)
        box.pack(fill="both", expand=True, pady=(6, 0))
        self.talk_text = tk.Text(box, wrap="word", height=20, font="TkTextFont")
        theme.style_text(self.talk_text)
        self.talk_text.configure(foreground=theme.AMBER)  # the game's dialogue text
        scroll = ttk.Scrollbar(box, command=self.talk_text.yview)
        self.talk_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.talk_text.pack(side="left", fill="both", expand=True)
        self.talk_text.tag_configure("speaker", font=theme.fonts()[1], foreground=theme.YELLOW)
        self.talk_text.tag_configure("reply", foreground=theme.PALE)
        self.talk_text.tag_configure("chosen", foreground=theme.GREEN)
        self._last_portrait: Optional[int] = None
        self.talk_text.tag_bind("speaker", "<Button-3>", self._speaker_clicked)

        # what each spell and psionic power really does, from the game's records
        spells = ttk.Frame(tabs, padding=6)
        tabs.add(spells, text="Spells", underline=0)
        row = ttk.Frame(spells)
        row.pack(fill="x")
        ttk.Label(row, text="Show").pack(side="left")
        self.spell_kind = tk.StringVar(value="All")
        kind = ttk.Combobox(row, textvariable=self.spell_kind, state="readonly", width=10,
                            values=("All", "Wizard", "Priest", "Psionic"))
        kind.pack(side="left", padx=4)
        kind.bind("<<ComboboxSelected>>", lambda _e: self.show_spells())
        ttk.Button(row, text="Save...", command=lambda: self.save_text(self.spell_text, "spells")).pack(side="right")
        ttk.Button(row, text="Refresh", command=self.show_spells).pack(side="right", padx=4)
        self.spells_party = tk.BooleanVar(value=False)
        ttk.Checkbutton(spells, text="Only spells the party has a caster level for", variable=self.spells_party,
                        command=self.show_spells).pack(anchor="w", pady=(4, 0))
        box = ttk.Frame(spells)
        box.pack(fill="both", expand=True, pady=(6, 0))
        self.spell_text = tk.Text(box, wrap="word", height=20, font="TkTextFont")
        theme.style_text(self.spell_text)
        scroll = ttk.Scrollbar(box, command=self.spell_text.yview)
        self.spell_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.spell_text.pack(side="left", fill="both", expand=True)
        self.spell_text.tag_configure("name", font=theme.fonts()[1], foreground=theme.YELLOW)
        self.spell_text.insert("end", "Connect to the game to read its spells.")
        tabs.bind("<<NotebookTabChanged>>", lambda _e: self.show_spells()
                  if tabs.select() == str(spells) and not self._spells_shown else None)
        self._spells_shown = False

        tools = ttk.Frame(tabs, padding=6)
        tabs.add(tools, text="Memory tools", underline=0)

        locate = ttk.LabelFrame(tools, text="Locate by name (or hex:14 16 12 for bytes)", padding=6)
        locate.pack(fill="x")
        row = ttk.Frame(locate)
        row.pack(fill="x")
        self.search_text = tk.StringVar()
        entry = ttk.Entry(row, textvariable=self.search_text, width=24)
        entry.pack(side="left")
        entry.bind("<Return>", lambda _e: self.search_name())
        ttk.Button(row, text="Search", command=self.search_name).pack(side="left", padx=4)
        row = ttk.Frame(locate)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="Assign selected name hit to slot").pack(side="left", padx=(0, 2))
        self.assign_slot = self._slot_box(row)
        ttk.Button(row, text="Assign", command=self.assign_hit).pack(side="left", padx=4)
        ttk.Label(row, text="Stride").pack(side="left", padx=(12, 2))
        self.stride_text = tk.StringVar()
        ttk.Entry(row, textvariable=self.stride_text, width=8).pack(side="left")
        ttk.Button(row, text="Apply", command=self.apply_stride).pack(side="left", padx=4)
        self.hit_list = tk.Listbox(locate, height=6, font="TkFixedFont", foreground=theme.YELLOW)
        theme.style_text(self.hit_list)
        self.hit_list.configure(foreground=theme.YELLOW)
        self.hit_list.pack(fill="x", pady=(6, 0))

        hexframe = ttk.LabelFrame(tools, text="Record bytes (changed bytes light up)", padding=6)
        hexframe.pack(fill="both", expand=True, pady=(6, 0))
        row = ttk.Frame(hexframe)
        row.pack(fill="x")
        self.hex_record = ttk.Combobox(row, width=10, state="readonly")
        self.hex_record.pack(side="left")
        ttk.Label(row, text="slot").pack(side="left", padx=(6, 2))
        self.hex_slot = self._slot_box(row)
        self.show_addresses = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="Record addresses in the party table",
                        variable=self.show_addresses).pack(side="right")
        self.inspect = tk.StringVar(value="Click a byte to decode it.")
        ttk.Label(row, textvariable=self.inspect, font="TkFixedFont").pack(side="left", padx=8)
        self.hex = tk.Text(hexframe, font="TkFixedFont", height=20, wrap="none")
        theme.style_text(self.hex)
        self.hex.pack(fill="both", expand=True, pady=(6, 0))
        # underlined as well as coloured, so a change doesn't depend on seeing the colour
        self.hex.tag_configure("changed", background=theme.AMBER, foreground=theme.SHADOW, underline=True)
        self.hex.tag_configure("selected", background=theme.PSI_BLUE, foreground=theme.SHADOW)
        self.hex.bind("<Button-1>", self.on_hex_click)

        self._build_options(tabs)
        self._apply_layout()

    def _build_options(self, tabs: ttk.Notebook) -> None:
        """The Options tab: what the dice log shows, and what the Ledger adds to the game."""
        options = ttk.Frame(tabs, padding=6)
        tabs.add(options, text="Options", underline=0)
        settings = launch.load_settings()
        log = ttk.LabelFrame(options, text="Dice log", padding=6)
        log.pack(fill="x")
        self.show_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(log, text="Show unlabelled rolls", variable=self.show_all).pack(anchor="w")
        # the indented lines under a roll (what a THAC0 or save was made of); hiding them leaves
        # the rolls, results, turns and HP
        self.show_details = tk.BooleanVar(value=True)
        ttk.Checkbutton(log, text="Show details (the sums behind each roll)", variable=self.show_details,
                        command=lambda: self.dice_text.tag_configure("detail", elide=not self.show_details.get())
                        ).pack(anchor="w", pady=(4, 0))
        in_game = ttk.LabelFrame(options, text="In the game (when started with the dice log)", padding=6)
        in_game.pack(fill="x", pady=(8, 0))
        # the game's own window, at the end of each turn in a fight: that turn's rolls
        self.popups = tk.BooleanVar(value=bool(settings.get("turn_popups", True)))
        ttk.Checkbutton(in_game, text="Show each turn's rolls in the game (click Continue to go on)",
                        variable=self.popups, command=self._popups_changed).pack(anchor="w")
        self.popup_detail = tk.BooleanVar(value=settings.get("turn_popups_detail", True))
        ttk.Checkbutton(in_game, text="... in detail, as in the log (MORE shows the next lines)",
                        variable=self.popup_detail, command=self._popups_changed).pack(anchor="w", padx=(20, 0))
        # the game's Look box, on a monster in a fight: what hurts it, then all of it in a window
        self.monster_info = tk.BooleanVar(value=bool(settings.get("monster_info", True)))
        ttk.Checkbutton(in_game, text="Describe monsters when you Look at them in a fight (defences, then a window)",
                        variable=self.monster_info, command=self._popups_changed).pack(anchor="w", pady=(4, 0))
        rules = ttk.LabelFrame(options, text="Rule changes (in games started with the dice log)", padding=6)
        rules.pack(fill="x", pady=(8, 0))
        self.helm_ac = tk.BooleanVar(value=bool(settings.get("helm_ac", True)))
        ttk.Checkbutton(rules, text="Helms give AC 1 (the game's helms give none)", variable=self.helm_ac,
                        command=self._popups_changed).pack(anchor="w")
        self.boots_move = tk.BooleanVar(value=bool(settings.get("boots_move", True)))
        ttk.Checkbutton(rules, text="Boots give 1 more move in a fight", variable=self.boots_move,
                        command=self._popups_changed).pack(anchor="w", pady=(4, 0))
        # the companion's own item: a Ring +1 on the dead prisoner in the arena (ring.py)
        self.arena_ring = tk.BooleanVar(value=bool(settings.get("arena_ring", True)))
        ttk.Checkbutton(in_game, text="Put a Ring of Protection +1 (+1 AC, +1 on saves) on the dead prisoner in the arena",
                        variable=self.arena_ring, command=self._popups_changed).pack(anchor="w", pady=(4, 0))

    def _slot_box(self, parent) -> ttk.Combobox:
        box = ttk.Combobox(parent, width=3, state="readonly")
        box.pack(side="left")
        return box

    def _apply_layout(self) -> None:
        """Refresh everything that depends on the layout (after loading or reloading it)."""
        slots = [str(i + 1) for i in range(self.layout.count)]
        for box in (self.assign_slot, self.hex_slot):
            box.configure(values=slots)
            box.current(0)
        self.hex_record.configure(values=list(self.layout.records))
        self.hex_record.set(self.layout.name.record)
        stride = self.layout.name_record.stride
        self.stride_text.set("" if stride is None else f"{stride:#x}")

        cols = ["field"] + [f"slot{i}" for i in range(self.layout.count)]
        self.table.delete(*self.table.get_children())
        self.table.configure(columns=cols)
        self.table.heading("field", text="")
        self.table.column("field", width=150, anchor="w", stretch=False)
        for i in range(self.layout.count):
            self.table.heading(f"slot{i}", text=f"Slot {i + 1}")
            self.table.column(f"slot{i}", width=118, anchor="center")

    # ---- actions ----------------------------------------------------------------

    def zoom(self, factor: Optional[float]) -> None:
        """Enlarge or shrink all text (None: back to the usual size)."""
        theme.set_scale(self.root, 1.0 if factor is None else theme.scale() * factor)
        self.banner.redraw()
        self._fit_party()

    def _fit_party(self) -> None:
        """Columns wide enough for the text size, and the divider moved to fit them."""
        field, slot = round(150 * theme.scale()), round(118 * theme.scale())
        self.table.column("field", width=field, minwidth=field, stretch=False)
        for i in range(self.layout.count):
            self.table.column(f"slot{i}", width=slot, minwidth=slot)
        # at large text sizes the table scrolls sideways rather than squeezing the logs
        wanted = field + slot * self.layout.count + 24
        width = self.panes.winfo_width()
        if width < 200:  # not laid out yet (a slow start): placing the divider now would hide the party
            self.root.after(200, self._fit_party)
            return
        place = min(wanted, int(width * 0.55))
        if self.panes.sashpos(0, place) < place // 2:  # the panes weren't ready after all: again soon
            self.root.after(200, self._fit_party)

    def save_text(self, widget: tk.Text, what: str) -> None:
        """Save a log as a text file (to read with other tools, such as a screen reader)."""
        path = filedialog.asksaveasfilename(title=f"Save the {what}", defaultextension=".txt",
                                            initialfile=f"{what.replace(' ', '-')}.txt",
                                            filetypes=[("Text", "*.txt"), ("All files", "*.*")])
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(widget.get("1.0", "end-1c"))

    def reconnect(self, quiet: bool = False) -> None:
        self.ds = None
        self.dice = None
        try:
            self.guest = self.connect()
        except Exception as e:  # shown to the user, who can fix it and retry
            self.guest = None
            if not quiet or not self.status.get().startswith("Not connected"):
                self.status.set(f"Not connected: {e}")
            self.next_try = time.monotonic() + RETRY_SECONDS
            return
        self.status.set(f"Connected to DOSBox pid {self.guest.proc.pid}, "
                        f"guest RAM {self.guest.size // (1024 * 1024)} MB at host {self.guest.base:#x}")

    def reload_layout(self) -> None:
        try:
            self.layout = Layout.load(self.layout.path)
        except (OSError, ValueError, KeyError) as e:
            messagebox.showerror("Layout", f"Could not load {self.layout.path}:\n{e}")
            return
        self._apply_layout()

    def save_layout(self) -> None:
        self.layout.save()
        messagebox.showinfo("Layout", f"Saved slots to {self.layout.path}")

    def search_name(self) -> None:
        text = self.search_text.get().strip()
        if not text or not self.guest:
            return
        try:
            pattern = _query_bytes(text)
        except ValueError:
            messagebox.showerror("Search", "After hex: give byte values like 14 16 12")
            return
        try:
            data = self.guest.snapshot()
        except ProcessError as e:
            self._disconnected(e)
            return
        self.hits = self.guest.find(pattern, ignore_case=True, data=data)
        self.hit_list.delete(0, "end")
        for addr in self.hits[:MAX_HITS]:
            self.hit_list.insert("end", f"{addr:#010x}  {_printable(data[addr:addr + 40])}")
        if not self.hits:
            self.hit_list.insert("end", "No matches.")
        elif len(self.hits) > MAX_HITS:
            self.hit_list.insert("end", f"... {len(self.hits) - MAX_HITS} more")

    def assign_hit(self) -> None:
        sel = self.hit_list.curselection()
        if not sel or sel[0] >= len(self.hits):
            messagebox.showinfo("Assign", "Select a search hit first.")
            return
        slot = int(self.assign_slot.get()) - 1
        self.layout.clear_slot(slot)
        self.layout.name_record.slots[slot] = self.hits[sel[0]] - (self.layout.name.offset or 0)
        self.link_records()
        self.hex_slot.current(slot)
        self.prev_hex.clear()
        self.changed_at.clear()

    def link_records(self) -> None:
        """Find linked records (e.g. character sheets) for every located slot."""
        if not self.guest:
            return
        try:
            data = self.guest.snapshot()
        except ProcessError as e:
            self._disconnected(e)
            return
        name = self.layout.name
        for slot, addr in enumerate(self.layout.name_record.addresses()):
            if addr is not None and name.display(data[addr:addr + (name.offset or 0) + name.length], 0):
                self.layout.link_slot(slot, data)

    def apply_stride(self) -> None:
        text = self.stride_text.get().strip()
        try:
            self.layout.name_record.stride = values.parse_int(text) if text else None
        except ValueError:
            messagebox.showerror("Stride", f"Not a number: {text}")
            return
        self.link_records()

    def on_hex_click(self, event) -> str:
        line, col = (int(x) for x in self.hex.index(f"@{event.x},{event.y}").split("."))
        column = (col - HEX_PREFIX) // 3
        i = (line - 1) * 16 + column
        if col < HEX_PREFIX or column >= 16 or i >= len(self.hex_data):
            return "break"
        base = self._hex_base() or 0
        offset = self.hex_start + i - base
        parts = [f"{t}={v}" for t in ("u8", "s8", "u16", "s16", "u32")
                 if (v := values.decode(self.hex_data, i, t)) is not None]
        self.inspect.set(f"offset {'-' if offset < 0 else '+'}{abs(offset):#x}: " + "  ".join(parts))
        self.hex.tag_remove("selected", "1.0", "end")
        self.hex.tag_add("selected", f"{line}.{HEX_PREFIX + column * 3}",
                         f"{line}.{HEX_PREFIX + column * 3 + 2}")
        return "break"

    # ---- refresh loop --------------------------------------------------------------

    def _disconnected(self, err: Exception) -> None:
        self.guest = None
        self.dice = None
        self.ds = None
        self.status.set(f"Disconnected ({err}). Waiting for DOSBox...")
        self.dice_status.set("Waiting for the game...")
        self.next_try = time.monotonic() + RETRY_SECONDS

    def close(self) -> None:
        """Put the game's rand() back before closing, so the game keeps working."""
        try:
            if self.dice:
                self.dice.detach()
        except Exception:
            pass
        self.root.destroy()

    def _tick(self) -> None:
        if not self.guest and time.monotonic() >= self.next_try:
            self.reconnect(quiet=True)
        if self.guest:
            try:
                self._auto_locate()
                self._refresh_table()
                self._refresh_hex()
            except ProcessError as e:
                self._disconnected(e)
        self.root.after(REFRESH_MS, self._tick)

    def _auto_locate(self) -> None:
        """For Shattered Lands, point the party slots at the game's own tables."""
        if not self.layout.raw.get("auto_locate"):
            return
        if self.ds is None:
            self.ds = game.find_data_segment(self.guest)
            if self.ds is None:
                return
        creature, sheet = self.layout.records.get("creature"), self.layout.records.get("sheet")
        records = game.party_records(self.guest, self.ds)
        if not any(c for c, _ in records):  # the game restarted or quit: find DS again
            self.ds = None
            return
        for slot, (c, s) in enumerate(records[:self.layout.count]):
            if creature:
                creature.slots[slot] = c
            if sheet:
                sheet.slots[slot] = s

    # ---- dice log ---------------------------------------------------------------

    def _dice_tick(self) -> None:
        try:
            self._dice_step()
        except ProcessError as e:
            self._disconnected(e)
        self.root.after(DICE_MS, self._dice_tick)

    def _dice_step(self) -> None:
        if not self.guest:
            return
        now = time.monotonic()
        if self.dice is None or not self.dice.attached:
            if now < self.next_try:
                return
            self.next_try = now + RETRY_SECONDS
            if self.dice is None:
                self.dice = DiceLog(self.guest)
                self.dice.speaker_names = launch.speaker_names()
                self.dice.learned_speakers = launch.learned_speakers()
                self.dice.popups = self.popups.get()
                self.dice.popup_detail = self.popup_detail.get()
                self.dice.monster_info = self.monster_info.get()
                self.dice.arena_ring = self.arena_ring.get()
                self.dice.rules = self._rules()
            try:
                self.dice_status.set(self.dice.attach())
            except DiceLogError as e:
                self.dice_status.set(str(e))
            return
        if now >= self.next_try:  # every couple of seconds: has the game restarted?
            self.next_try = now + RETRY_SECONDS
            if not self.dice.still_patched():
                self.dice.detach()
                self.dice_status.set("The game restarted; attaching again...")
                return
        lines = self.dice.lines(self.show_all.get())
        if lines:
            self._append_dice(lines)
        self.round_line.set(self._round_text())
        learned = self.dice.take_speakers()
        if learned:  # names worked out from conversations: keep them, and show them on earlier lines
            launch.add_learned_speakers(learned)
            for portrait in learned:
                self._rename_portrait(portrait)
        talk = self.dice.take_dialogue()
        if talk:
            self._append_dialogue(talk)

    def _round_text(self) -> str:
        """The round in progress, in initiative order: who acts now, who is still to come."""
        try:
            status = self.dice.round_status()
        except (struct.error, IndexError, ValueError, OSError):
            return ""
        if not status:
            return ""
        def names(rows):
            return ", ".join(f"{name} {score}" for name, score in rows)
        parts = [f"Round {status['round']}." if status["round"] else "This round."]
        if status["now"]:
            parts.append(f"Now: {status['now'][0]} ({status['now'][1]}).")
        parts.append(f"Still to act: {names(status['next'])}." if status["next"] else "No one else to act.")
        if status["done"]:
            parts.append(f"Done: {names(status['done'])}.")
        if status["down"]:
            parts.append(f"Down: {names(status['down'])}.")
        return " ".join(parts)

    @staticmethod
    def _window_label(settings: dict) -> str:
        if settings.get("fullscreen"):
            return "Full screen"
        scale = settings.get("window_scale", launch.DEFAULT_SCALE)
        return next((label for label, v in WINDOW_CHOICES.items() if v == scale), "Triple (960x720)")

    def _window_chosen(self, _event=None) -> None:
        """Remember the game window's size; it applies the next time the game is started."""
        scale = WINDOW_CHOICES[self.window_choice.get()]
        settings = launch.load_settings()
        if scale is None:
            settings["fullscreen"] = True
        else:
            settings["fullscreen"] = False
            settings["window_scale"] = scale
        launch.save_settings(settings)
        self.status.set(f"Game window: {self.window_choice.get()}, from the next time you start the game "
                        "(Alt+Enter switches full screen while playing).")

    def _popups_changed(self) -> None:
        on = self.popups.get()
        settings = launch.load_settings()
        settings["turn_popups"] = on
        settings["turn_popups_detail"] = self.popup_detail.get()
        settings["monster_info"] = self.monster_info.get()
        settings["arena_ring"] = self.arena_ring.get()
        settings["helm_ac"] = self.helm_ac.get()
        settings["boots_move"] = self.boots_move.get()
        launch.save_settings(settings)
        if self.dice is not None:
            self.dice.set_popups(on)
            self.dice.popup_detail = self.popup_detail.get()
            self.dice.set_monster_info(self.monster_info.get())
            self.dice.arena_ring = self.arena_ring.get()
            self.dice.set_rules(self._rules())

    def _rules(self) -> int:
        return (RULE_HELMS if self.helm_ac.get() else 0) | (RULE_BOOTS if self.boots_move.get() else 0)

    def show_spells(self) -> None:
        """Fill the Spells tab from the running game's records."""
        self.spell_text.delete("1.0", "end")
        if not self.guest or self.ds is None:
            self.spell_text.insert("end", "Connect to the game to read its spells.")
            return
        try:
            spells = spellbook.all_spells(game.GameData(self.guest, self.ds))
        except (struct.error, IndexError, ValueError, OSError) as e:
            self.spell_text.insert("end", f"Couldn't read the spells: {e}")
            return
        kind = self.spell_kind.get()
        shown = [s for s in spells if (kind == "All" or s.magic == kind)
                 and (not self.spells_party.get() or s.casters)]
        for info in shown:
            first, *rest = info.lines()
            self.spell_text.insert("end", first + "\n", "name")
            self.spell_text.insert("end", "".join(line + "\n" for line in rest) + "\n")
        if not shown:
            self.spell_text.insert("end", "No spells to show.")
        self._spells_shown = True

    def _speaker_clicked(self, event) -> None:
        tags = self.talk_text.tag_names(f"@{event.x},{event.y}")
        portrait = next((int(t.split()[1]) for t in tags if t.startswith("portrait ")), None)
        self.name_speaker(portrait)

    def name_speaker(self, portrait: Optional[int]) -> None:
        """Ask for a name for a dialogue portrait, remember it, and show it on every line from it."""
        from tkinter import simpledialog
        if portrait is None or self.dice is None:
            messagebox.showinfo("Name speaker", "No one with a portrait has spoken yet.", parent=self.root)
            return
        shown = self.dice.speaker(portrait)
        name = simpledialog.askstring(
            "Name speaker", f"Name for the speaker shown as \"{shown}\" (portrait {portrait}).\n"
            "Leave it empty to go back to the default.", initialvalue=self.dice.speaker_names.get(portrait, ""),
            parent=self.root)
        if name is None:
            return
        name = " ".join(name.split())
        launch.set_speaker_name(portrait, name)
        if name:
            self.dice.speaker_names[portrait] = name
        else:
            self.dice.speaker_names.pop(portrait, None)
        self._rename_portrait(portrait)

    def _rename_portrait(self, portrait: int) -> None:
        """Show a portrait's current name on every line already shown from it."""
        tag = f"portrait {portrait}"
        ranges = self.talk_text.tag_ranges(tag)
        for start, end in reversed(list(zip(ranges[0::2], ranges[1::2]))):
            self.talk_text.delete(start, end)
            self.talk_text.insert(start, self.dice.speaker(portrait), ("speaker", tag))

    def clear_dialogue(self) -> None:
        self.talk_text.delete("1.0", "end")
        self._images.clear()

    def _append_dialogue(self, entries) -> None:
        at_end = self.talk_text.yview()[1] >= 0.999
        for entry in entries:
            if entry.chosen:  # the player's answer to the replies above
                self.talk_text.delete("end-2c")  # into the gap under the replies
                self.talk_text.insert("end", f"  You chose: {entry.chosen}\n\n", "chosen")
                continue
            face = self.art.portrait(entry.portrait) if entry.portrait else None
            if face:  # the game's portrait, twice its size (more at larger text sizes)
                image = art.photo(self.root, face, max(2, round(2 * theme.scale())), background=theme.DEEP)
                self._images.append(image)
                self.talk_text.image_create("end", image=image, padx=2, pady=4, align="center")
                self.talk_text.insert("end", " ")
            tags = ("speaker", f"portrait {entry.portrait}") if entry.portrait else ("speaker",)
            self.talk_text.insert("end", self.dice.speaker(entry.portrait), tags)
            self.talk_text.insert("end", "\n")
            if entry.portrait:
                self._last_portrait = entry.portrait
            if entry.text:
                self.talk_text.insert("end", entry.text + "\n")
            if entry.title:
                self.talk_text.insert("end", f"  ({entry.title})\n", "reply")
            for n, reply in enumerate(entry.replies, 1):
                self.talk_text.insert("end", f"  {n}. {reply}\n", "reply")
            self.talk_text.insert("end", "\n")
        if at_end:
            self.talk_text.see("end")

    def _append_dice(self, lines: List[str]) -> None:
        at_end = self.dice_text.yview()[1] >= 0.999
        for line in lines:
            tag = ("round" if line.startswith(("Round ", "Initiative: ")) else
                   "turn" if line.endswith("'s turn") else
                   "save" if " saves vs " in line or " magic resistance " in line else
                   "hit" if "-> HIT" in line else
                   "miss" if "-> miss" in line else
                   "detail" if line.startswith("    ") else
                   "damage" if line.startswith("  ") or " damage: " in line else "other")
            self.dice_text.insert("end", line + "\n", tag)
        excess = int(self.dice_text.index("end-1c").split(".")[0]) - MAX_LOG_LINES
        if excess > 0:
            self.dice_text.delete("1.0", f"{excess + 1}.0")
        if at_end:
            self.dice_text.see("end")

    def _ac_rows(self, slots) -> List[Tuple[str, List[str]]]:
        """The AC the game last worked out for each character in a fight, and what it was made
        of, as the dice log sees them; "-" until then."""
        labels = ("Current AC", "  AC: armour, shield", "  AC: DEX", "  AC: spells, rings, other")
        if not (self.dice and self.dice.attached and self.ds is not None and "creature" in self.layout.records):
            return [(label, ["-"] * len(slots)) for label in labels]
        table = game.far_pointer(self.guest, self.ds, game.CREATURES_PTR)
        columns = []
        for s in slots:
            addr = s[1].get("creature")
            index = (addr - table) // game.CREATURE_SIZE if addr is not None else None
            ac, detail = self.dice.last_ac.get(index), self.dice.ac_detail.get(index)
            if detail is None or detail.total != ac:
                columns.append(["-" if ac is None else str(ac), "-", "-", "-"])
            else:
                columns.append([str(ac)] + [f"{v:+d}" for v in (detail.armour, detail.dex, detail.other)])
        return [(label, [c[i] for c in columns]) for i, label in enumerate(labels)]

    def _now_rows(self, slots) -> List[Tuple[str, List[str]]]:
        """THAC0 with each weapon ready, and the d20 each save needs, as they stand now."""
        labels = ("  THAC0 now, each weapon", "  Saves now " + "/".join(game.SAVE_SHORT))
        if self.ds is None:
            return [(label, [""] * len(slots)) for label in labels]
        gd = game.GameData(self.guest, self.ds)
        table = game.far_pointer(self.guest, self.ds, game.CREATURES_PTR)
        hits, saves = [], []
        for s in slots:
            addr = s[1].get("creature")
            index = (addr - table) // game.CREATURE_SIZE if addr is not None else None
            try:
                known = index is not None and 0 <= index < game.PARTY_SIZE
                hits.append(", ".join(f"{h.thac0} {h.name}" for h in gd.weapon_hits(index)) if known else "")
                saves.append(" ".join(str(x.needs) for x in gd.saves_now(index)) if known else "")
            except (struct.error, IndexError, ValueError):
                hits.append("")
                saves.append("")
        return [(labels[0], hits), (labels[1], saves)]

    def _member_slots(self, slots) -> List[list]:
        """Each slot's spell slots (GameData.spell_slots), or [] when the game isn't running."""
        if self.ds is None:
            return [[] for _ in slots]
        gd = game.GameData(self.guest, self.ds)
        table = game.far_pointer(self.guest, self.ds, game.CREATURES_PTR)
        out = []
        for s in slots:
            addr = s[1].get("creature")
            index = (addr - table) // game.CREATURE_SIZE if addr is not None else None
            try:
                out.append(gd.spell_slots(index) if index is not None and 0 <= index < 4 else [])
            except (struct.error, IndexError):
                out.append([])
        return out

    def _slot_rows(self, slots) -> List[Tuple[str, List[str]]]:
        """'Wizard spells left' / 'Priest spells left': '1st 3/5, 2nd 2/3', left of the most."""
        per_member = [dict(m) for m in self._member_slots(slots)]
        rows = [(f"{kind} spells left", [game.slots_text(m.get(kind, [])) for m in per_member])
                for kind, _ in game.MAGIC_KINDS]
        if self.ds is not None:  # each thief's skills as they stand (equipment and effects)
            gd = game.GameData(self.guest, self.ds)
            table = game.far_pointer(self.guest, self.ds, game.CREATURES_PTR)
            cells = []
            for s in slots:
                addr = s[1].get("creature")
                skills = gd.thief_skills_now((addr - table) // game.CREATURE_SIZE) if addr is not None else []
                cells.append(" ".join(f"{n}" for _, n in skills))
            rows.append(("Thief skills PP/OL/FT/HN/CW", cells))
            worn = []
            for s in slots:
                addr = s[1].get("creature")
                items = gd.equipment((addr - table) // game.CREATURE_SIZE) if addr is not None else []
                worn.append(", ".join(f"{slot}: {item}" if slot else item for slot, item in items))
            rows.append(("Equipment", worn))
        return rows

    def _refresh_table(self) -> None:
        slots = [self.layout.decode_slot(i, self.guest.read) for i in range(self.layout.count)]
        rows = [(f"{r} @", [f"{s[1][r]:#x}" if s[1][r] is not None else "" for s in slots])
                for r in self.layout.records] if self.show_addresses.get() else []
        for i, s in enumerate(slots):  # the game shows names in capitals
            self.table.heading(f"slot{i}", text=s[0].upper() if s[0] else f"Slot {i + 1}")
        labels = [f.label for f in self.layout.fields]
        for i, f in enumerate(self.layout.fields):
            cells = [s[2][i][1] for s in slots]
            if f"Max {f.label}" in labels:  # "54/54", as the game shows HP and PSP
                top = labels.index(f"Max {f.label}")
                cells = [f"{c}/{s[2][top][1]}" if c != "" else "" for c, s in zip(cells, slots)]
            elif f.label.startswith("Max ") and f.label[4:] in labels:
                continue
            rows.append((f.label, cells))
            if f.label == "Base AC":
                rows += self._ac_rows(slots)
            elif f.label == "THAC0":
                rows += self._now_rows(slots)[:1]
            elif f.label == "Save: Spell":
                rows += self._now_rows(slots)[1:]
        rows += self._slot_rows(slots)

        self._refresh_cards(slots)
        existing = self.table.get_children()
        if len(existing) != len(rows):
            self.table.delete(*existing)
            existing = [self.table.insert("", "end") for _ in rows]
        for item, (label, cells) in zip(existing, rows):
            self.table.item(item, values=[label] + cells)

    def _refresh_cards(self, slots) -> None:
        """The Characters tab: each slot's card, with its condition and current AC."""
        gd = game.GameData(self.guest, self.ds) if self.ds is not None else None
        effects = gd.effects_left() if gd else []
        combatants = gd.combatants() if gd else {}
        table = game.far_pointer(self.guest, self.ds, game.CREATURES_PTR) if gd else None
        spell_slots = self._member_slots(slots)
        for card, (name, bases, fields), member_slots in zip(self.cards.cards, slots, spell_slots):
            status, ac = "", None
            addr = bases.get("creature")
            if gd and addr is not None and table is not None:
                index = (addr - table) // game.CREATURE_SIZE
                code = self.guest.read(addr + game.CREATURE_STATUS, 1)[0]
                status = game.STATUS_NAMES.get(code, "")
                mine = [c for c, i in combatants.items() if i == index]
                names = sorted({game.effect_text(e, charges, seconds) for e, charges, seconds in effects
                                if e.owner in mine})
                if names:
                    status += (", " if status else "") + ", ".join(names)
                ac = self.dice.last_ac.get(index) if self.dice and self.dice.attached else None
            known = gd and addr is not None and table is not None
            thief = gd.thief_skills_now(index) if known else []
            equipment = gd.equipment(index) if known else []
            try:
                hits = gd.weapon_hits(index) if known and index < game.PARTY_SIZE else []
                saves = gd.saves_now(index) if known and index < game.PARTY_SIZE else []
            except (struct.error, IndexError, ValueError):
                hits, saves = [], []
            boots = bool(known and self.boots_move.get() and gd.wears_boots(index))
            card.show(name, dict(fields), status, ac, self.art, member_slots, thief, equipment, hits, saves, boots)

    def _hex_base(self) -> Optional[int]:
        record = self.layout.records.get(self.hex_record.get())
        return record.addresses()[int(self.hex_slot.get()) - 1] if record else None

    def _refresh_hex(self) -> None:
        base = self._hex_base()
        if base is None:
            self.hex_data = b""
            self._set_hex_text(f"The {self.hex_record.get()} record of slot {self.hex_slot.get()} "
                               "is not located yet.\n\n"
                               "Search for the character's name above, pick the hit\n"
                               "that looks like their record, and press Assign.", [])
            return
        self.hex_start = base - self.layout.hex_before
        self.hex_data = self.guest.read(self.hex_start, self.layout.hex_before + self.layout.hex_after)
        now = time.monotonic()
        for i, b in enumerate(self.hex_data):
            addr = self.hex_start + i
            if addr in self.prev_hex and self.prev_hex[addr] != b:
                self.changed_at[addr] = now
            self.prev_hex[addr] = b

        lines, marks = [], []
        for row in range(0, len(self.hex_data), 16):
            chunk = self.hex_data[row:row + 16]
            rel = self.hex_start + row - base
            lines.append(f"{'-' if rel < 0 else '+'}{abs(rel):04x}  {self.hex_start + row:08x}  "
                         + " ".join(f"{b:02x}" for b in chunk).ljust(48) + " " + _printable(chunk))
            for i in range(len(chunk)):
                if now - self.changed_at.get(self.hex_start + row + i, -1e9) < HIGHLIGHT_SECONDS:
                    marks.append((row // 16 + 1, HEX_PREFIX + i * 3))
        self._set_hex_text("\n".join(lines), marks)

    def _set_hex_text(self, text: str, marks) -> None:
        selected = self.hex.tag_ranges("selected")
        self.hex.delete("1.0", "end")
        self.hex.insert("1.0", text)
        for line, col in marks:
            self.hex.tag_add("changed", f"{line}.{col}", f"{line}.{col + 2}")
        if selected:
            self.hex.tag_add("selected", *selected)


def run(layout: Layout, connect: Callable[[], GuestMemory]) -> None:
    root = tk.Tk()
    Viewer(root, layout, connect)
    root.mainloop()
