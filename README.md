# pokedeck

Playtest Pokémon TCG decks without shuffling. Paste a decklist export and the
tool plays it — 1,000 full games against a 100-deck gauntlet, with real printed
cards, real attacks, prizes and knockouts — then reports the matchup spread.

Card data comes from the [TCGdex](https://tcgdex.dev) database (every Scarlet &
Violet and Mega Evolution set, ~5,000 cards) and ships inside the package, so
nothing calls the network at runtime. No dependencies beyond the standard
library.

```bash
pip install -e .
pokedeck gauntlet examples/charizard.txt
```

## The gauntlet

100 opposing decks × 10 games each. Turn order alternates game by game, so every
matchup is scored from both sides of the coin flip.

```
$ pokedeck gauntlet examples/charizard.txt -n 10 --rows 5
examples/charizard.txt vs the gauntlet — 100 decks × 10 games (1000 games)

  record            721-279-0   (72.1% ±2.8%)
  going first        70.0%   (500 games)
  going second       74.2%   (500 games)
  prize margin      +2.52 per game   (4.68 taken, 2.17 given)
  game length       9.7 turns each
  decided by        prizes 73%, deck-out 16%, bench-out 11%
  card text modelled 100.0%

Worst 5 matchups
  win%   matchup                       record    prizes  turns
   20.0%  Greninja ex (aggro)           2-8-0   -3.1    7.0
   20.0%  Archaludon ex (grind)         2-8-0   -2.4    8.3
   ...
```

A thousand games take about seven seconds. Flags: `-n` games per opponent,
`--decks N` to cut the field down, `--rows N` for only the worst and best N
matchups (the default prints all 100), `--seed`, `--turn-limit`, `--json`.

The field lives in `pokedeck/data/gauntlet/` as 100 readable decklists — 25
archetypes (Charizard ex, Gardevoir ex, Dragapult ex, Raging Bolt ex, Miraidon
ex, Gholdengo ex, Terapagos ex, Mega Lucario ex, …) in four variants each:
`standard`, `aggro`, `techy` and `grind`. Rebuild or edit the field with
`python tools/build_gauntlet.py`.

## What the battle engine models

Every game is played out properly, by the same heuristic player on both sides:

- **Setup** — shuffle, seven cards, mulligans (and the extra draw they give the
  opponent), a Basic to the Active Spot, up to five on the Bench, six prizes.
- **Turns** — draw, Abilities, Trainers (one Supporter, one Stadium, any number
  of Items), evolution on the real timing rule, one Energy attachment, one
  retreat paid in Energy, then an attack. The player going first cannot attack
  on turn one.
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
$ pokedeck check examples/charizard.txt
Composition
  pokemon              13
  basics                7
  draw supporters       8
  ball/search items    11
  ...
Opening-hand maths (no draw support)
  mulligan rate (no Basic in 7)       39.9%
  draw supporter in opening 7         65.4%
```

Exits non-zero when the deck breaks a construction rule (60 cards, four copies
per card, at least one Pokémon; basic Energy is exempt from the copy limit).

### `sim` — how often does the deck set up?

A fast goldfish simulation of the opening turns, with no opponent:

```
$ pokedeck sim examples/charizard.txt -n 5000 --turns 3 \
    --goal "play:Charizard ex" --goal "Rare Candy + Charmander"
```

- `--goal "Charizard ex"` — the card is in hand or in play.
- `--goal "play:Charizard ex"` — the card is on the board.
- `--goal "Rare Candy + Charmander"` — every piece at once, scored the moment
  they line up.

### `odds` — exact hypergeometric numbers, no simulation

```
$ pokedeck odds examples/charizard.txt --card "Rare Candy" --turns 2
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
Pokémon: 13
4 Charmander PAF 7
3 Charizard ex OBF 125

Trainer: 34
4 Professor's Research SVI 189
...

Energy: 13
9 Basic Fire Energy SVE 2
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

deck = parse_file("deck.txt")
report = run_gauntlet(deck, resolve(deck), load_field(), games_per_deck=10)
print(report.win_rate, report.sorted_matchups()[0].opponent)
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```
