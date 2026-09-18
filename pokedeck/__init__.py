"""pokedeck — playtest Pokémon TCG decks from the command line.

    from pokedeck import parse, resolve, Config, run

    deck = parse(open("deck.txt").read())
    report = run(deck, resolve(deck), Config(turns=3, goals=(("Charizard ex",),)))
"""

from .cards import Card, Deck, DeckEntry
from .decklist import DecklistError, Issue, format_deck, parse, parse_file, validate
from .engine import Config, GameResult, play_game
from .knowledge import Resolution, resolve
from .simulate import SimReport, run

__all__ = [
    "Card",
    "Config",
    "Deck",
    "DeckEntry",
    "DecklistError",
    "GameResult",
    "Issue",
    "Resolution",
    "SimReport",
    "format_deck",
    "parse",
    "parse_file",
    "play_game",
    "resolve",
    "run",
    "validate",
]

__version__ = "0.1.0"
