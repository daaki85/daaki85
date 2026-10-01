# Templar's Ledger: a companion and mod for Dark Sun: Shattered Lands

Templar's Ledger runs next to **Dark Sun: Shattered Lands** (the GOG release, in
DOSBox) and shows what the game keeps to itself: every roll it makes, what each
roll was compared against, and where every bonus comes from. It also adds to the
game itself, in the game's own lettering and windows:

- **The rolls behind the scenes:** attacks, damage, saving throws, magic
  resistance, initiative, thief skills, character creation and level-up HP, with
  each bonus named.
- **A party viewer:** THAC0 with each weapon, saves as they stand now, AC and
  what makes it up, spell slots, thief skills, equipment and active effects.
- **In the game:**
  - THAC0, saves, thief skills and DEX adjustments on the inventory screen;
  - spell slots on the USE screen;
  - each turn's rolls in a pop-up during fights;
  - what hurts a monster in the Look box.
- **Dialogue and spells tabs:** a scrollable record of every conversation, and
  what each spell and psionic power really does, from the game's own records.
- **Optional AD&D rule changes**, all on by default and each one switchable:
  - helms give AC;
  - boots give an extra move;
  - two-weapon penalties;
  - spells saved against with the spell save;
  - DEX on saves against fire, cold and electricity instead of a doubled d20;
  - a new spell, Cat's Grace;
  - thieves hiding in shadows and moving silently to backstab.
- **New items and thief play:** a Ring of Protection +1 to find in the arena;
  gear for Kurzak, Legcrusher and Pehtucl in the slave pens;
  Thieves' Tools for every thief; picking anyone's pockets.
- **A mini-quest:** the cooked vulture, at last good for something (Dinos
  cooks it for the party).

The game folder and your saves are never modified. For the dice log, the
launcher runs a patched copy of the game that it keeps in its own folder.

**Everything else is in [`darksun-companion/README.md`](darksun-companion/README.md):**
- requirements;
- how to start it (one double-click on Windows);
- every log line explained;
- how it works.

## Getting started

1. Download this repository (**Code → Download ZIP**) and unzip it anywhere.
2. In the `darksun-companion` folder, double-click **`Start Game with Dice Log.bat`**.
   The first time, it offers to install 64-bit Python if you don't have it.
3. The game and Templar's Ledger start together.

## Changelog

### Unreleased (in review)

**Added**
- **Gear for the slave pens' bosses** (with the Ledger running, given once a
  game):
  - Kurzak: a metal Short Sword (1d6, a new item type; a thief can lift it)
    and a leather Helm;
  - Legcrusher: Leather Chest Armor +1;
  - Pehtucl: a Cloak of Protection +1 (a new item type: +1 AC and +1 on saves,
    as the ring) and a Ring of Protection +1 (a thief can lift it).

**Changed**
- **The inventory screen shows hide in shadows** in hear noise's place (which
  one script check uses); the Ledger's own screens show both.
- **Pick pockets lifts a short sword** too, though it weighs more than other
  small things.

### Pull request #7 ([merged 2026-10-01](https://github.com/daaki85/darksun-companion-mod/pull/7))

**Added**
- **Rule change: AD&D's two-weapon penalties.** A non-ranger with a melee weapon
  in each hand attacks at −2 with the main hand and −4 with the off hand, offset
  by the DEX reaction adjustment.
  - No penalty for one weapon, a two-handed weapon, a weapon and shield, or a
    ranger.
- **Rule change: the spell save.** Spells are saved against with the spell save,
  not petrification/polymorph.
- **Rule change: DEX instead of a doubled d20.** On saves against fire, cold and
  electricity, the DEX defensive adjustment counts instead of a doubled d20. The
  game's own dormant AD&D code does the work.
- **Cat's Grace**, a new 2nd-level wizard spell in Flaming Sphere's place.
  - +1d6 DEX, at most 24, working exactly as Strength does for STR.
  - Untick the rule and Flaming Sphere is back.
- **REAC and DEF on the inventory screen.** REAC (the DEX reaction adjustment)
  sits beside SP; DEF (the defensive adjustment) sits on the AC line.
- **Rule change: hiding in shadows to backstab.** A thief whose turn comes with
  no enemy beside them rolls hide in shadows (half the chance in daylight),
  then move silently. If both succeed, their next attack that turn is from
  behind, and a backstab with a weapon that can.
  - Daylight goes by the map: outdoors, or on maps with buildings, by the
    floor under the thief.
  - The game itself never rolls hide in shadows.
- **The cooked vulture quest.** Take the cooked vulture to Dinos in the slave
  pens: he cooks it for the party, who eat with him. Each member gets 100 XP
  and a full rest (HP, PSP, spell slots), and the vulture is used up.
- **32 new entries in the game's item name table**, for the Ledger's own items.
  The Ring of Protection and Thieves' Tools no longer borrow the game's entries:
  the game's "Rest icon" label is back.

**Changed**
- **Turn pop-ups in the game are off by default**, and have three levels: at the
  least (only what came of each attack and spell, no dice), in short, or in
  detail.
- **Spell slots** (on the USE screen and the Characters tab) only show the spell
  levels the character can cast. More levels appear as they level up. The game
  gives WIS bonus slots at levels a character can't use yet, and those are no
  longer listed.

**Fixed**
- Item names numbered past 255 were read wrongly by the Ledger (for example,
  Serpent Boots).

### Pull request #6 ([merged 2026-09-30](https://github.com/daaki85/darksun-companion-mod/pull/6))

**Fixed**
- **Boots gave no extra move.** The rule looked at the wrong equipment slot (the
  feet are slot 13, not 12).

**Changed**
- README screenshots retaken (move silently, boots, Thieves' Tools, Options).

### Pull request #5 ([merged 2026-09-30](https://github.com/daaki85/darksun-companion-mod/pull/5))

**Added**
- A **Give thieving tools now** button on the Options tab.
- **Thieves' Tools** get a name of their own and a leather satchel's picture
  instead of a key's.

**Fixed**
- The arena ring, and the backpack cell the thieving tools went into.
- Only one set of tools per thief.
- Long lines on the Options tab wrap to the window.

### Pull request #4 ([merged 2026-09-30](https://github.com/daaki85/darksun-companion-mod/pull/4))

**Added**
- **Picking pockets:**
  - press P in a conversation, with a thief leading;
  - small things only;
  - a move silently roll decides whether a fumble is noticed;
  - a few coins when there's nothing else to take.
- **Thieving tools:** every thief starts a new game with a set. Pick them up and
  click someone to try their pockets.
- **Ring of Protection +1**, found on the Tied-up Prisoner in the arena.
- Items named for the rule changes ("Helm (AC 1)", "Boots (+1 Move)").
- **Thief skills as they stand:** equipment penalties and effects, in the game
  and in the Ledger.
- **Start the game** from the Ledger's window, and a triple-size game window.

**Fixed**
- Fights restarting or crashing after a pop-up's Continue.
- The arena's opening show.
- The Announcer's name being replaced by one learned mid-fight.

### Pull request #3 ([merged 2026-09-30](https://github.com/daaki85/darksun-companion-mod/pull/3))

**Added**
- **In the game:**
  - THAC0, saves and thief skills on the inventory and View Character screens;
  - spell slots on the USE screen;
  - each turn's rolls in the game's own window, with monsters' turns in a
    pop-up of their own;
  - monsters' defences in the Look box.
- **Spells tab:** what every spell and psionic power does.
- **Launchers:** one for the game alone with the in-game additions, and one for
  the game and the Ledger together. DOSBox runs in a window, with a choice of
  size.
- **Script decoder:** every thief and ability check in the game's scripts.
- **The first rule changes:** helms give AC 1; boots give a move more in a fight.
- **Saving throws** with each modifier named.
- **THAC0** shown with each weapon, fresh on every redraw.
- The Ring +1 (+1 AC and saves).

**Changed**
- No packaged .exe: the .bat files offer to install Python instead.

### Pull request #2 ([merged 2026-09-29](https://github.com/daaki85/darksun-companion-mod/pull/2))

**Added**
- The game's own **portraits and font**, read from your install at run time.
- **A Characters tab** laid out like the game's View Character screen.
  - Each character's equipment by slot.
  - Effects with rounds or charges left.
  - Spell slots.
- **Spell detail in the dice log:**
  - damage formulas, durations, and what a save does;
  - rules for 20 more effects;
  - healing, Magic Missile and Slay Living dice labelled;
  - Dispel Magic per effect.
- **Thief skill rolls**, with what each chance is made of.
- **Psionics:** powers named, PSP spent logged, magic resistance changes.
- **Saves:** the chance to save, and what the save left.
- **Dialogue:** the reply you picked, and named speakers.
- **The log at a glance:** round headers, hit chances, HP left, and a details
  switch.

### Pull request #1 ([merged 2026-09-28](https://github.com/daaki85/darksun-companion-mod/pull/1))

**Added**
- **The party viewer**, reading Shattered Lands' character records live.
- **The dice log:**
  - attack bonuses, weapons, saving throws, spells and buffs;
  - kills and XP, weapon breaks, level-up HP and AC make-up;
  - attacks from behind and backstabs (with the damage multiplier);
  - each round's initiative order and how each score was made up;
  - the two-weapon adjustment, and character creation rolls.
- **A dialogue tab.**
- **Accessibility** (AODA / WCAG 2.0 AA):
  - contrast checked in tests;
  - text size controls;
  - full keyboard access;
  - logs you can save.
- Double-click launchers and a step-by-step Windows guide.
- The name *Templar's Ledger*, and a window in the game's colours.
