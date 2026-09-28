"""Command line entry point: python -m dscompanion <command> ..."""

import argparse
import os
import sys

from . import values
from .guestmem import GuestMemory, locate
from .layout import Layout
from .process import ProcessMemory, find_dosbox_processes
from .savefile import load_party
from .search import OPS, SearchSession

DEFAULT_LAYOUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "layouts", "shattered_lands.json")
SEARCH_FILE = ".dscompanion-search.json"


class CliError(Exception):
    pass


def connect(args) -> GuestMemory:
    pid = args.pid
    if pid is None:
        found = find_dosbox_processes()
        if not found:
            raise CliError("No DOSBox process found. Start the game first, or pass --pid.")
        if len(found) > 1:
            listing = ", ".join(f"{p} ({n})" for p, n in found)
            raise CliError(f"Several DOSBox processes are running: {listing}. Pick one with --pid.")
        pid = found[0][0]
    host_base = None if args.host_base is None else values.parse_int(args.host_base)
    return locate(ProcessMemory(pid), host_base)


def hexdump(data: bytes, start: int) -> str:
    lines = []
    for row in range(0, len(data), 16):
        chunk = data[row:row + 16]
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{start + row:08x}  {' '.join(f'{b:02x}' for b in chunk):<48} {text}")
    return "\n".join(lines)


def cmd_processes(args) -> None:
    found = find_dosbox_processes()
    if not found:
        print("No DOSBox processes found.")
    for pid, name in found:
        try:
            guest = locate(ProcessMemory(pid))
            print(f"{pid:>7}  {name}  guest RAM: {guest.size // (1024 * 1024)} MB at host {guest.base:#x}")
        except Exception as e:
            print(f"{pid:>7}  {name}  ({e})")


def cmd_find_text(args) -> None:
    guest = connect(args)
    data = guest.snapshot()
    hits = guest.find(args.text.encode("cp437"), ignore_case=not args.case_sensitive, data=data)
    print(f"{len(hits)} match(es) for {args.text!r}")
    for addr in hits[:args.limit]:
        print(f"\n== {addr:#x}")
        start = max(addr - args.context, 0)
        print(hexdump(data[start:addr + args.context], start))


def cmd_dump(args) -> None:
    guest = connect(args)
    addr = values.parse_int(args.address)
    print(hexdump(guest.read(addr, values.parse_int(args.length)), addr))


def _print_candidates(session: SearchSession, limit: int) -> None:
    print(f"{len(session.candidates)} candidate(s)")
    for addr, v in list(session.candidates.items())[:limit]:
        print(f"  {addr:#010x}  {v}")


def cmd_search(args) -> None:
    guest = connect(args)
    lo, hi = 0, None
    if args.near is not None:
        near = values.parse_int(args.near)
        lo, hi = near - args.range, near + args.range
    session = SearchSession.start(guest.snapshot(), args.type, values.parse_int(args.value), lo, hi)
    session.save(SEARCH_FILE)
    _print_candidates(session, args.limit)


def cmd_next(args) -> None:
    if not os.path.exists(SEARCH_FILE):
        raise CliError("No search in progress. Start one with the 'search' command.")
    session = SearchSession.load(SEARCH_FILE)
    guest = connect(args)
    op, value = args.condition, None
    if op not in OPS:
        op, value = "eq", values.parse_int(args.condition)
    session.refine(guest.snapshot(), op, value)
    session.save(SEARCH_FILE)
    _print_candidates(session, args.limit)


def cmd_save(args) -> None:
    layout = Layout.load(args.layout)
    mem = load_party(args.file, layout)
    slots = [layout.decode_slot(i, mem.read) for i in range(layout.count)]
    slots = [s for s in slots if s[0]]
    if not slots:
        raise CliError("No party members found in this save.")
    rows = [("Name", [s[0] for s in slots])]
    rows += [(label, [s[2][i][1] for s in slots]) for i, (label, _) in enumerate(slots[0][2])]
    width = max(len(label) for label, _ in rows) + 2
    cols = [max(len(r[1][c]) for r in rows) + 2 for c in range(len(slots))]
    for label, cells in rows:
        print(label.ljust(width) + "".join(cell.ljust(w) for cell, w in zip(cells, cols)))


def cmd_view(args) -> None:
    from .viewer import run  # tkinter is only needed here
    run(Layout.load(args.layout), lambda: connect(args))


def main(argv=None) -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--pid", type=int, help="DOSBox process id (default: the only DOSBox running)")
    common.add_argument("--host-base", help="skip auto-detection: host address of guest RAM")

    p = argparse.ArgumentParser(prog="dscompanion", description="Dark Sun companion: party viewer and memory tools")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("view", parents=[common], help="open the party viewer window")
    s.add_argument("--layout", default=DEFAULT_LAYOUT, help="layout JSON file")
    s.set_defaults(func=cmd_view)

    s = sub.add_parser("save", help="show the party stored in a save file (SAVEnn.SAV)")
    s.add_argument("file")
    s.add_argument("--layout", default=DEFAULT_LAYOUT, help="layout JSON file")
    s.set_defaults(func=cmd_save)

    s = sub.add_parser("processes", help="list DOSBox processes and where their guest RAM is")
    s.set_defaults(func=cmd_processes)

    s = sub.add_parser("find-text", parents=[common], help="find text (e.g. a character name) in guest RAM")
    s.add_argument("text")
    s.add_argument("--case-sensitive", action="store_true")
    s.add_argument("--context", type=int, default=64, help="bytes of context to show around each hit")
    s.add_argument("--limit", type=int, default=20)
    s.set_defaults(func=cmd_find_text)

    s = sub.add_parser("dump", parents=[common], help="hex dump guest memory")
    s.add_argument("address")
    s.add_argument("length", nargs="?", default="256")
    s.set_defaults(func=cmd_dump)

    s = sub.add_parser("search", parents=[common], help="start a value search (e.g. current HP)")
    s.add_argument("type", choices=list(values.FORMATS))
    s.add_argument("value")
    s.add_argument("--near", help="only search around this guest address (e.g. a name hit)")
    s.add_argument("--range", type=int, default=4096, help="bytes either side of --near")
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("next", parents=[common], help="narrow the search: a new value, or " + "/".join(OPS[1:]))
    s.add_argument("condition")
    s.add_argument("--limit", type=int, default=30)
    s.set_defaults(func=cmd_next)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except Exception as e:  # report cleanly instead of with a traceback
        if os.environ.get("DSCOMPANION_DEBUG"):
            raise
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
