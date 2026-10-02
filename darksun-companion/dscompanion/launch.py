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
import struct
import subprocess
from typing import Dict, List, Optional, Tuple

from . import gamepatch, gff, icons

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOS_DIR = os.path.join(HERE, "dos")
HELPER = "DSCLOG.EXE"
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


def speaker_names() -> Dict[int, str]:
    """The names the player has given dialogue portraits: {portrait: name}."""
    names = load_settings().get("speakers", {})
    return {int(k): v for k, v in names.items() if str(k).isdigit() and isinstance(v, str) and v}


def set_speaker_name(portrait: int, name: str) -> None:
    """Remember a name for a portrait (an empty name forgets it)."""
    settings = load_settings()
    names = settings.setdefault("speakers", {})
    if name:
        names[str(portrait)] = name
    else:
        names.pop(str(portrait), None)
    save_settings(settings)


def learned_speakers() -> Dict[int, str]:
    """Portrait names the Ledger worked out from conversations: {portrait: name}."""
    names = load_settings().get("speakers_learned", {})
    return {int(k): v for k, v in names.items() if str(k).isdigit() and isinstance(v, str) and v}


def pickpocketed() -> List[str]:
    """The pockets tried already (pickpocket.py), "key@game time" each: each person gets one try."""
    return list(load_settings().get("pickpocketed", []))


def set_pickpocketed(entries: List[str]) -> None:
    settings = load_settings()
    settings["pickpocketed"] = list(entries)
    save_settings(settings)


def tools_given() -> set:
    """The thieves given thieving tools already (tools.py)."""
    return set(load_settings().get("tools_given", []))


def add_tools_given(keys: List[str]) -> None:
    settings = load_settings()
    settings["tools_given"] = sorted(set(settings.get("tools_given", [])) | set(keys))
    save_settings(settings)


def add_learned_speakers(learned: Dict[int, str]) -> None:
    settings = load_settings()
    settings.setdefault("speakers_learned", {}).update({str(k): v for k, v in learned.items()})
    save_settings(settings)


def find_game_dir(given: Optional[str] = None) -> Optional[str]:
    """The game folder: `given`, the one remembered from last time, or a usual GOG location."""
    for folder in [given, load_settings().get("game_dir")] + candidate_dirs():
        if folder and is_game_dir(folder):
            return folder
    return None


SCALERS = {2: "normal2x", 3: "normal3x"}
DEFAULT_SCALE = 3
WINDOW_SCALES = (1, 2, 3, 4)


def display_lines(settings: dict) -> List[str]:
    """DOSBox's display, over GOG's settings (full screen): a window, by default three times the
    game's 320x200 (960x720 with the aspect correction GOG turns on); `window_scale` 2 makes it
    twice, 4 four times, 1 leaves it at 320x240; `fullscreen` true keeps GOG's full screen.
    Alt+Enter switches either way in DOSBox. DOSBox 0.74 has no 4x scaler, so four times is
    DOSBox scaling the window itself, which needs its OpenGL output."""
    if settings.get("fullscreen"):
        return []
    scale = settings.get("window_scale", DEFAULT_SCALE)
    scale = scale if scale in WINDOW_SCALES else DEFAULT_SCALE
    if scale == 4:
        return ["[sdl]", "fullscreen=false", "output=opengl", "windowresolution=1280x960", "[render]",
                "aspect=true", "scaler=normal2x", ""]
    return ["[sdl]", "fullscreen=false", "[render]", "aspect=true",
            "scaler=" + ("none" if scale == 1 else SCALERS[scale]), ""]


def write_conf(game_dir: str, path: str = CONF, dice_log: bool = True) -> str:
    """Our replacement for dosbox_darksun_single.conf. Without the dice log it just runs the game."""
    lines = display_lines(load_settings())
    lines += ["[autoexec]", "@echo off", "cls", 'mount c ".."']
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
    """Write DSUNLOG.EXE next to DSCLOG.EXE, and the copy of SEGOBJEX.GFF with the companion's
    item icons (icons.py; without it the items keep the plain icons). Returns why the game
    can't be patched, or None."""
    try:
        gamepatch.write_patched(_find_file(game_dir, "DSUN.EXE"), os.path.join(DOS_DIR, PATCHED_EXE))
    except (gamepatch.PatchError, OSError) as e:
        return str(e)
    try:
        objects = _find_file(game_dir, icons.OBJECTS_FILE)
        if objects:
            icons.write_objects(objects, os.path.join(DOS_DIR, icons.OBJECTS_FILE))
    except (gff.GffError, OSError, KeyError, struct.error, ValueError):
        pass  # no icons of our own: the game's plain ones
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
