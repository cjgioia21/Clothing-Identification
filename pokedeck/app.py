"""The double-click front end: a menu for people who did not open a terminal.

Running the packaged executable with no arguments lands here. Drag a decklist
onto it, or pass one on the command line, and it goes straight to that deck.
"""

from __future__ import annotations

import multiprocessing
import os
import sys
from pathlib import Path

from .decklist import DecklistError, parse_file, validate
from .gauntlet import load_field, run_gauntlet
from .knowledge import resolve
from .legality import check as legality_check
from .report import render_check, render_gauntlet, render_hands, render_sim
from .engine import Config, play_game
from .simulate import run as run_sim

BANNER = r"""
  pokedeck — Pokemon TCG deck tester
  ------------------------------------------------
  Plays your deck against 100 Standard-legal decks.
"""


def main(argv: list[str] | None = None) -> int:
    multiprocessing.freeze_support()  # a packaged .exe re-runs itself for workers
    argv = list(sys.argv[1:] if argv is None else argv)
    print(BANNER)
    path = argv[0] if argv else None
    while True:
        path = path or ask_for_deck()
        if path is None:
            return 0
        try:
            deck = parse_file(path)
        except (DecklistError, FileNotFoundError, OSError) as exc:
            print(f"\n  Could not read that decklist: {exc}\n")
            path = None
            continue
        resolution = resolve(deck)
        print(f"\n  Loaded {Path(path).name} — {deck.size} cards\n")
        if not deck_menu(deck, resolution, path):
            return 0
        path = None


def ask_for_deck() -> str | None:
    """Ask for a decklist file, accepting a pasted path or a dragged file."""
    print("  Drop a decklist file here (or paste its path), then press Enter.")
    print("  Leave it empty to quit.\n")
    while True:
        raw = prompt("  Decklist: ")
        if raw is None or not raw.strip():
            return None
        candidate = raw.strip().strip('"').strip("'")
        if Path(candidate).is_file():
            return candidate
        print(f"  No file at {candidate!r} — try again.\n")


def deck_menu(deck, resolution, path: str) -> bool:
    """Run actions on a loaded deck. False means quit."""
    while True:
        print("  1) Check the deck (legality, composition, opening-hand odds)")
        print("  2) Play the gauntlet — 100 decks, 10 games each")
        print("  3) Quick gauntlet — 20 decks, 4 games each")
        print("  4) Setup odds (goldfish simulation)")
        print("  5) Deal sample opening hands")
        print("  6) Load a different deck")
        print("  7) Quit\n")
        choice = prompt("  Choose 1-7: ")
        if choice is None or choice.strip() in ("7", "q", "quit", "exit"):
            return False
        choice = choice.strip()
        print()
        if choice == "1":
            print(render_check(
                deck, resolution, validate(deck), legality_check(deck, resolution), "standard"
            ))
        elif choice in ("2", "3"):
            decks, games = (100, 10) if choice == "2" else (20, 4)
            print(f"  Playing {decks * games} games — this takes a few minutes.\n")
            report = run_gauntlet(
                deck,
                resolution,
                load_field(decks),
                games_per_deck=games,
                policy="champion",
                workers=max(1, (os.cpu_count() or 2) - 1),
            )
            print(render_gauntlet(report, rows=8))
            print("\n  Tip: run this from a terminal as `pokedeck gauntlet <deck>` for the full table.")
        elif choice == "4":
            config = Config(turns=3, goals=default_goals(deck, resolution))
            print(render_sim(run_sim(deck, resolution, config, games=3000)))
        elif choice == "5":
            import random

            rng = random.Random()
            hands = [
                play_game(resolution, deck.cards(), Config(turns=0), rng).opening_hand
                for _ in range(5)
            ]
            print(render_hands(hands))
        elif choice == "6":
            return True
        else:
            print("  Sorry, I did not understand that.")
        print()


def default_goals(deck, resolution):
    from .cli import default_goals as pick

    return tuple(pick(deck, resolution))


def prompt(message: str) -> str | None:
    try:
        return input(message)
    except (EOFError, KeyboardInterrupt):
        print()
        return None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
