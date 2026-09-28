# Dark Sun Companion

A companion tool for **Dark Sun: Shattered Lands** (the GOG release) running in
DOSBox, in the spirit of the Gold Box Companion. It has two parts:

- **Party viewer:** every party member's stats, live, including numbers the
  game doesn't show (THAC0, saving throws, class ids).
- **Dice log:** the rolls the game makes behind the scenes, with what they were
  compared against. For example:
  `Dag attacks Mountain Stalker: d20 = 18, needs 6 (THAC0 10 with bonuses, target AC 4) -> HIT`,
  then `Dag hits Mountain Stalker for 14: 1d6 = [2] + 12 STR 24`.

Nothing in the game folder or your save files is changed. The viewer only reads
memory. The dice log briefly patches the running game in memory (see
[How the dice log works](#how-the-dice-log-works)) and removes the patch when
you close the companion.

![The companion during a fight in Shattered Lands](docs/dicelog.png)

## Requirements

- **Windows** with DOSBox (plain DOSBox 0.74, DOSBox Staging, or the DOSBox
  bundled with the GOG/Steam release).
- **64-bit Python 3.8+** from python.org. It includes tkinter and needs no extra
  packages. Use 64-bit Python because 64-bit DOSBox can't be read from 32-bit
  Python.
- Linux works too if you can read other processes' memory (root, or
  `kernel.yama.ptrace_scope=0`).

## Running it (Windows)

The companion is a separate program that runs next to the game. You don't
install anything into the game folder.

**One-time setup**

1. Install Python from <https://www.python.org/downloads/>. On the first
   installer screen, tick **"Add python.exe to PATH"**.
2. Download this project: on GitHub open the `claude/amazing-lovelace-gcqdap`
   branch, click **Code → Download ZIP**, and unzip it anywhere.
   The files you need are in the `darksun-companion` folder.

**Every time you play**

Double-click **`Start Game with Dice Log.bat`** in the `darksun-companion`
folder. It starts Shattered Lands (through GOG's own DOSBox) with the dice log
helper loaded, and opens the companion next to it. The first time, it looks for
the game in the usual GOG folders; if it can't find it, it asks you where the
game is installed and remembers the answer.

Load your game. The party's stats fill in by themselves, and rolls appear in
the **Dice log** tab as they happen.

If you start the game the normal way instead, **`Start Companion.bat`** still
shows the party, but the dice log will say the helper isn't loaded.

**Checking a save file (no game needed):** drag a `SAVEnn.SAV` file from the
game folder onto **`Show Save.bat`**.

**From a command prompt**, the same things are:

```
python -m dscompanion launch                        # start the game with the dice log, and the viewer
python -m dscompanion view                          # the viewer only
python -m dscompanion dicelog                       # the dice log in the command prompt
python -m dscompanion save C:\path\to\SAVE01.SAV   # the party stored in a save
python -m dscompanion processes                     # is DOSBox found?
```

If more than one DOSBox is running, add `--pid <number>` (from `processes`).

## The dice log

Each line is one roll:

| Line | Meaning |
|---|---|
| `X attacks Y: d20 = 14, needs 12 (THAC0 15 with bonuses, target AC 3) -> HIT` | An attack roll. The THAC0 already includes bonuses such as STR; the AC is the target's real AC, with armour and DEX. A natural 20 always hits and a natural 1 always misses. |
| `  X hits Y for 14: 1d8 = [6] + 8 STR 20` | The damage of that hit: the dice, then the STR bonus the game adds for melee attacks. Damage is at least 1. |
| `X DEX check: d20 = 9, needs 16 or less (DEX 16) -> success` | An ability check. A natural 20 always fails. |
| `Percentile check: d100 = 35, needs 40 or less -> success` | A percentage roll. What it's for isn't known yet. |

**Show unlabelled rolls** also lists everything else the game randomises
(creatures wandering, animations and so on), as raw numbers with where in the
game's code they came from. It's noisy, but useful for finding more rolls worth
labelling.

Tested in play: the attack and damage lines match the HP the game takes off,
for both the party and the monsters.

### How the dice log works

Every roll in the game goes through one function, Borland C++'s `rand()`.

1. `dos\DSCLOG.EXE` is a tiny DOS program (8 KB of code and buffer; source in
   `dos\dsclog.asm`). The launcher loads it into upper memory before the game
   starts, so the game loses no memory. It contains a replacement `rand()`
   that returns exactly the numbers the original would, and also records each
   call, what code called it, and that code's arguments (dice count and
   sides, THAC0, AC...) in a small ring buffer.
2. When the game is running, the companion replaces the first 5 bytes of the
   game's `rand()` in memory with a jump to the replacement, and reads the
   ring buffer every 50 ms. Closing the companion puts the 5 bytes back.
3. To keep bursts of unimportant randomness from crowding out the rolls that
   matter, the helper only records calls from code it knows how to label,
   unless **Show unlabelled rolls** is ticked.

Because the replacement produces identical numbers, the game plays exactly as
it would without it.

Limitations:
- Only the GOG release has been checked. Another version of `DSUN.EXE` may
  keep things at different addresses. The dice log then says it can't find
  `rand()` rather than showing wrong numbers.
- DOSBox must use its normal CPU core for the game, which is what GOG's
  `core=auto` setting does for this game. With `core=dynamic` the patch might
  not take effect.
- Rolls made outside combat and ability checks (for example treasure or
  random encounters) show up only with **Show unlabelled rolls**, as raw
  numbers.

## Using the viewer

For Shattered Lands the party is found automatically. The steps below are for
mapping new fields, or for other layouts:

1. Type a party member's name under **Locate by name** and press **Search**.
2. Select the hit that is the character's record and press **Assign**.
   In the hit list, the record shows its name followed by dots, since binary
   data follows the name. A copy in a text buffer is followed by more text.
   Slots 2–4 follow automatically if the party's records sit next to each other
   in memory, as they do in save files. Otherwise assign each slot by name.
3. The **character sheet** (XP, classes, levels, saves) is found automatically:
   it carries the same ability scores and entity ID as the creature record.
4. **Save layout** stores the addresses. They may change when you load a save
   or restart the game. If a slot starts showing garbage, locate it again.

The **Record bytes** panel shows the raw record. Bytes that change light up
orange, and clicking a byte decodes it as u8/s8/u16/s16/u32. Use it to map
fields that aren't known yet. Watch a byte change as you take damage, spend
PSP, or equip armour, then add it to `layouts/shattered_lands.json` and press
**Reload layout**.

### Command-line mapping tools

```
python -m dscompanion find-text Daaki               # hex dump around each hit
python -m dscompanion dump 0x1a2c 128               # hex dump an address
python -m dscompanion search u8 23 --near 0x1a2c    # Cheat-Engine-style value search
python -m dscompanion next 17                       # ...narrow after the value changes
python -m dscompanion next decreased                # also: changed, unchanged, increased
```

## What is known

A save file (`SAVEnn.SAV`) is an SSI **GFF** archive. Two of its chunks hold
the party:

- **`SAVE` chunk 5, creature table.** 58-byte records (`0x3a`) for everyone in
  the current region, party first.
- **`SAVE` chunk 6, character sheets.** 71-byte records (`0x47`).

The game keeps the same records in memory, with the party's sheets one after
another. Old copies of a record can linger elsewhere in memory, so the viewer
prefers the sheet at the party's stride position. Offsets are relative to the
start of each record. The evidence comes from five save files covering three
parties, plus the in-game View Character screens.

| Record | Offset | Type | Field | Evidence |
|---|---|---|---|---|
| creature | `+0x00` | s16 | Current HP | ≤ max HP everywhere; wounded characters lower |
| creature | `+0x02` | s16 | Current PSP | ≤ max PSP everywhere |
| creature | `+0x06` | u16 | Entity ID (`0x80nn` for the party) | same value in the sheet at `+0x10` |
| creature | `+0x1a` | s8 | Base AC, before armour and DEX | 10 for humanoids, 5 for the thri-kreen; the AC the game shows is worked out from this |
| creature | `+0x1b` | u8 | Movement | 12, 15 for the thri-kreen |
| creature | `+0x1f` | u8 | THAC0 | matches the AD&D warrior table at levels 3, 4, 7 and 8 |
| creature | `+0x22` | u8 ×6 | STR DEX CON INT WIS CHA | same as the sheet |
| creature | `+0x28` | str 18 | Name | |
| sheet | `+0x00` | u32 | XP | matches the game |
| sheet | `+0x04` | u32 | Unknown; usually equals XP | a recruited NPC kept the previous occupant's value |
| sheet | `+0x08` | s16 | Max HP | |
| sheet | `+0x0a` | s16 | HP before CON bonus (probably) | max − this = CON bonus × level for single-class characters |
| sheet | `+0x0c` | s16 | Max PSP | |
| sheet | `+0x10` | u16 | Entity ID | links the sheet to its creature record |
| sheet | `+0x18` | u8 | Race: 1 Human, 3 Elf, 4 Half-elf, 5 Half-giant, 8 Thri-kreen | ability modifiers fit; 2, 6, 7 are unseen |
| sheet | `+0x19` | u8 | Gender: 1 male, 2 female | |
| sheet | `+0x1a` | u8 | Alignment: 1 LG, 2 LN, 3 LE, 4 NG, 5 TN, 6 NE, 7 CG, 8 CN, 9 CE | 1, 5, 7 confirmed in game |
| sheet | `+0x1b` | u8 ×6 | STR DEX CON INT WIS CHA | |
| sheet | `+0x21` | u8 ×3 | Class: 1–4 Cleric, 5–8 Druid, 9 Fighter, 10 Gladiator, 11 Preserver, 12 Psionicist, 13–16 Ranger, 17 Thief (0 = none) | 2, 7, 8, 9, 11, 12, 13, 14, 17 confirmed in game; the rest follow the pattern (four each, probably one per element) |
| sheet | `+0x24` | u8 ×3 | Level in each class | |
| sheet | `+0x37` | u8 ×5 | Saves: para/poison, rod/staff, petrify, breath, spell | match the AD&D warrior table exactly |

In memory, the game reaches both tables through far pointers in its data
segment: `DS:0x1665` points to the creature table and `DS:0x1661` to the
sheets (a creature's sheet number is its word at `+0x04`). The data segment
starts with Borland's copyright string at `DS:0x0004`, which is how the viewer
finds the party by itself (`dscompanion/game.py`).

Also seen: per-region `RGnn` chunks hold a combined creature record, sheet and
inventory for each character. Region *nn* uses `SAVE` chunks *nn*×60+1 and up
for its own copy of the region state.

## Practising without the game

`tests/make_fake_party.py` writes `FAKEPTY.COM`, a tiny DOS program holding two
made-up characters in the same record shapes as the game. The first character
loses 1 HP every second. Run it in DOSBox and try the viewer (search for
`SADIRA`).

```
python tests/make_fake_party.py
dosbox FAKEPTY.COM
```

![The viewer on the practice program](docs/viewer.png)

## How it works

DOSBox keeps the emulated PC's RAM in one block of its own process memory. The
tool finds that block by looking for the BIOS date string DOSBox writes at
guest address `0xFFFF5` ("01/01/92"), and checks it against the interrupt
table at guest address 0. After that, reading the game's memory is a plain
`ReadProcessMemory` at `block + guest address`. Dark Sun runs under the DOS/4GW
extender, whose flat 32-bit pointers are these same guest addresses. If
detection fails on an unusual DOSBox build, you can pass the block's host
address with `--host-base`.

## Development

```
python -m unittest discover -s tests
```
