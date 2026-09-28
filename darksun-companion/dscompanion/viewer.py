"""The party viewer window (tkinter).

Left: one column per party slot showing the fields mapped in the layout.
Right: tools for mapping records — locate a character by name (linked records
such as the character sheet are then found automatically), and a live hex view
of a record that highlights bytes as they change. Click a byte to see it
decoded as each value type.
"""

import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional

from . import values
from .guestmem import GuestMemory
from .layout import Layout
from .process import ProcessError

REFRESH_MS = 500
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

        root.title(f"Dark Sun Companion - {layout.game or 'party viewer'}")
        root.geometry("1240x720")
        self._build()
        self.reconnect()
        self._tick()

    # ---- layout of the window -------------------------------------------------

    def _build(self) -> None:
        top = ttk.Frame(self.root, padding=6)
        top.pack(fill="x")
        self.status = tk.StringVar(value="Not connected")
        ttk.Label(top, textvariable=self.status).pack(side="left")
        ttk.Button(top, text="Save layout", command=self.save_layout).pack(side="right")
        ttk.Button(top, text="Reload layout", command=self.reload_layout).pack(side="right", padx=4)
        ttk.Button(top, text="Reconnect", command=self.reconnect).pack(side="right")

        panes = ttk.PanedWindow(self.root, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        party = ttk.Frame(panes)
        self.table = ttk.Treeview(party, show="headings")
        self.table.pack(fill="both", expand=True)
        panes.add(party, weight=1)

        tools = ttk.Frame(panes)
        panes.add(tools, weight=1)

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
        self.hit_list = tk.Listbox(locate, height=6, font="TkFixedFont")
        self.hit_list.pack(fill="x", pady=(6, 0))

        hexframe = ttk.LabelFrame(tools, text="Record bytes (changed bytes light up)", padding=6)
        hexframe.pack(fill="both", expand=True, pady=(6, 0))
        row = ttk.Frame(hexframe)
        row.pack(fill="x")
        self.hex_record = ttk.Combobox(row, width=10, state="readonly")
        self.hex_record.pack(side="left")
        ttk.Label(row, text="slot").pack(side="left", padx=(6, 2))
        self.hex_slot = self._slot_box(row)
        self.inspect = tk.StringVar(value="Click a byte to decode it.")
        ttk.Label(row, textvariable=self.inspect, font="TkFixedFont").pack(side="left", padx=8)
        self.hex = tk.Text(hexframe, font="TkFixedFont", height=20, wrap="none")
        self.hex.pack(fill="both", expand=True, pady=(6, 0))
        self.hex.tag_configure("changed", background="#ffb347", foreground="black")
        self.hex.tag_configure("selected", background="#7ab8ff", foreground="black")
        self.hex.bind("<Button-1>", self.on_hex_click)

        self._apply_layout()

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
            self.table.column(f"slot{i}", width=100, anchor="center")

    # ---- actions ----------------------------------------------------------------

    def reconnect(self) -> None:
        try:
            self.guest = self.connect()
        except Exception as e:  # shown to the user, who can fix it and retry
            self.guest = None
            self.status.set(f"Not connected: {e}")
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
        self.status.set(f"Disconnected ({err}). Start DOSBox and press Reconnect.")

    def _tick(self) -> None:
        if self.guest:
            try:
                self._refresh_table()
                self._refresh_hex()
            except ProcessError as e:
                self._disconnected(e)
        self.root.after(REFRESH_MS, self._tick)

    def _refresh_table(self) -> None:
        slots = [self.layout.decode_slot(i, self.guest.read) for i in range(self.layout.count)]
        rows = [(f"{r} @", [f"{s[1][r]:#x}" if s[1][r] is not None else "" for s in slots])
                for r in self.layout.records]
        rows.append(("Name", [s[0] for s in slots]))
        for i, f in enumerate(self.layout.fields):
            rows.append((f.label, [s[2][i][1] for s in slots]))

        existing = self.table.get_children()
        if len(existing) != len(rows):
            self.table.delete(*existing)
            existing = [self.table.insert("", "end") for _ in rows]
        for item, (label, cells) in zip(existing, rows):
            self.table.item(item, values=[label] + cells)

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
