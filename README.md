# pokedeck

Playtest Pokémon TCG decks without shuffling: paste a decklist export, get
legality checks, exact draw odds, and a Monte Carlo goldfish simulation of the
first few turns.

No dependencies beyond the standard library.

```bash
pip install -e .
pokedeck check examples/charizard.txt
```

## Commands

### `check` — is the deck legal, and what shape is it?

```
$ pokedeck check examples/charizard.txt
examples/charizard.txt — 60 cards

Composition
  pokemon              13
  basics                7
  evolutions            6
  trainers             34
  supporters           10
  draw supporters       8
  items                22
  ball/search items    11
  ...

Opening-hand maths (no draw support)
  mulligan rate (no Basic in 7)       39.9%
  draw supporter in opening 7         65.4%
  draw supporter by turn 2            75.1%
```

Exits non-zero when the deck breaks a construction rule (60 cards, four copies
per card, at least one Pokémon; basic Energy is exempt from the copy limit).

### `sim` — how often does the deck actually set up?

```
$ pokedeck sim examples/charizard.txt -n 5000 --turns 3 \
    --goal "play:Charizard ex" --goal "Rare Candy + Charmander"

Turn by turn
  turn  supporter  bench  energy  hand
     1   61.6%      2.1    0.7    4.0
     2   44.5%      2.6    1.3    3.3
     3   37.1%      2.9    1.8    3.4

Setup odds (cumulative, card in hand or in play)
  goal                         T0      T1      T2      T3     avg   prized
  play:Charizard ex          0.0%    0.0%   38.9%   54.2%    2.28   28.8%
  Rare Candy + Charmander   24.2%   57.0%   72.0%   80.3%    1.09   57.6%
```

Goal syntax:

- `--goal "Charizard ex"` — the card is in hand or in play.
- `--goal "play:Charizard ex"` — the card is on the board.
- `--goal "Rare Candy + Charmander"` — every piece at once, checked the moment
  they line up (not just at end of turn).
- `prized` is the share of games where at least one piece of the goal started
  in the prize cards.

Without `--goal`, the deck's evolved Pokémon are used as the goals.

Other flags: `--second` (play going second), `-n` games, `--turns`, `--seed`,
`--json`, and `--dump-hand` to make the bot always fire off its biggest draw
supporter instead of holding combo pieces.

### `hand` — deal sample opening hands

```
$ pokedeck hand examples/gardevoir.txt -n 2 --seed 7
```

### `odds` — exact hypergeometric numbers, no simulation

```
$ pokedeck odds examples/charizard.txt --card "Rare Candy" --turns 2
  card                            copies      T0      T1      T2   prized
  Rare Candy                         4     39.9%   44.5%   48.8%    35.1%
```

### `compare` — the same goals across several lists

```
$ pokedeck compare list-a.txt list-b.txt -n 5000 --goal "play:Charizard ex"
```

## Decklist format

The PTCG Live / PTCGO export format, with or without set codes:

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

`pokedeck/data/cards.json` holds the card behaviour the simulator knows about.
Anything missing is simulated as a blank card of its decklist category (and
reported, so you can see what was ignored). Add or correct cards with a JSON
file of the same shape:

```json
{"cards": [
  {"name": "Spoink", "category": "pokemon", "stage": "basic",
   "ability_name": "Bounce", "ability": [{"op": "draw", "n": 2}]},
  {"name": "Mystery Ball", "category": "trainer", "subtype": "item",
   "effects": [{"op": "discard_from_hand", "n": 1},
               {"op": "search", "filter": "basic_pokemon", "n": 1, "dest": "bench"}]}
]}
```

```bash
pokedeck sim deck.txt --cards my-cards.json
```

Effect ops: `draw`, `draw_to`, `draw_prizes`, `discard_hand`,
`shuffle_hand_into_deck`, `discard_from_hand`, `search` (with `filter` and
`dest`), `recover`. Search filters: `any`, `pokemon`, `basic_pokemon`, `item`,
`tool`, `supporter`, `stadium`, `energy`, `basic_energy`. `ability_trigger` is
`turn` (once per turn) or `on_play`.

## What the simulator does and does not model

It goldfishes: one player, no opponent. Each turn it draws, uses abilities,
plays search items, plays a draw supporter, evolves, and attaches one Energy,
following a greedy policy:

- Balls that cost cards are held until the draw supporter has been played.
- A hand-dumping supporter is held back only when the hand already has two
  goal pieces and six or more cards (`--dump-hand` turns this off).
- Discards are paid with blanks first, then spare Pokémon, then items — never
  with goal pieces while anything else is available.
- Evolution follows the real timing rule: nothing evolves on the first turn of
  the game or the turn it hits the board; Rare Candy skips the middle stage.

It does not model: attacking, damage, knockouts, prize trades, the opponent's
board, Stadium effects, Ability lock, or anything that depends on what the
other player does. Numbers from `sim` are setup consistency, not win rates.

## Library use

```python
from pokedeck import parse_file, resolve, Config, run

deck = parse_file("deck.txt")
report = run(deck, resolve(deck), Config(turns=3, goals=(("play:Charizard ex",),)), games=5000)
print(report.goals[0].by_turn[2])
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```
