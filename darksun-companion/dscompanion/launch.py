"""Starting the GOG release of Shattered Lands with the dice log.

GOG runs DOSBox with two config files: dosbox_darksun.conf (settings) and
dosbox_darksun_single.conf (the [autoexec] that mounts the game and shows a
small menu). We keep the first and replace the second with our own
[autoexec], which also mounts the companion's dos folder as D:, loads
DSCLOG.EXE into upper memory, and runs DSUNLOG.EXE: a patched copy of the
game (see gamepatch.py) that the launcher keeps in the dos folder. Nothing in
the game folder is changed.
"""

import json
import os
import string
import subprocess
from typing import List, Optional, Tuple

from . import gamepatch

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOS_DIR = os.path.join(HERE, "dos")
SETTINGS = os.path.join(HERE, "settings.json")
CONF = os.path.join(HERE, "dosbox_dicelog.conf")
PATCHED_EXE = "DSUNLOG.EXE"

GOG_SUBDIRS = (
    r"GOG Games\Dark Sun Shattered Lands",
    r"Program Files (x86)\GOG Galaxy\Games\Dark Sun Shattered Lands",
    r"Program Files\GOG Galaxy\Games\Dark Sun Shattered Lands",
    r"GOG Galaxy\Games\Dark Sun Shattered Lands",
    r"Games\Dark Sun Shattered Lands",
)


class LaunchError(Exception):
    pass


def _find_file(folder: str, name: str) -> Optional[str]:
    """`name` inside `folder`, ignoring case (for Linux, and odd installs)."""
    try:
        for entry in os.listdir(folder):
            if entry.lower() == name.lower():
                return os.path.join(folder, entry)
    except OSError:
        pass
    return None


def is_game_dir(folder: str) -> bool:
    dosbox = _find_file(folder, "DOSBOX")
    return bool(_find_file(folder, "DSUN.EXE") and dosbox and _find_file(dosbox, "DOSBox.exe"))


def candidate_dirs() -> List[str]:
    drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")] if os.name == "nt" else []
    return [os.path.join(drive, sub) for drive in drives for sub in GOG_SUBDIRS]


def load_settings() -> dict:
    try:
        with open(SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_settings(settings: dict) -> None:
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def find_game_dir(given: Optional[str] = None) -> Optional[str]:
    """The game folder: `given`, the one remembered from last time, or a usual GOG location."""
    for folder in [given, load_settings().get("game_dir")] + candidate_dirs():
        if folder and is_game_dir(folder):
            return folder
    return None


def write_conf(game_dir: str, path: str = CONF, dice_log: bool = True) -> str:
    """Our replacement for dosbox_darksun_single.conf. Without the dice log it just runs the game."""
    lines = ["[autoexec]", "@echo off", "cls", 'mount c ".."']
    if os.path.isdir(os.path.join(game_dir, "cloud_saves")):
        lines.append(r'mount C "..\cloud_saves" -t overlay')  # where GOG keeps the saves
    lines += [f'mount d "{DOS_DIR}"', "c:"]
    # the game runs from C: (the game folder), where the patched copy looks for its files
    lines += [r"lh d:\dsclog.exe", "cls", "d:\\" + PATCHED_EXE.lower()] if dice_log else ["darksun"]
    lines += ["exit", ""]
    with open(path, "w", newline="\r\n") as f:
        f.write("\n".join(lines))
    return path


def prepare_patched_game(game_dir: str) -> Optional[str]:
    """Write DSUNLOG.EXE next to DSCLOG.EXE. Returns why it couldn't, or None."""
    try:
        gamepatch.write_patched(_find_file(game_dir, "DSUN.EXE"), os.path.join(DOS_DIR, PATCHED_EXE))
    except (gamepatch.PatchError, OSError) as e:
        return str(e)
    return None


def launch(game_dir: str) -> Tuple[subprocess.Popen, Optional[str]]:
    """Start the game. Returns DOSBox's process and, if the dice log can't run, why."""
    dosbox_dir = _find_file(game_dir, "DOSBOX")
    settings_conf = _find_file(game_dir, "dosbox_darksun.conf") or _find_file(
        os.path.join(game_dir, "__support", "app"), "dosbox_darksun.conf")
    if not dosbox_dir or not settings_conf:
        raise LaunchError(f"{game_dir} does not look like the GOG install of Shattered Lands")
    problem = prepare_patched_game(game_dir)
    conf = write_conf(game_dir, dice_log=problem is None)
    return subprocess.Popen(
        [_find_file(dosbox_dir, "DOSBox.exe"), "-conf", settings_conf, "-conf", conf, "-noconsole"],
        cwd=dosbox_dir), problem
