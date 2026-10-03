"""The "downloaded from the internet" mark taken off the Ledger's own files.

Windows marks a file downloaded by a browser with a note beside it (an NTFS stream named
Zone.Identifier, the "Mark of the Web"), and unzipping a marked zip with Explorer marks every
file in it. Double-clicking a marked .bat file then shows "Open File - Security Warning: The
publisher could not be verified", every time. A .bat file can't carry a signature, so nothing in
the files themselves can prevent that.

The first .bat file the player starts has to be let through by them (Run). From then on the
Ledger, already running, takes the mark off the files in its own folder (and nothing outside
it), so the others start without asking. It does what Explorer's "Unblock" box does. Anything
that fails (another file system, a file in use) is left as it was.
"""

import os
import sys
from typing import Callable, List, Optional

MARK = ":Zone.Identifier"
FOLDER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # the Ledger's own folder
SKIP = {"__pycache__", ".git"}


def unblock(folder: str = FOLDER, remove: Optional[Callable[[str], None]] = None,
            windows: Optional[bool] = None) -> List[str]:
    """The mark taken off every file under FOLDER (on Windows only). The files it was taken off."""
    if not (sys.platform == "win32" if windows is None else windows):
        return []
    remove = remove or os.remove
    done = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d not in SKIP]
        for name in files:
            path = os.path.join(root, name)
            try:
                remove(path + MARK)
            except OSError:  # (not marked, or the mark can't be removed: as it was)
                continue
            done.append(path)
    return done
