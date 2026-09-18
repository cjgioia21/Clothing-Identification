"""pokedeck — playtest Pokémon TCG decks from the command line.

    from pokedeck import parse_file, resolve, load_field, run_gauntlet

    deck = parse_file("deck.txt")
    report = run_gauntlet(deck, resolve(deck), load_field(), games_per_deck=10)
    print(report.win_rate)
"""

from .cards import Card, Deck, DeckEntry
from .decklist import DecklistError, Issue, format_deck, parse, parse_file, validate
from .battle import Battle, BattleDeck, BattleResult
from .engine import Config, GameResult, play_game
from .gauntlet import GauntletReport, load_field, run_gauntlet
from .scoring import evaluate
from .planner import ChampionPolicy
from .policy import Policy
from .pool import load_pool
from .knowledge import Resolution, resolve
from .simulate import SimReport, run

__all__ = [
    "Battle",
    "BattleDeck",
    "BattleResult",
    "Card",
    "ChampionPolicy",
    "Config",
    "Deck",
    "DeckEntry",
    "DecklistError",
    "GameResult",
    "GauntletReport",
    "Issue",
    "Policy",
    "Resolution",
    "SimReport",
    "evaluate",
    "format_deck",
    "load_field",
    "load_pool",
    "parse",
    "parse_file",
    "play_game",
    "resolve",
    "run",
    "run_gauntlet",
    "validate",
]

__version__ = "0.1.0"
