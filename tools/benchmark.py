"""Play two players against each other and report who is actually better.

    python tools/benchmark.py                      # the shipped match-ups
    python tools/benchmark.py --games 120 --a champion --b tactical

Seat and turn order are varied independently across the seeds. Without that,
"player A always goes first" quietly hands A a handicap — going first cannot
attack on turn one — and a fair player looks like a losing one.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokedeck.battle import Battle, BattleDeck  # noqa: E402
from pokedeck.decklist import parse_file  # noqa: E402
from pokedeck.knowledge import resolve  # noqa: E402
from pokedeck.planner import ChampionPolicy  # noqa: E402
from pokedeck.policy import Policy  # noqa: E402

PLAYERS = {
    "greedy": lambda seed: Policy(),
    "champion": lambda seed: ChampionPolicy(seed=seed),
    "champion-deep": lambda seed: ChampionPolicy(seed=seed, rollouts=6, depth=3),
    "champion-wide": lambda seed: ChampionPolicy(seed=seed, rollouts=8, finalists=8),
    "champion-searching-rollouts": lambda seed: ChampionPolicy(
        seed=seed,
        rollout_policy=ChampionPolicy(seed=seed + 7, rollouts=1, depth=1, finalists=3,
                                      rollout_policy=Policy()),
    ),
}


def duel(decks, make_a, make_b, games: int = 60) -> tuple[float, float]:
    """Win rate for A, and seconds per game.

    Each seed plays A in both seats and in both turn orders, so the result is
    the players' difference rather than the seat's.
    """
    wins = played = 0
    start = time.time()
    for seed in range(games):
        a_side = seed % 2
        first = (seed // 2) % 2
        players = (make_a(seed), make_b(seed)) if a_side == 0 else (make_b(seed), make_a(seed))
        result = Battle(decks, players, random.Random(seed), first=first).play()
        played += 1
        wins += result.winner == a_side
    return wins / max(1, played), (time.time() - start) / max(1, played)


def load(path: str) -> BattleDeck:
    deck = parse_file(path)
    return BattleDeck.build(deck, resolve(deck))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a", default="champion", choices=sorted(PLAYERS))
    parser.add_argument("--b", default="greedy", choices=sorted(PLAYERS))
    parser.add_argument("--games", type=int, default=60)
    parser.add_argument("--decks", nargs="*", default=["examples/dragapult.txt",
                                                      "examples/raging-bolt.txt"])
    args = parser.parse_args()

    built = [(Path(p).stem, load(p)) for p in args.decks]
    print(f"{args.a} vs {args.b} — {args.games} games per match-up\n")
    for name, deck in built:
        rate, pace = duel((deck, deck), PLAYERS[args.a], PLAYERS[args.b], args.games)
        print(f"  {name + ' mirror':34} {rate:.0%}   {pace:.2f}s/game", flush=True)
    if len(built) > 1:
        (left_name, left), (right_name, right) = built[0], built[1]
        rate, pace = duel((left, right), PLAYERS[args.a], PLAYERS[args.b], args.games)
        print(f"  {left_name + ' vs ' + right_name:34} {rate:.0%}   {pace:.2f}s/game")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
