"""Tune the position score by playing candidate weights against the current ones.

    python tools/tune_scoring.py --candidates 8 --games 40

Each candidate plays the incumbent with seat and turn order balanced, and only
a candidate that clears a margin is reported — a weight set that wins by noise
is not an improvement.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokedeck import scoring  # noqa: E402
from pokedeck.battle import Battle, BattleDeck  # noqa: E402
from pokedeck.decklist import parse_file  # noqa: E402
from pokedeck.knowledge import resolve  # noqa: E402
from pokedeck.planner import ChampionPolicy  # noqa: E402
from pokedeck.scoring import Weights  # noqa: E402

TUNABLE = ("prize", "ko_threat", "ko_risk", "board", "hand", "survival",
           "endgame", "liability")


def load(path: str) -> BattleDeck:
    deck = parse_file(path)
    return BattleDeck.build(deck, resolve(deck))


def duel(decks, candidate: Weights, incumbent: Weights, games: int, rng: random.Random) -> float:
    """Win rate for ``candidate``. Each side scores with its own weights."""
    wins = 0
    for seed in range(games):
        candidate_side = seed % 2
        first = (seed // 2) % 2
        players = [ChampionPolicy(seed=seed), ChampionPolicy(seed=seed + 991)]
        weights = [incumbent, incumbent]
        weights[candidate_side] = candidate

        battle = Battle(tuple(decks), tuple(players), random.Random(seed), first=first)
        # The score is global, so each player's turn runs under its own weights.
        original_take_turn = battle.take_turn

        def take_turn(index: int, _take=original_take_turn) -> None:
            previous = scoring.use(weights[index])
            try:
                _take(index)
            finally:
                scoring.use(previous)

        battle.take_turn = take_turn
        result = battle.play()
        wins += result.winner == candidate_side
    return wins / max(1, games)


def sample(rng: random.Random, base: Weights) -> Weights:
    changes = {}
    for field in rng.sample(TUNABLE, k=rng.randint(1, 3)):
        current = getattr(base, field)
        changes[field] = round(current * rng.uniform(0.4, 2.2), 2)
    return base.replace(**changes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=int, default=8)
    parser.add_argument("--games", type=int, default=40)
    parser.add_argument("--margin", type=float, default=0.60, help="win rate a candidate must clear")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--decks", nargs="*", default=["examples/dragapult.txt",
                                                       "examples/raging-bolt.txt"])
    args = parser.parse_args()

    rng = random.Random(args.seed)
    decks = [load(path) for path in args.decks]
    pairing = (decks[0], decks[-1])
    incumbent = scoring.WEIGHTS

    print(f"incumbent: {incumbent}\n")
    best, best_rate = None, 0.5
    for number in range(args.candidates):
        candidate = sample(rng, incumbent)
        rate = duel(pairing, candidate, incumbent, args.games, rng)
        changed = {f: getattr(candidate, f) for f in TUNABLE
                   if getattr(candidate, f) != getattr(incumbent, f)}
        flag = "  <-- better" if rate >= args.margin else ""
        print(f"  {number + 1}. {rate:.0%}  {changed}{flag}", flush=True)
        if rate > best_rate:
            best, best_rate = candidate, rate
    print(f"\nbest: {best_rate:.0%} {best if best else '(nothing beat the incumbent)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
