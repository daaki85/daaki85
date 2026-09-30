"""Entry point for the standalone program (PyInstaller). Starts Shattered Lands with the
in-game additions and Templar's Ledger next to it, as "python -m dscompanion launch" does;
with --no-ledger, only the game (as "python -m dscompanion play")."""
import io
import os
import sys

from dscompanion.__main__ import main


def run(argv) -> int:
    """main(), with its error message (it has no console) shown in a message box."""
    errors, sys.stderr = sys.stderr, io.StringIO()
    try:
        code = main(argv)
    finally:
        text, sys.stderr = sys.stderr.getvalue().strip(), errors
    if code and text:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("Dark Sun with Templar's Ledger", text)
        root.destroy()
    return code


if __name__ == "__main__":
    if sys.stdout is None:  # a windowed program has no console to print to
        sys.stdout = open(os.devnull, "w")
    args = sys.argv[1:]
    if "--no-ledger" in args:
        args.remove("--no-ledger")
        sys.exit(run(["play"] + args))
    sys.exit(run(["launch"] + args))
