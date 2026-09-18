"""Command line interface: pokedeck check | sim | hand | odds | compare."""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import asdict

from .cards import Category, Deck, Stage
from .decklist import DecklistError, parse_file, validate
from .engine import IN_PLAY_PREFIX, Config, play_game
from .knowledge import Resolution, load_overrides, resolve
from .legality import FORMATS
from .legality import check as legality_check
from .gauntlet import POLICIES, load_field, run_gauntlet
from .report import (
    render_check,
    render_gauntlet,
    render_comparison,
    render_hands,
    render_odds_table,
    render_sim,
)
from .simulate import run


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (DecklistError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pokedeck", description="Playtest Pokémon TCG decks.")
    subs = parser.add_subparsers(dest="command", required=True)

    check = subs.add_parser("check", help="validate a decklist and show its shape")
    _add_common(check)
    check.add_argument("--format", default="standard", choices=sorted(FORMATS),
                       help="format to check legality against (default: standard)")
    check.set_defaults(handler=_cmd_check)

    sim = subs.add_parser("sim", help="simulate opening turns and report setup odds")
    _add_common(sim)
    _add_sim_options(sim)
    sim.set_defaults(handler=_cmd_sim)

    hand = subs.add_parser("hand", help="deal sample opening hands")
    _add_common(hand)
    hand.add_argument("-n", "--hands", type=int, default=5)
    hand.add_argument("--seed", type=int)
    hand.set_defaults(handler=_cmd_hand)

    odds = subs.add_parser("odds", help="exact hypergeometric odds for named cards")
    _add_common(odds)
    odds.add_argument("--card", action="append", default=[], help="card name (repeatable)")
    odds.add_argument("--turns", type=int, default=3)
    odds.set_defaults(handler=_cmd_odds)

    gauntlet = subs.add_parser("gauntlet", help="play 10 games against each of 100 opposing decks")
    _add_common(gauntlet)
    gauntlet.add_argument("-n", "--games", type=int, default=10, help="games per opposing deck")
    gauntlet.add_argument("--decks", type=int, default=0, help="use only the first N opposing decks")
    gauntlet.add_argument("--rows", type=int, default=0, help="show only the N worst and best matchups")
    gauntlet.add_argument("--seed", type=int, default=0)
    gauntlet.add_argument("--turn-limit", type=int, default=60, help="half-turns before a draw")
    gauntlet.add_argument("--policy", default="champion", choices=list(POLICIES),
                          help="how your deck is played (default: champion, which searches)")
    gauntlet.add_argument("--opponent-policy", default=None, choices=list(POLICIES),
                          help="how the field is played (default: the same as --policy)")
    gauntlet.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1),
                          help="processes to split the field across")
    gauntlet.set_defaults(handler=_cmd_gauntlet)

    compare = subs.add_parser("compare", help="simulate several decks and line up the results")
    compare.add_argument("decklists", nargs="+")
    compare.add_argument("--cards", help="JSON file of extra or corrected card definitions")
    compare.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    _add_sim_options(compare)
    compare.set_defaults(handler=_cmd_compare)

    return parser


def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("decklist", help="path to a PTCG Live / PTCGO export")
    sub.add_argument("--cards", help="JSON file of extra or corrected card definitions")
    sub.add_argument("--json", action="store_true", help="emit machine-readable JSON")


def _add_sim_options(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("-n", "--games", type=int, default=5000)
    sub.add_argument("--turns", type=int, default=3)
    sub.add_argument(
        "--goal",
        action="append",
        default=[],
        help="card to set up; combine pieces with '+' (repeatable)",
    )
    sub.add_argument("--second", action="store_true", help="play going second")
    sub.add_argument("--seed", type=int, default=0)
    sub.add_argument("--keep-hand", dest="keep_hand", action="store_true", default=True,
                     help="hold Professor's Research while the hand holds combo pieces (default)")
    sub.add_argument("--dump-hand", dest="keep_hand", action="store_false",
                     help="always play the biggest draw supporter available")


def _load(path: str, overrides_path: str | None) -> tuple[Deck, Resolution]:
    deck = parse_file(path)
    overrides = load_overrides(overrides_path) if overrides_path else None
    return deck, resolve(deck, overrides)


def _cmd_check(args) -> int:
    deck, resolution = _load(args.decklist, args.cards)
    issues = validate(deck)
    format_issues = legality_check(deck, resolution, args.format)
    if args.json:
        print(json.dumps(
            {
                "deck": deck.name,
                "size": deck.size,
                "format": args.format,
                "issues": [vars(i) for i in issues],
                "format_issues": [vars(i) for i in format_issues],
                "unknown_cards": resolution.unknown,
            },
            indent=2,
        ))
    else:
        print(render_check(deck, resolution, issues, format_issues, args.format))
    return 1 if any(i.level == "error" for i in issues + format_issues) else 0


def _cmd_sim(args) -> int:
    deck, resolution = _load(args.decklist, args.cards)
    config = _config(args, deck, resolution)
    report = run(deck, resolution, config, games=args.games, seed=args.seed)
    print(json.dumps(asdict(report), indent=2) if args.json else render_sim(report))
    return 0


def _cmd_hand(args) -> int:
    deck, resolution = _load(args.decklist, args.cards)
    rng = random.Random(args.seed)
    config = Config(turns=0)
    hands = [play_game(resolution, deck.cards(), config, rng).opening_hand for _ in range(args.hands)]
    print(json.dumps(hands, indent=2) if args.json else render_hands(hands))
    return 0


def _cmd_odds(args) -> int:
    deck, resolution = _load(args.decklist, args.cards)
    names = args.card or [e.name for e in deck.entries]
    for name in names:
        if deck.entry_for(name) is None:
            raise ValueError(f"{name!r} is not in {deck.name}")
    names = [deck.entry_for(n).name for n in names]
    if args.json:
        from .odds import at_least, cards_seen, prized

        print(json.dumps(
            {
                name: {
                    "copies": deck.count_of(name),
                    "by_turn": {
                        t: at_least(deck.count_of(name), cards_seen(t), deck.size)
                        for t in range(args.turns + 1)
                    },
                    "prized": prized(deck.count_of(name), deck.size),
                }
                for name in names
            },
            indent=2,
        ))
    else:
        print(render_odds_table(deck, names, args.turns))
    return 0


def _cmd_gauntlet(args) -> int:
    deck, resolution = _load(args.decklist, args.cards)
    field = load_field(args.decks or None)
    report = run_gauntlet(
        deck,
        resolution,
        field,
        games_per_deck=args.games,
        seed=args.seed,
        turn_limit=args.turn_limit,
        policy=args.policy,
        opponent_policy=args.opponent_policy,
        workers=args.workers,
    )
    if args.json:
        print(json.dumps(_gauntlet_json(report), indent=2))
    else:
        print(render_gauntlet(report, rows=args.rows))
    return 0


def _gauntlet_json(report) -> dict:
    return {
        "deck": report.deck_name,
        "policy": report.policy,
        "games": report.games,
        "opponents": report.opponents,
        "record": {"wins": report.wins, "losses": report.losses, "ties": report.ties},
        "win_rate": report.win_rate,
        "win_rate_first": report.win_rate_first,
        "win_rate_second": report.win_rate_second,
        "prize_margin": report.prize_margin,
        "average_turns": report.average_turns,
        "decided_by": dict(report.reasons),
        "coverage": report.coverage,
        "illegal_cards": report.illegal_cards,
        "unknown_cards": report.unknown_cards,
        "partial_cards": report.partial_cards,
        "matchups": [
            {
                "opponent": m.opponent,
                "games": m.games,
                "wins": m.wins,
                "losses": m.losses,
                "ties": m.ties,
                "win_rate": m.win_rate,
                "prize_margin": m.prize_margin,
                "average_turns": m.average_turns,
            }
            for m in report.sorted_matchups()
        ],
    }


def _cmd_compare(args) -> int:
    reports = []
    for path in args.decklists:
        deck, resolution = _load(path, args.cards)
        config = _config(args, deck, resolution)
        reports.append(run(deck, resolution, config, games=args.games, seed=args.seed))
    if args.json:
        print(json.dumps([asdict(r) for r in reports], indent=2))
    else:
        print(render_comparison(reports))
    return 0


def _config(args, deck: Deck, resolution: Resolution) -> Config:
    goals = _parse_goals(args.goal, deck) or default_goals(deck, resolution)
    return Config(
        going_first=not args.second,
        turns=args.turns,
        goals=tuple(goals),
        keep_goal_cards=args.keep_hand,
    )


def _parse_goals(raw_goals: list[str], deck: Deck) -> list[tuple[str, ...]]:
    """Turn --goal strings into tuples of deck card names.

    "Rare Candy + Charmander" needs both pieces; "play:Charizard ex" only
    counts once the card is on the board.
    """
    goals: list[tuple[str, ...]] = []
    for raw in raw_goals:
        pieces = []
        for piece in raw.split("+"):
            piece = piece.strip()
            in_play = piece.lower().startswith(IN_PLAY_PREFIX)
            if in_play:
                piece = piece[len(IN_PLAY_PREFIX):].strip()
            entry = deck.entry_for(piece)
            if entry is None:
                raise ValueError(f"{piece!r} is not in {deck.name}")
            pieces.append(IN_PLAY_PREFIX + entry.name if in_play else entry.name)
        goals.append(tuple(pieces))
    return goals


def default_goals(deck: Deck, resolution: Resolution, limit: int = 3) -> list[tuple[str, ...]]:
    """Without --goal, aim for the deck's evolved Pokémon, then its best Basic."""
    evolutions = [
        e for e in deck.entries
        if resolution.get(e.name).category is Category.POKEMON
        and resolution.get(e.name).stage in (Stage.STAGE1, Stage.STAGE2)
    ]
    evolutions.sort(key=lambda e: (resolution.get(e.name).stage is not Stage.STAGE2, -e.count, e.name))
    if evolutions:
        return [(e.name,) for e in evolutions[:limit]]
    basics = [e for e in deck.entries if resolution.get(e.name).is_basic_pokemon]
    basics.sort(key=lambda e: (-e.count, e.name))
    return [(e.name,) for e in basics[:1]]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
