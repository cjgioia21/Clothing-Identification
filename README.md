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
$ pokedeck gauntlet examples/dragapult.txt -n 10 --rows 5
examples/dragapult.txt vs the gauntlet — 100 decks × 10 games (1000 games)

  record            680-318-2   (68.0% ±2.9%)
  going first        70.0%   (500 games)
  going second       66.0%   (500 games)
  prize margin      +2.03 per game   (4.20 taken, 2.17 given)
  game length       10.8 turns each
  decided by        prizes 77%, bench-out 14%, deck-out 9%, turn-limit 0%
  card text modelled  96.0%
  partly modelled:      Lucian

Worst 5 matchups
  win%   matchup                            record    prizes  turns
   10.0%  Greninja ex (aggro)                1-9-0   -3.2   10.0
   20.0%  Mega Lucario ex (standard)         2-8-0   -2.5   10.3
   ...
```

If your own list is not Standard-legal the report says so and plays it anyway —
the field stays legal, so you are told what you are measuring.

A thousand games take about seven seconds. Flags: `-n` games per opponent,
`--decks N` to cut the field down, `--rows N` for only the worst and best N
matchups (the default prints all 100), `--seed`, `--turn-limit`, `--json`.

The field lives in `pokedeck/data/gauntlet/` as 100 readable decklists — 25
archetypes (Dragapult ex, Hydreigon ex, Mega Lucario ex, Mega Dragonite ex,
Cynthia's Garchomp ex, Raging Bolt ex, Miraidon ex, Terapagos ex, Steven's
Metagross ex, …) in four variants each: `standard`, `aggro`, `techy` and
`grind`. The builder picks the newest legal print of every card, derives the
Energy from what the attacker's own attack costs, keeps each list to one ACE
SPEC, and refuses to write a deck that fails the construction or format check.
Rebuild or edit the field with `python tools/build_gauntlet.py`.

## What the battle engine models

Every game is played out properly, by the same heuristic player on both sides:

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

The player it uses is a decent club player, not a champion: it benches early,
evolves on curve, stacks Energy on the attacker that is closest to its real
attack, draws only when the hand is thin (decking yourself is a loss), gusts
with Boss's Orders when the gust scores a knockout, retreats a dead Active, and
attacks for the knockout when one is available.

**Not modelled:** the Lost Zone, most damage-modifying Abilities, Stadium
effects beyond occupying the slot, Ability lock, attack choices that depend on
reading the opponent, and any card text the compiler could not parse. Nothing is
silently invented: an unreadable rider just does not fire, and the coverage line
in every report tells you how much of your deck was taken literally.

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

## Decklist format

The PTCG Live / PTCGO export format, with or without set codes. Set codes pin
the exact print (and therefore the exact card), which matters when a Pokémon has
been printed more than once:

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
