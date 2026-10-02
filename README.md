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
  - THAC0, saves, thief skills and DEX adjustments on the inventory screen,
    THAC0 and saves on View Character;
  - spell slots on the USE screen;
  - each turn's rolls in a pop-up during fights, if you tick it (three levels
    of detail);
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
  - thieves hiding in shadows and moving silently to backstab, and rangers
    to attack from behind;
  - thief skills from AD&D's table, with Dark Sun's race and DEX adjustments;
  - half-giants wielding two-handed weapons in one hand;
  - class levels up to 10 (the game stops at 9).
- **New items and thief play:** a Ring of Protection +1 to find in the arena;
  gear for Kurzak, Legcrusher and Pehtucl in the slave pens (a short sword
  and a Cloak of Protection among it), with icons of their own; the rest of
  the bone scale armour, with a Bone Helm, where its chest piece lies; Thieves'
  Tools for every thief;
  picking anyone's pockets; and no more thief skill penalty for what a thief
  holds.
- **A mini-quest:** the cooked vulture, at last good for something (Dinos
  cooks it for the party).
- **What the party wears, on the map:** weapons, shields, bows, armour, helms,
  cloaks, boots and belts on their figures, walking and fighting, changing as
  their gear does.

The game folder is never modified, and your save files only keep what you'd
expect from play: the items the Ledger hands out, the XP it gives. For the dice
log, the launcher runs a patched copy of the game that it keeps in its own
folder.

**Everything else is in [`darksun-companion/README.md`](darksun-companion/README.md):**
- requirements;
- how to start it on Windows;
- every log line explained;
- how it works.

## Getting started

1. Download the latest release from the
   [Releases page](https://github.com/daaki85/darksun-companion-mod/releases)
   (`Templars-Ledger-<version>.zip`) and unzip it anywhere. (Or this repository
   as it stands: **Code → Download ZIP**.)
2. In the `darksun-companion` folder, double-click **`Start Templar's Ledger.bat`**.
   The first time, it offers to install 64-bit Python if you don't have it.
3. On the Ledger's **Options** tab, pick the rule changes and additions you
   want (they're remembered).
4. Press **Start the game** at the top left. The game starts with your options,
   and the Ledger follows it.

(`Start Game with Dice Log.bat` starts the game and the Ledger together in one
double-click, with the options as last set.)

## Changelog

Release **1.0.0** is pull requests #1 to #13. Its notes are in
[`release-notes/v1.0.0.md`](release-notes/v1.0.0.md).

### Pull request #14 (in review)

**Added**
- **What the party wears, on the map:** each character's figure shows their
  weapons and shields (each kind its shape, in its material's colours), bow
  and quiver on the back, armour (their own clothing recoloured toward its
  material), helms as circlets, cloaks (the game's own cloak, fitted to them),
  boots and belts, walking and fighting, and changes as soon as their gear
  does. Walking, a one-handed weapon hangs at the belt; in a fight it is in
  the hand. Two characters of the same race and sex each show their own
  gear. On by default; a switch on the Options tab.

**Changed**
- **Cat's Grace's icon** is a cat's paw print instead of a cat's face.

### Pull request #13 ([merged 2026-10-02](https://github.com/daaki85/darksun-companion-mod/pull/13))

**Added**
- **The Release workflow can be run by hand**, making the version's tag.

### Pull request #12 ([merged 2026-10-02](https://github.com/daaki85/darksun-companion-mod/pull/12))

**Added**
- **Release 1.0.0:** the version, its release notes, and a workflow that
  builds the release zip.

### Pull request #11 ([merged 2026-10-02](https://github.com/daaki85/darksun-companion-mod/pull/11))

**Added**
- **Cat's Grace looks like itself:** its own icon (a lean, fox-like cat's face
  on gold) and its own description in the spell box, instead of Flaming
  Sphere's.

**Fixed**
- **The slave pens' gear given twice** (a second short sword on Kurzak after
  his was lifted, two Leather Chest Armor +1 on Legcrusher) to a game loaded
  after it was given: none of it is given where it is already in the game.
- **Prices:** Leather Chest Armor +1 is worth 3000 (it was 10), the Cloak of
  Protection +1 5000 and the Rings of Protection +1 5000, as magic items;
  ones already in a game are repriced.
- **Dinos takes the vulture as soon as a fight is over** (he wouldn't until the
  party rested): the Ledger now reads the game's own combat flag.
- **Thieves' Tools can't be used in a fight**, only out of one.
- **The dice log and the Dialogue tab keep up with the newest lines** (they
  stopped following them, and lines that came while another tab was open
  were out of view); scrolling up to read back still holds the place.
- **The bone scale set added twice** to a game loaded after it was added: it is
  now added only where none of its pieces is.
- **No more log lines for the Ledger's items** handed out (the slave pens'
  gear, the bone scale set): they're there to be found.
- **The Bone Helm** can only be worn by those who can wear bone scale armour
  (not thieves).

**Changed**
- **Getting started:** open the Ledger first, pick the options, then **Start
  the game** from it.

### Pull request #10 ([merged 2026-10-02](https://github.com/daaki85/darksun-companion-mod/pull/10))

**Fixed**
- **Half-giants' two-handed weapons in one hand:** the rule didn't take
  effect (the helper looked for the character on show in the wrong place).

### Pull request #9 ([merged 2026-10-02](https://github.com/daaki85/darksun-companion-mod/pull/9))

**Added**
- **Rule change: thief skills from AD&D's table.** A skill is AD&D's average
  for the thief level, plus the race's adjustment, plus Dark Sun's DEX
  adjustment (AD&D's table to 19, the Dark Sun rules' to 22). The game added 4
  a level to a base of its own and used a DEX formula, which gave a 3rd-level
  thief move silently and hide in shadows 10 to 20 points too high. Rangers'
  two chances take the same adjustments.
- **The bone scale set:** where the Bone Scale Chest Armor is found, its arm and
  leg pieces (the game's own, never placed) and a new Bone Helm, coloured to
  match, are found with it.
- **Rule change: half-giants wield two-handed weapons in one hand,** with a
  shield or a light weapon in the other (the game's rule against two heavy
  weapons still stands).
- **Names in colour in the dice log:** each party member's in a colour of
  their own, monsters' in red, bold, all at 4.5:1 contrast or more.

**Fixed**
- **A game that stops with an error** leaves its message on screen (DOSBox
  waits for a key instead of closing), and the dice log says how DOSBox
  closed, telling a crash of DOSBox's own apart.
- **Picking a pocket after loading a save:** a try made after the save (the
  thief caught) is forgotten when it's loaded, so that person can be tried
  again.
- **XP taken away and given back between areas** (the game does it as the
  party moves on) is no longer logged as a loss and a gain; a loss that stays
  is logged after a minute.
- **A monster's AC in its Look box** could be an earlier fight's creature's
  (the game reuses creature records): a slig in the first arena fight showed
  the opening fight's Defiler's AC −9. The Ledger now forgets monsters' ACs
  when a new fight begins.

**Changed**
- **The Options tab scrolls** when the window is too small to show it all.
- **Options:** the Ring +1, picking pockets and the thieving tools button sit
  under Rule changes, with the other changes to play.

### Pull request #8 ([merged 2026-10-02](https://github.com/daaki85/darksun-companion-mod/pull/8))

**Added**
- **Rule change: levels up to 10.** Every class can reach 10th level, at
  AD&D's XP (the game stops at 9). The game's own tables and formulas give
  the rest: hit points, THAC0, saves, spell slots (still no higher than 5th
  level), thief skills, a gladiator's armour bonus, a preserver's new spell
  and a psionicist's new power. Thieves roll their 10th hit die (the game
  would give them a psionicist's fixed +2).
- **Gear for the slave pens' bosses** (with the Ledger running, given once a
  game):
  - Kurzak: a metal Short Sword (1d6, a new item type; a thief can lift it)
    and a leather Helm;
  - Legcrusher: Leather Chest Armor +1;
  - Pehtucl: a Cloak of Protection +1 (a new item type: +1 AC and +1 on saves,
    as the ring) and a Ring of Protection +1 (a thief can lift it).
- **Rangers hide in shadows and move silently too** (the stealth rule), with
  AD&D's ranger chances: the full chance outdoors and half indoors, the
  reverse of thieves. Their attack from behind is +2 to hit and ignores the
  target's DEX and shield, but is no backstab. Their two chances show on the
  inventory screen where a thief's MOVE and HIDE go, and on the Characters
  tab.
- **Item icons of their own** for the Short Sword (a shorter blade), Leather
  Chest Armor +1 (fire), the Cloak of Protection +1 (violet) and the two Rings
  of Protection +1 (Pehtucl's violet, the arena's fire), made from the game's
  plain ones. The launcher writes a copy of the game's objects file with them
  in its own folder; the game folder is untouched.

**Changed**
- **Thief skills: no equipment penalty.** The game took 5 to 10 off some
  thief skills for anything in the legs slot, the quiver or either hand
  (whatever it was); it no longer does in games started with the dice log.
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
