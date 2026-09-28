# Dark Sun Companion: party viewer

A companion tool for **Dark Sun: Shattered Lands** running in DOSBox, in the
spirit of the Gold Box Companion. It reads the game's memory from outside
DOSBox, so it never modifies the game, the emulator, or save files.

This first version is the **party viewer**, plus the tools needed to map the
character record. Nobody has published the in-memory character layout, so the
bundled layout (`layouts/shattered_lands.json`) starts with every field set to
"not discovered yet" (`?`). You fill it in using the workflow below, and the
viewer shows each field as soon as you map it.

![Viewer running against the fake-party test program](docs/viewer.png)

*(The screenshot uses the made-up test program described below, not the real
game. Its HP counter has run past zero and wrapped around, which is why slot 1
shows HP above max.)*

## Requirements

- **Windows** with DOSBox (plain DOSBox 0.74, DOSBox Staging, or the DOSBox
  bundled with the GOG/Steam release).
- **64-bit Python 3.8+** from python.org. It includes tkinter and needs no extra
  packages. Use 64-bit Python because 64-bit DOSBox can't be read from 32-bit
  Python.
- Linux works too if you can read other processes' memory (root, or
  `kernel.yama.ptrace_scope=0`).

## Running it

From this folder, with the game running in DOSBox:

```
python -m dscompanion processes        # checks that DOSBox and its RAM are found
python -m dscompanion view             # opens the party viewer
```

If more than one DOSBox is running, add `--pid <number>` (from `processes`).

## Mapping the character record

Addresses below are **guest addresses**: positions in the emulated PC's RAM.
Dark Sun runs under the DOS/4GW extender, so these are the same numbers the
game uses for its own pointers.

### 1. Find a character's record by name

In the viewer, type a party member's name under **Locate by name** and press
**Search**. The name usually appears several times, in text buffers and UI
strings as well as in the character record. To tell the hits apart:

- The record copy is surrounded by small numbers (ability scores 3–25, HP, level).
- A text-buffer copy is surrounded by other text.

Select the likely hit, choose slot 1, and press **Assign**. The **Record bytes**
panel now shows that area of memory, with offsets relative to the record
(`+0000` is where the name starts).

The same search from the command line:

```
python -m dscompanion find-text Sadira
```

### 2. Watch bytes change

Keep the viewer open next to the game and make one thing change: take damage,
spend psionic points, level up, or equip armour to change AC. Bytes that change
**light up orange** for a few seconds. Click a byte to see it decoded as
u8/s8/u16/s16/u32. That shows you whether it's a one-byte or two-byte value.

### 3. Or narrow down a value (Cheat Engine style)

When you know a number from the game screen (say HP is 23), search for it near
the name hit, change it in the game, then narrow:

```
python -m dscompanion search u8 23 --near 0x1a2c   # only within 4 KB of the name
# ... take damage in the game: HP is now 17 ...
python -m dscompanion next 17
python -m dscompanion next decreased               # also: changed, unchanged, increased
```

Once one address is left, its offset is `address - record base`. The search
state is kept in `.dscompanion-search.json` in the current folder.

### 4. Record it in the layout

Edit `layouts/shattered_lands.json` and fill in the offset and type:

```json
{"label": "HP", "offset": "0x18", "type": "s16"}
```

Press **Reload layout** in the viewer to see it. Raw ids can be given names:

```json
{"label": "Race", "offset": "0x30", "type": "u8", "values": {"0": "Human", "1": "Dwarf"}}
```

Types: `u8 s8 u16 s16 u32 s32` (little-endian) and `str` (with a `length`).
Offsets can be negative if the name isn't at the start of the record.

### 5. The other party members

If the four records sit next to each other in memory, assign slot 2 by name
too. The difference between the slot 1 and slot 2 addresses is the **stride**.
Enter it and press **Apply**, and slots 3–4 fill in automatically. Otherwise,
assign each slot by name. **Save layout** writes the slot addresses to the file.

Records may move when you load a save or restart the game. If a slot starts
showing garbage, locate it by name again.

## Practising without the game

`tests/make_fake_party.py` writes `FAKEPTY.COM`, a tiny DOS program holding two
made-up character records. The first character loses 1 HP every second. Run it
in DOSBox and try the steps above (search for `SADIRA`). Its record layout is
listed in the script, so you can check your results.

```
python tests/make_fake_party.py
dosbox FAKEPTY.COM
```

## Tips for the real game

- Save files probably hold the same character data as memory. Comparing a
  save's bytes with the in-memory record can help confirm fields.
- Some stats are likely stored twice: a base value and a current value with
  modifiers applied (e.g. STR from a potion, AC from armour). Map both if they
  differ.
- Wake of the Ravager uses the same engine, so its record layout is probably
  similar. Copy the layout file and adjust it.

## How it works

DOSBox keeps the emulated PC's RAM in one block of its own process memory. The
tool finds that block by looking for the BIOS date string DOSBox writes at
guest address `0xFFFF5` ("01/01/92"), and checks it against the interrupt
table at guest address 0. After that, reading the game's memory is a plain
`ReadProcessMemory` at `block + guest address`. If detection fails on an
unusual DOSBox build, you can pass the block's host address with
`--host-base`.

## Development

```
python -m unittest discover -s tests
```
