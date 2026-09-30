"""Entry point for the standalone program (PyInstaller): start the game with the in-game
rolls and stats, no window of our own. Same as: python -m dscompanion play"""
import sys

from dscompanion.__main__ import main

if __name__ == "__main__":
    sys.exit(main(["play"] + sys.argv[1:]))
