# Dark Sun Companion

A companion tool for **Dark Sun: Shattered Lands** (the GOG release) running in
DOSBox, in the spirit of the Gold Box Companion. It has three parts:

- **Party viewer:** every party member's stats, live, including numbers the
  game doesn't show (THAC0, saving throws, attacks per round, the AC the game
  uses in a fight and what it's made of, class ids).
- **Dice log:** the rolls the game makes behind the scenes, with what they were
  compared against and where every bonus comes from. For example:

  ```
  Dag attacks Mountain Stalker with Long Sword +1 (1d8+1): d20 = 18, hits AC -10, target AC 4 -> HIT
      THAC0 16, +1 Blessed, +6 STR, +1 weapon = 8
    Dag hits Mountain Stalker for 20: 1d8 = [7] +1 weapon +12 STR 24
  Fireball damage: 9d6 = [3 + 2 + 3 + 4 + 5 + 4 + 1 + 2 + 2] = 26
  Red Slaad magic resistance 30% vs Fireball: d100 = 71 -> not resisted
  Red Slaad saves vs Fireball from Daaki (petrification/polymorph): d20 = 6, doubled for this spell = 12, needs 11 -> saved
  Jellybelly gives Blessed to Daaki: +1 to hit, +1 on saves
  Slig is killed (270 XP)
  XP: Gerakis +67, K'ratchek +22, Cermak +67, Cilla +22 (for Slig 270)
  ```
- **Dialogue:** what characters say, and the replies you're offered, kept in a
  tab you can scroll back through.

Nothing in the game folder or your save files is changed. The viewer only reads
memory. For the dice log, the launcher runs a patched copy of the game that it
keeps in the companion's own folder (see
[How the dice log works](#how-the-dice-log-works)).

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
helper loaded, and opens the companion next to it. Your saves are the same ones
the game normally uses. The first time, it looks for
the game in the usual GOG folders; if it can't find it, it asks you where the
game is installed and remembers the answer.

Load your game. The party's stats fill in by themselves, and rolls appear in
the **Dice log** tab as they happen.

If you start the game the normal way instead, **`Start Companion.bat`** still
shows the party, but the dice log will say the game was started without it.

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

| Line | Meaning |
|---|---|
| `X attacks Y with Long Sword +1 (1d8+1): d20 = 14, hits AC 1, target AC 3 -> HIT` | An attack roll, the weapon and its damage dice. `X attacks Y from behind ...` and `X attacks Y BACKSTAB ...` mark attacks from behind and backstabs (see below). "Hits AC" is the lowest AC this roll hits (THAC0 − d20); the target AC is the one the game used, with armour, DEX and spells. A natural 20 always hits and a natural 1 always misses. |
| `    THAC0 16, +1 Blessed, +6 STR, +1 weapon = 8` | Where the attacker's THAC0 for this attack comes from: STR (melee) or DEX (missiles), spells (Bless, Prayer, Slow, Graft Weapon, the target's Blur), attacking from behind, the weapon's plus, the penalty for non-metal weapons (wooden −3, bone −1, stone and obsidian −2), and the difficulty setting for monsters. |
| `  X hits Y for 14: 1d8 = [6] +8 STR 20` | The damage of that hit: the dice, the weapon's bonus, and the STR bonus the game adds for melee. Damage is at least 1. |
| `  X hits Y for 51: (1d8 = [5] +12 STR 24) x3 backstab` | A backstab (see below) multiplies the whole damage, STR bonus included. |
| `Fireball damage: 9d6 = [...] = 26` | A spell's damage roll, rolled for each target before its saving throw. |
| `Y magic resistance 30% vs Fireball: d100 = 71 -> not resisted` | The magic resistance roll (only shown for targets that have some). |
| `Y saves vs Fireball from X (petrification/polymorph): d20 = 6, doubled for this spell = 12 +1 modifiers (incl. Blessed) = 13, needs 11 -> saved` | A saving throw: which of the target's five saves it uses, the d20, the game's modifiers, and the number it had to reach. The game doubles the d20 for some spells (Burning Hands, Fireball, Cone of Cold, Flame Strike, Wall of Fire...). A natural 1 always fails and a natural 20 always saves. |
| `X gives Blessed to Y, Z: +1 to hit, +1 on saves` / `Blessed ends on Y` | A spell or psionic effect starting or ending, with what it does in the game's code where that is known (to-hit, AC, saving throws). |
| `X DEX check: d20 = 9, needs 16 or less (DEX 16) -> success` | An ability check. A natural 20 always fails. |
| `Percentile check: d100 = 35, needs 40 or less -> success` | A percentage roll. What it's for isn't known yet. |
| `    X's Bone Long Sword nearly broke: 0 on 0-7, then 12 on 0-19 (needed 0)` / `... BREAKS` | The weapon check the game makes after an attack sequence whose last attack hit. Only non-magical wood, bone, stone and obsidian weapons can break (and not every kind: clubs and quarterstaffs can't): they break when a 0-7 roll and then a 0-19 roll both come up 0, 1 chance in 160. The line only appears when the first roll comes up 0. |
| `Initiative, highest acts first:` / `    Cilla 25 = 20 + 1 (0-9 roll) +4 DEX, tie broken by 6 (0-199 roll)` | The order for the round, with each score's make-up (see below). |
| `Message: Long Sword is broken !` | The game's own message boxes: broken or corroded weapons and armour, level-ups, "NO PATH FROM HERE" and so on. |
| `    X's special effect on Y: d10 = 1, works on a 1 -> it works` | The 1-in-10 extra effect some creatures' hits have (the thri-kreen bite, for one). |
| `Slig is killed (270 XP)` | A creature dying, with the XP it's worth (from its character sheet). |
| `XP: Gerakis +67, K'ratchek +22, ... (for Slig 270)` | Experience the party got, and for which kills. The game gives it right after the kill: an equal share to each character, split again between a multi-class character's classes (the sheet counts XP per class, so a three-class thri-kreen shows a third of the share). |
| `Cilla is now a 3rd level Ranger` / `    max HP 15 -> 21 (+6)` | A level gained, and the new maximum HP. |
| `    no hit point roll: that comes only when the highest class level rises (still 3rd)` | A multi-class character's level in one class went up without raising their highest level: the game gives no hit points for it. |
| `Cilla's 3rd Ranger level: hit points d10 = 2, raised to 3 for CON 21` | The hit point roll for a new level: the class's die (d8 clerics and druids, d10 fighters, gladiators and rangers, d4 preservers, d6 psionicists and thieves), never less than 2, 3 or 4 with CON 20, 21-22 or 23+, and doubled for half-giants. After level 9 or 10 there's no roll, just a fixed gain. |
| `Dice: 1d8 = [3] = 3` | Dice the log couldn't tie to anything (for example a spell with no saving throw). |

**Show unlabelled rolls** also lists everything else the game randomises
(creatures wandering, animations and so on), as raw numbers with where in the
game's code they came from. It's noisy, but useful for finding more rolls worth
labelling.

Tested in play: the attack and damage lines match the HP the game takes off,
for both the party and the monsters, and every saving throw of a Fireball is
logged.

The viewer's **Current AC** row is the AC the game last used for each
character in a fight (armour, DEX and spells included), and the rows under it
say what it was made of: armour and shield (and spells that take their place,
such as Spirit Armor and Magical Vestments), DEX (the game's table: −1 at 15
down to −6 at 24; not counted when attacked from behind), and spells and
anything else. They show "-" until the game has worked out that character's AC
in a fight.

Ability scores such as `STR 24 (20 without spells)` show the score now and, in
brackets, the character's own score when a spell (Strength, for one) has
raised it. The character's own score already includes the racial adjustment:
a half-giant's 20 + 4 shows as 24.

### Initiative

From the game's code: at the start of every round each combatant's initiative
is 20 + a roll of 0-9 + a DEX adjustment + Hasted +2, Slowed −2 and Blind −2.
The DEX adjustment has its own table: −6 at DEX 1, −4 at 2, −3 at 3, −2 at 4,
−1 at 5, none for 6-15, +1 at 16, +2 at 17-18, +3 at 19-20, +4 at 21-23 and
+5 at 24-25. The weapon makes no difference (there are no weapon speeds). The
highest score acts first; a second roll, 0-199, decides between equal scores
(the log shows it only for those). Choosing Wait lowers the character's score
to 10 (or by one, if it's 10 or less already) so they act later in the round.

### Attacks from behind and backstabs

From the game's code:

- An attack is **from behind** when the attacker stands in the square directly
  behind the way the target is facing. A creature faces nowhere in particular
  at the start of each round; the first attack on it in the round turns it
  to face that attacker (one of eight directions), and it keeps facing that
  way for the rest of the round. So a second attacker on the far side, later
  in the same round, attacks from behind. (Its own attacks don't turn it.)
  It gets +2 to hit, and the target loses its DEX bonus and its shield.
- A **backstab** is an attack from behind by a thief, in melee, with a weapon
  that isn't too heavy (the game's weight value at most 40; a long sword's
  is 20). It gets another +2 to hit (+4 in all), and on the thief's first
  attack of the round the damage, STR bonus included, is multiplied: x2 at
  thief levels 1-4, x3 at 5-8, x4 at 9-12, x5 from 13.

### The Dialogue tab

Everything the game shows in its dialogue window, one entry per window of
text, with the replies offered numbered underneath (and the list's title,
such as "Answer Yes or No", above them). The game only says which portrait
goes with the text, so speakers show as `Portrait 119` and so on (119 is the
arena announcer); the text itself often names who's speaking. Text shown
without a face (the emblem instead) is `Narration`.

### How the dice log works

Every roll in the game goes through one function, Borland C++'s `rand()`.

1. When you start the game with the dice log, the launcher writes
   `dos\DSUNLOG.EXE`: a copy of the game's `DSUN.EXE` with a few small changes
   (`dscompanion/gamepatch.py`). The start of `rand()`, the end of the saving
   throw, the end of the AC calculation, the start of the routine that fills
   the dialogue window and the start of the message box routine become
   `INT 60h` to `64h`, and the copy looks for its data files in the current
   folder rather than next to itself. DOSBox runs it from the game folder, so
   it uses your saves as usual.
2. `dos\DSCLOG.EXE` (source in `dos\dsclog.asm`) is a tiny DOS program loaded
   into upper memory before the game, so the game loses no memory. It answers
   those interrupts. Its `rand()` returns exactly the numbers the original
   would and also records each call, what code called it, and that code's
   arguments (dice count and sides, THAC0, AC...) in a ring buffer. The others
   record the final saving throw total, the AC the game uses, and the text
   of dialogues and messages (in a second buffer).
3. The companion finds the buffer in DOSBox's memory and reads it every 50 ms.
   It works out what each roll was for from the code that asked for it, and
   reads the rest (names, weapons, spells, effects) from the game's own data.
4. To keep bursts of unimportant randomness from crowding out the rolls that
   matter, the helper only records calls from code it knows how to label,
   unless **Show unlabelled rolls** is ticked.

Because the replacement produces identical numbers, the game plays exactly as
it would without it.

Limitations:
- Only the GOG release (`DSUN.EXE` of 611,408 bytes) is supported. With
  another version the launcher starts the game without the dice log and says
  why.
- Rolls made outside combat (for example treasure or random encounters) show
  up only with **Show unlabelled rolls**, as raw numbers.
- A save-file load from the main menu is recognised, so the spells already
  active in it aren't reported as new. Loading a save of the same party in the
  middle of play isn't, and its effects may be listed as if just cast.
- Dialogue speakers are portrait numbers, not names (see above).
- Weapon breaking was checked against the game's code, and the check's rolls
  were seen in play, but no weapon happened to break during testing; the
  game's own "is broken !" message is logged either way.

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
| sheet | `+0x04` | u32 | For monsters, the XP they're worth; for the party, usually equals XP | matches the XP the party gets for a kill |
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
| sheet | `+0x27` | s8 | Base AC for the AC calculation | read by the game's AC code |
| sheet | `+0x29` | u8 | Magic resistance (%) | read by the game's magic resistance check |
| sheet | `+0x1d` | u8 | CON (among the abilities at `+0x1b`); sets the least a level's hit point roll counts for | read by the game's level-up code |
| sheet | `+0x2a` | u8 | Attacks per round × 2 | read by the game's combat code |
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
`ReadProcessMemory` at `block + guest address`. Dark Sun is a 16-bit real-mode
program, so a `segment:offset` address is simply `segment × 16 + offset` in
guest memory. If detection fails on an unusual DOSBox build, you can pass the
block's host address with `--host-base`.

## Development

```
python -m unittest discover -s tests
```
