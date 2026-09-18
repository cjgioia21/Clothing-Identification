"""Run a deck against the whole gauntlet field and score the matchups."""

from __future__ import annotations

import random
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from importlib import resources
from statistics import fmean

from .battle import DEFAULT_TURN_LIMIT, Battle, BattleDeck
from .decklist import Deck, parse
from .knowledge import Resolution, resolve
from .legality import card_is_legal
from .planner import ChampionPolicy
from .policy import Policy

POLICIES = ("champion", "greedy")


def make_policy(name: str, seed: int = 0):
    """Build a player. ``champion`` searches its turn; ``greedy`` follows rules."""
    if name == "greedy":
        return Policy()
    if name == "champion":
        return ChampionPolicy(seed=seed)
    raise ValueError(f"unknown policy {name!r} (try: {', '.join(POLICIES)})")

FIELD_PACKAGE = "pokedeck.data.gauntlet"


@dataclass
class Matchup:
    opponent: str
    games: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    prizes_for: int = 0
    prizes_against: int = 0
    turns: list[int] = field(default_factory=list)
    reasons: Counter = field(default_factory=Counter)

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def prize_margin(self) -> float:
        """Average prize difference — how close the losses actually were."""
        return (self.prizes_for - self.prizes_against) / self.games if self.games else 0.0

    @property
    def average_turns(self) -> float:
        return fmean(self.turns) if self.turns else 0.0


@dataclass
class MatchupOutcome:
    """One opponent's worth of games, as a worker hands it back."""

    matchup: Matchup
    first_games: int = 0
    first_wins: int = 0
    second_games: int = 0
    second_wins: int = 0


@dataclass
class GauntletReport:
    deck_name: str
    opponents: int
    games_per_deck: int
    policy: str = "greedy"
    games: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    first_games: int = 0
    first_wins: int = 0
    second_games: int = 0
    second_wins: int = 0
    prizes_for: int = 0
    prizes_against: int = 0
    turns: list[int] = field(default_factory=list)
    reasons: Counter = field(default_factory=Counter)
    matchups: list[Matchup] = field(default_factory=list)
    coverage: float = 1.0
    unknown_cards: list[str] = field(default_factory=list)
    partial_cards: list[str] = field(default_factory=list)
    illegal_cards: list[str] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.games if self.games else 0.0

    @property
    def win_rate_first(self) -> float:
        return self.first_wins / self.first_games if self.first_games else 0.0

    @property
    def win_rate_second(self) -> float:
        return self.second_wins / self.second_games if self.second_games else 0.0

    @property
    def average_turns(self) -> float:
        return fmean(self.turns) if self.turns else 0.0

    @property
    def prize_margin(self) -> float:
        return (self.prizes_for - self.prizes_against) / self.games if self.games else 0.0

    def margin(self) -> float:
        """95% confidence half-width on the overall win rate."""
        if not self.games:
            return 0.0
        p = self.win_rate
        return 1.96 * (max(p * (1 - p), 0.0) / self.games) ** 0.5

    def sorted_matchups(self) -> list[Matchup]:
        return sorted(self.matchups, key=lambda m: (m.win_rate, m.prize_margin))


def load_field(limit: int | None = None) -> list[tuple[Deck, Resolution]]:
    """Load the bundled gauntlet decks, in a stable order."""
    entries = []
    for item in sorted(resources.files(FIELD_PACKAGE).iterdir(), key=lambda p: p.name):
        if not item.name.endswith(".txt"):
            continue
        text = item.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip() or item.name
        deck = parse(text, name=title)
        entries.append((deck, resolve(deck)))
        if limit and len(entries) >= limit:
            break
    return entries


def run_gauntlet(
    deck: Deck,
    resolution: Resolution,
    field_decks: list[tuple[Deck, Resolution]] | None = None,
    games_per_deck: int = 10,
    seed: int = 0,
    turn_limit: int = DEFAULT_TURN_LIMIT,
    opponents: int | None = None,
    policy: str = "greedy",
    opponent_policy: str | None = None,
    workers: int = 1,
) -> GauntletReport:
    """Play ``games_per_deck`` games against every deck in the field.

    Turn order alternates game by game, so a matchup is scored from both sides
    of the coin flip. ``workers`` splits the field across processes; the games
    themselves are seeded per matchup, so the result does not depend on it.
    """
    field_decks = field_decks if field_decks is not None else load_field(opponents)
    opponent_policy = opponent_policy or policy
    mine = BattleDeck.build(deck, resolution)

    report = GauntletReport(
        deck_name=deck.name,
        opponents=len(field_decks),
        games_per_deck=games_per_deck,
        policy=policy,
        coverage=resolution.coverage(),
        unknown_cards=list(resolution.unknown),
        partial_cards=list(resolution.partial),
        illegal_cards=[
            entry.name for entry in deck.entries
            if not card_is_legal(resolution.get(entry.name))
            and resolution.get(entry.name).known
            and resolution.get(entry.name).regulation
        ],
    )

    jobs = [
        (mine, BattleDeck.build(opponent_deck, opponent_resolution), opponent_deck.name,
         position, games_per_deck, seed, turn_limit, policy, opponent_policy)
        for position, (opponent_deck, opponent_resolution) in enumerate(field_decks)
    ]

    if workers > 1 and len(jobs) > 1:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            outcomes = list(pool.map(_play_matchup, jobs, chunksize=1))
    else:
        outcomes = [_play_matchup(job) for job in jobs]

    for outcome in outcomes:
        _merge(report, outcome)
    return report


def _play_matchup(job) -> MatchupOutcome:
    """All the games against one opponent — the unit of work for a worker."""
    (mine, theirs, name, position, games, seed, turn_limit, policy, opponent_policy) = job
    outcome = MatchupOutcome(matchup=Matchup(opponent=name))
    for game in range(games):
        rng = random.Random((seed, position, game).__hash__())
        first = game % 2  # 0 = our deck starts
        players = (
            make_policy(policy, seed=rng.randrange(1 << 30)),
            make_policy(opponent_policy, seed=rng.randrange(1 << 30)),
        )
        battle = Battle((mine, theirs), players, rng, first=first, turn_limit=turn_limit)
        result = battle.play()
        _score_game(outcome, result, first)
    return outcome


def _score_game(outcome: MatchupOutcome, result, first: int) -> None:
    matchup = outcome.matchup
    mine, theirs = result.prizes_taken
    matchup.games += 1
    matchup.prizes_for += mine
    matchup.prizes_against += theirs
    matchup.turns.append(result.turns)
    matchup.reasons[result.reason] += 1
    if first == 0:
        outcome.first_games += 1
    else:
        outcome.second_games += 1
    if result.winner == 0:
        matchup.wins += 1
        if first == 0:
            outcome.first_wins += 1
        else:
            outcome.second_wins += 1
    elif result.winner == 1:
        matchup.losses += 1
    else:
        matchup.ties += 1


def _merge(report: GauntletReport, outcome: MatchupOutcome) -> None:
    matchup = outcome.matchup
    report.matchups.append(matchup)
    report.games += matchup.games
    report.wins += matchup.wins
    report.losses += matchup.losses
    report.ties += matchup.ties
    report.prizes_for += matchup.prizes_for
    report.prizes_against += matchup.prizes_against
    report.turns.extend(matchup.turns)
    report.reasons.update(matchup.reasons)
    report.first_games += outcome.first_games
    report.first_wins += outcome.first_wins
    report.second_games += outcome.second_games
    report.second_wins += outcome.second_wins
