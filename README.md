# pokedeck

Playtest Pokémon TCG decks without shuffling. Paste a decklist export and the
tool plays it — 1,000 full games against a 100-deck gauntlet, with real printed
cards, real attacks, prizes and knockouts — then reports the matchup spread.

Card data comes from the [TCGdex](https://tcgdex.dev) database (every Scarlet &
Violet and Mega Evolution set, ~5,000 cards) and ships inside the package, so
nothing calls the network at runtime. No dependencies beyond the standard
library.

Every deck in the gauntlet is **Standard-legal**: current regulation marks only
(H, I and J after the April 2026 rotation), inside the copy limits, one ACE SPEC
at most. `pokedeck check` holds your list to the same bar.

```bash
pip install -e .
pokedeck gauntlet examples/dragapult.txt
```

## The gauntlet

100 opposing decks × 10 games each. Turn order alternates game by game, so every
matchup is scored from both sides of the coin flip.

```
$ pokedeck gauntlet examples/dragapult.txt -n 10 --rows 6
examples/dragapult.txt vs the gauntlet — 100 decks × 10 games (1000 games, champion player)

  record            654-344-2   (65.4% ±2.9%)
  going first        65.4%   (500 games)
  going second       65.4%   (500 games)
  prize margin      +1.41 per game   (4.03 taken, 2.62 given)
  game length       8.9 turns each
  decided by        prizes 76%, bench-out 17%, deck-out 7%
  card text modelled 100.0%

Worst 6 matchups
  win%   matchup                            record    prizes  turns
   10.0%  Dragapult ex (standard)            1-9-0   -3.1    6.1
   10.0%  Archaludon ex (standard)           1-9-0   -2.6    8.0
   20.0%  Terapagos ex (grind)               2-8-0   -2.7    7.2
   ...
```

If your own list is not Standard-legal the report says so and plays it anyway —
the field stays legal, so you are told what you are measuring.

`--decks N` takes an even spread across the field rather than the first N
files, so a short run still meets every archetype.

Both sides are played by the searching player by default, which takes a few
minutes for a thousand games across four cores; `--policy greedy` swaps in the
heuristic player and finishes in about ten seconds when you just want a smoke
test. Flags: `-n` games per opponent, `--decks N` to cut the field down,
`--rows N` for only the worst and best N matchups (the default prints all 100),
`--policy` / `--opponent-policy`, `--workers`, `--seed`, `--turn-limit`,
`--json`.

The field lives in `pokedeck/data/gauntlet/` as 100 readable decklists — 25
archetypes (Dragapult ex, Hydreigon ex, Mega Lucario ex, Mega Dragonite ex,
Cynthia's Garchomp ex, Raging Bolt ex, Miraidon ex, Terapagos ex, Steven's
Metagross ex, …) in four variants each: `standard`, `aggro`, `techy` and
`grind`. The builder picks the newest legal print of every card, derives the
Energy from what the attacker's own attack costs, keeps each list to one ACE
SPEC, and refuses to write a deck that fails the construction or format check.
Rebuild or edit the field with `python tools/build_gauntlet.py`.

## What the battle engine models

Every game is played out properly, by the same player on both sides:

- **Setup** — shuffle, seven cards, mulligans (and the extra draw they give the
  opponent), a Basic to the Active Spot, up to five on the Bench, six prizes.
- **Turns** — draw, Abilities, Trainers (one Supporter, one Stadium, any number
  of Items), evolution on the real timing rule, one Energy attachment, one
  retreat paid in Energy, then an attack. The player going first cannot attack
  on turn one, and cannot play a Supporter on it either — unless the card says
  it may, the way Carmine does.
- **Attacks** — printed cost checked by Energy type, printed damage, the riders
  the text compiler understands (damage per prize taken, per Energy attached,
  "discard as much Energy as you like", bench damage and damage counters,
  snipes, coin flips, self-damage, Energy discard, "can't attack next turn",
  switching), then Weakness (×2) and Resistance.
- **Special Conditions** — Asleep, Paralyzed, Confused, Burned and Poisoned,
  resolved at the Pokémon Checkup between turns, and cleared by switching.
- **Knockouts and winning** — prizes taken by rule-box value (ex and V take two,
  Mega Evolution ex and VMAX three), promotion from the Bench, and all three win
  conditions: six prizes, no Pokémon left, or an empty deck on the draw step.
- **Damage modifiers, in the printed order** — Tools and Abilities that add
  damage (Maximum Belt against an ex, a team buff) land before Weakness and
  Resistance; the defender's own reductions come last. Abilities that rewrite
  Weakness, Tools that add HP or take Energy off a retreat, and Abilities that
  make a named attack cheaper all apply.
- **Lockdowns** — Ability lock (neither side may use Abilities), Item lock for
  a turn, and an attack locked out of being used again next turn.
- **Damage counters** — placed by Abilities such as Dusclops and Dusknoir,
  which knock themselves out as the price, moved around by Munkidori, and
  spread by attacks.
- **Energy that counts as more than one thing** — a rainbow Energy is one unit
  that can pay any symbol (and only on a Basic, for Prism; only on a Stage 2,
  and for two, for Neo Upper). Typed costs are paid with the least flexible
  Energy that fits, so the rainbow is kept for what needs it.
- **Stadiums** — the once-a-turn ability each player may use (Fossil Quarry,
  Artazon, Lumiose City) and the ones that prevent damage, such as
  Neutralization Zone blanking attacks from the opponent's ex and V.
- **Fossils** — Trainers played as 60 HP Basics that cannot retreat, searchable
  by the cards that name them and evolvable by the Pokémon above them.
- **Borrowed attacks** — a Pokémon whose Ability lets it use the attacks of
  your Benched Pokémon, paid for with its own Energy.

## The player

Two players ship with the tool, and `--policy` picks between them.

**`champion` (default)** searches its turn instead of following a checklist.
For every action it could take — use an Ability, play this Item, evolve that
Pokémon, attach Energy here rather than there, retreat, attack with this — it
clones the game, plays the action, lets the opponent answer and plays its own
follow-up, then scores the position that comes out. The action with the best
average score is the one it actually takes, and then it searches again from
the new position.

Each action is judged on its own, without the rest of the turn played out
behind it. That distinction matters more than it sounds: with a greedy
continuation filling in the gaps, every option scored about the same, and the
search emptied its hand every turn for marginal value — searching a deck away
to fetch a Pokémon it did not need. Judged alone, a card it has no use for
stays a card it still has.

Three things make that search honest and affordable:

- **Determinization.** Every clone reshuffles what the player cannot see: its
  own deck and prizes, and the opponent's hand, deck and prizes. The search
  plans against the game it can observe rather than reading the opponent's hand
  off the table.
- **Common random numbers.** Every candidate for one decision is played out
  against the *same* shuffles, so a line wins on merit rather than on being
  handed the better deal.
- **A cheap first pass.** One rollout each narrows the options to five
  finalists; the full rollouts are spent on those.

The position score is the one a player would recognise: prizes taken first,
then whether the board can take a knockout next turn and survive the swing
back, then development — Energy in play, attackers that are paid for, damage
already on the board, bench size, how many prizes the bench is quietly owing
the opponent, and how close either deck is to running out of cards.

Measured against the heuristic player — same decks, same seeds, only the player
different, 60 games each:

| matchup | searching player wins |
| --- | --- |
| Raging Bolt mirror | 80% |
| Dragapult vs Raging Bolt | 77% |
| Dragapult mirror | 60% |

The Raging Bolt mirror is a deck-out race, and it used to be the hole in this
player — 50% before it stopped spending cards it did not need. The position
score still carries a deck-out term, because a one-turn search cannot feel a
race it cannot see the end of.

**`greedy`** is the heuristic player: bench early, evolve on curve, stack Energy
on the attacker closest to its real attack, draw only when the hand is thin
(decking yourself is a loss), gust with Boss's Orders when the gust scores a
knockout, retreat a dead Active, and attack for the knockout when one is there.
It is a decent club player and it is fast, which is what makes it useful as the
rollout player inside the search.

**Neither is a world champion.** The search is one turn deep with a heuristic
continuation: it does not plan a prize map three turns out, does not hold a
card back for a read on the opponent's deck, does not know that a particular
matchup is won by a line no evaluation function would score highly, and only
understands the card text the compiler could read. It plays a clean, tactical
game and it does not misplay the obvious things — that is the honest ceiling
here.

Across the hundred field decks, **100% of distinct cards are fully modelled** —
every line of their printed text turned into rules, checked by
`tools/audit_cards.py`, which puts each card into a controlled game, uses it,
and reports anything that changed nothing. Pool-wide, 61% of Standard-legal
cards read end to end; the rest is reported, never guessed at.

**Not modelled:** the Lost Zone, attack choices that depend on reading the
opponent, Tera Pokémon (TCGdex carries no Tera marking, so a shield printed
against them matches nothing), and any text the compiler could not parse.
Nothing is silently invented: an unreadable rider just does not fire, and the
coverage line in every report tells you how much of your deck was taken
literally.

```
  card text modelled  95.0%
  partly modelled:      Jirachi
  not in the card pool: Some Promo Card
```

Cards outside the bundled pool (an older-format card, a brand new print) become
blanks — a 60 HP Pokémon with no attacks. Fix that by naming them in an
overrides file (see *Teaching it new cards*) or refreshing the pool.

## The other commands

### `check` — is the deck legal, and what shape is it?

```
$ pokedeck check examples/dragapult.txt
Composition
  pokemon              16
  basics                8
  draw supporters      10
  ball/search items     9
  ...
Opening-hand maths (no draw support)
  mulligan rate (no Basic in 7)       34.6%
  draw supporter in opening 7         74.1%

Construction: 60 cards, no card over its copy limit

Format (standard)
  legal — every card is in the current regulation marks
```

Two separate bars, both of which exit non-zero when broken:

- **Construction** — 60 cards, four copies per card (basic Energy exempt), at
  least one Pokémon.
- **Format** — every card in a legal regulation mark, and at most one ACE SPEC
  card. Standard is H, I and J: the April 2026 rotation dropped G, and basic
  Energy has no mark and never rotates. `--format any` checks construction only
  and skips rotation, for testing an older list (`examples/rotated-charizard.txt`
  is one, kept to show the failure).

```
$ pokedeck check examples/rotated-charizard.txt
Format (standard)
  [error] Charizard ex (sv03-125) is regulation mark G — not legal in standard
  [error] Professor's Research (sv01-189) is regulation mark G — not legal in standard
  ...
```

A card the pool has never seen is reported as a warning, not an error — we
cannot verify what we cannot look up.

### `sim` — how often does the deck set up?

A fast goldfish simulation of the opening turns, with no opponent:

```
$ pokedeck sim examples/dragapult.txt -n 5000 --turns 3 \
    --goal "play:Dragapult ex" --goal "Rare Candy + Dreepy"
```

- `--goal "Dragapult ex"` — the card is in hand or in play.
- `--goal "play:Dragapult ex"` — the card is on the board.
- `--goal "Rare Candy + Dreepy"` — every piece at once, scored the moment they
  line up.

### `odds` — exact hypergeometric numbers, no simulation

```
$ pokedeck odds examples/dragapult.txt --card "Rare Candy" --turns 2
  card                            copies      T0      T1      T2   prized
  Rare Candy                         4     39.9%   44.5%   48.8%    35.1%
```

### `hand` and `compare`

`pokedeck hand deck.txt -n 5` deals sample opening hands;
`pokedeck compare a.txt b.txt --goal "..."` lines two lists up on the same goals.

## The desktop app

The same tool ships as a single executable with nothing to install — no Python,
no `pip`. `packaging/pokedeck.spec` builds it with PyInstaller, and
`.github/workflows/build-exe.yml` builds `pokedeck.exe` on Windows (plus Linux
and macOS binaries) on every tag, runs the test suite and a smoke test against
the real binary, and attaches the results to the release.

Build one yourself on the platform you want it for:

```bash
pip install pyinstaller
pyinstaller packaging/pokedeck.spec      # dist/pokedeck.exe on Windows
```

Double-clicking the executable opens a menu — point it at a decklist and pick
what to run:

```
  pokedeck — Pokemon TCG deck tester
  ------------------------------------------------
  Plays your deck against 100 Standard-legal decks.

  Decklist: C:\Users\me\Desktop\my-deck.txt

  Loaded my-deck.txt — 60 cards

  1) Check the deck (legality, composition, opening-hand odds)
  2) Play the gauntlet — 100 decks, 10 games each
  3) Quick gauntlet — 20 decks, 4 games each
  4) Setup odds (goldfish simulation)
  5) Deal sample opening hands
  6) Load a different deck
  7) Quit
```

Dragging a decklist onto the executable loads it straight away, and every CLI
command still works from a terminal: `pokedeck.exe gauntlet my-deck.txt -n 10`.

## Decklist format

The PTCG Live / PTCGO export format, with or without set codes. Set codes pin
the exact print (and therefore the exact card), which matters when a Pokémon has
been printed more than once. Energy can be written either way — `Basic {F}
Energy`, `Fighting Energy` and `Basic Fighting Energy` are the same card — and
a print the pool has never seen is swapped for another printing of the same
card, which `check` tells you about rather than doing quietly:

```
Pokémon: 16
4 Dreepy ASH 158
3 Dragapult ex ASH 160

Trainer: 34
4 Carmine TWM 145
...

Energy: 10
5 Basic Fire Energy
```

## Teaching it new cards

`pokedeck/data/cards.json` holds hand-written scripts that override the compiled
text for cards the compiler reads poorly. Supply your own with `--cards`:

```json
{"cards": [
  {"name": "Mystery Ball", "category": "trainer", "subtype": "item",
   "effects": [{"op": "discard_from_hand", "n": 1},
               {"op": "search", "filter": "basic_pokemon", "n": 1, "dest": "bench"}]},
  {"name": "Glitchmon ex", "category": "pokemon", "stage": "basic", "hp": 220,
   "types": ["Fire"], "weakness": "Water", "retreat": 2, "prize_value": 2,
   "attacks": [{"name": "Blast", "cost": ["Fire", "Fire"], "damage": 180}]}
]}
```

```bash
pokedeck gauntlet deck.txt --cards my-cards.json
```

Effect ops: `draw`, `draw_to`, `draw_prizes`, `discard_hand`,
`shuffle_hand_into_deck`, `discard_from_hand`, `search` (with `filter` and
`dest`), `recover`, `attach_energy`, `bonus_per`, `scale`,
`discard_energy_scale`, `bench_damage`, `bench_counters`, `snipe`, `snipe_multi`,
`status`, `heal_self`, `self_damage`, `shield`, `switch_self`,
`switch_opponent`, `no_attack_next_turn`, `ko_target`, `clear_conditions`.
Search filters: `any`, `pokemon`, `basic_pokemon`, `item`, `tool`, `supporter`,
`stadium`, `energy`, `basic_energy`. `ability_trigger` is `turn`, `on_play` or
`on_evolve`.

## Refreshing the card pool

```bash
python tools/fetch_pool.py                 # every SV and ME set
python tools/fetch_pool.py --sets sv10 me05
```

This rewrites `pokedeck/data/cardpool.json.gz` (about 270 KiB for ~5,000 cards).

## Library use

```python
from pokedeck import parse_file, resolve, run_gauntlet, load_field
from pokedeck.legality import check as legality_check

deck = parse_file("deck.txt")
resolution = resolve(deck)
print(legality_check(deck, resolution))          # [] when the list is Standard-legal
report = run_gauntlet(deck, resolution, load_field(), games_per_deck=10)
print(report.win_rate, report.sorted_matchups()[0].opponent)
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```
