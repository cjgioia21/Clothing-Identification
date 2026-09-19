import random
from pathlib import Path

import pytest

from pokedeck.decklist import parse
from pokedeck.engine import Config, Game
from pokedeck.knowledge import resolve

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
CHARIZARD = (EXAMPLES / "rotated-charizard.txt").read_text(encoding="utf-8")
DRAGAPULT = (EXAMPLES / "dragapult.txt").read_text(encoding="utf-8")
RAGING_BOLT = (EXAMPLES / "raging-bolt.txt").read_text(encoding="utf-8")


@pytest.fixture
def charizard_deck():
    """A pre-rotation list: fine for parsing and odds, illegal in Standard."""
    return parse(CHARIZARD, name="charizard")


@pytest.fixture
def charizard_kb(charizard_deck):
    return resolve(charizard_deck)


@pytest.fixture
def legal_deck():
    return parse(DRAGAPULT, name="dragapult")


@pytest.fixture
def legal_kb(legal_deck):
    return resolve(legal_deck)


def make_game(deck_text, config=None, seed=0, name="test"):
    """Build a game from a decklist string without shuffling surprises."""
    deck = parse(deck_text, name=name)
    resolution = resolve(deck)
    return Game(resolution, deck.cards(), config or Config(), random.Random(seed))


def zones_total(game):
    """Every card in the game, wherever it currently sits."""
    stacked = sum(len(spot.stack) for spot in game.in_play())
    return len(game.deck) + len(game.hand) + len(game.discard) + len(game.prizes) + stacked + len(game.attached)
