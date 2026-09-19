"""Monte Carlo runner: play a deck many times and aggregate what happened."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from math import sqrt
from statistics import fmean

from .cards import Deck
from .engine import IN_PLAY_PREFIX, Config, GameResult, play_game
from .knowledge import Resolution


@dataclass
class GoalStat:
    name: str
    by_turn: dict[int, float]  # cumulative probability of having the goal
    average_turn: float | None
    never: float
    prized: float


@dataclass
class TurnStat:
    turn: int
    supporter_rate: float
    average_bench: float
    average_energy: float
    average_hand: float


@dataclass
class SimReport:
    deck_name: str
    games: int
    turns: int
    going_first: bool
    mulligan_rate: float
    average_mulligans: float
    unplayable_rate: float
    opening_basics: float
    opening_supporters: float
    opening_energy: float
    no_supporter_opening: float
    goals: list[GoalStat] = field(default_factory=list)
    turn_stats: list[TurnStat] = field(default_factory=list)
    unknown_cards: list[str] = field(default_factory=list)

    def margin(self, probability: float) -> float:
        """95% confidence half-width for a probability from this many games."""
        return 1.96 * sqrt(max(probability * (1 - probability), 0.0) / self.games)


def run(
    deck: Deck,
    resolution: Resolution,
    config: Config,
    games: int = 5000,
    seed: int | None = None,
) -> SimReport:
    rng = random.Random(seed)
    cards = deck.cards()
    results = [play_game(resolution, cards, config, rng) for _ in range(games)]
    return summarise(deck, resolution, config, results)


def summarise(
    deck: Deck,
    resolution: Resolution,
    config: Config,
    results: list[GameResult],
) -> SimReport:
    games = len(results)
    playable = [r for r in results if not r.stuck]
    report = SimReport(
        deck_name=deck.name,
        games=games,
        turns=config.turns,
        going_first=config.going_first,
        mulligan_rate=_rate(results, lambda r: r.mulligans > 0),
        average_mulligans=fmean(r.mulligans for r in results) if results else 0.0,
        unplayable_rate=_rate(results, lambda r: r.stuck),
        opening_basics=fmean(r.opening_basics for r in playable) if playable else 0.0,
        opening_supporters=fmean(r.opening_supporters for r in playable) if playable else 0.0,
        opening_energy=fmean(r.opening_energy for r in playable) if playable else 0.0,
        no_supporter_opening=_rate(playable, lambda r: r.opening_supporters == 0),
        unknown_cards=list(resolution.unknown),
    )

    for goal in config.goals:
        key = " + ".join(goal)
        hits = [r.goal_turn.get(key) for r in playable]
        reached = [t for t in hits if t is not None]
        report.goals.append(
            GoalStat(
                name=key,
                by_turn={
                    turn: (sum(1 for t in reached if t <= turn) / len(playable) if playable else 0.0)
                    for turn in range(0, config.turns + 1)
                },
                average_turn=fmean(reached) if reached else None,
                never=1 - (len(reached) / len(playable)) if playable else 1.0,
                prized=_rate(
                    playable,
                    lambda r, g=goal: any(_bare(n) in r.prizes for n in g),
                ),
            )
        )

    for turn in range(1, config.turns + 1):
        snaps = [r.snapshots[turn - 1] for r in playable if len(r.snapshots) >= turn]
        if not snaps:
            continue
        report.turn_stats.append(
            TurnStat(
                turn=turn,
                supporter_rate=sum(1 for s in snaps if s.supporter_played) / len(snaps),
                average_bench=fmean(s.bench_size for s in snaps),
                average_energy=fmean(s.energy_in_play for s in snaps),
                average_hand=fmean(len(s.hand) for s in snaps),
            )
        )
    return report


def _bare(name: str) -> str:
    return name[len(IN_PLAY_PREFIX):] if name.startswith(IN_PLAY_PREFIX) else name


def _rate(results: list[GameResult], predicate) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if predicate(r)) / len(results)
