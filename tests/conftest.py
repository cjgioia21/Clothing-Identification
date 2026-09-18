import random

import pytest

from pokedeck.decklist import parse
from pokedeck.engine import Config, Game
from pokedeck.knowledge import resolve

CHARIZARD = """
Pokémon: 13
4 Charmander PAF 7
1 Charmeleon PAF 8
3 Charizard ex OBF 125
2 Pidgey MEW 16
2 Pidgeot ex OBF 164
1 Radiant Greninja ASR 46

Trainer: 34
4 Professor's Research SVI 189
3 Iono PAL 185
2 Boss's Orders PAL 172
1 Arven OBF 186
4 Ultra Ball SVI 196
4 Rare Candy SVI 191
4 Nest Ball SVI 181
3 Buddy-Buddy Poffin TEF 144
2 Super Rod PAL 188
2 Counter Catcher PAR 160
2 Switch SVI 194
1 Night Stretcher SFA 61
2 Artazon PAL 171

Energy: 13
9 Basic Fire Energy SVE 2
4 Basic Water Energy SVE 3
"""


@pytest.fixture
def charizard_deck():
    return parse(CHARIZARD, name="charizard")


@pytest.fixture
def charizard_kb(charizard_deck):
    return resolve(charizard_deck)


def make_game(deck_text, config=None, seed=0, name="test"):
    """Build a game from a decklist string without shuffling surprises."""
    deck = parse(deck_text, name=name)
    resolution = resolve(deck)
    return Game(resolution, deck.cards(), config or Config(), random.Random(seed))


def zones_total(game):
    """Every card in the game, wherever it currently sits."""
    stacked = sum(len(spot.stack) for spot in game.in_play())
    return len(game.deck) + len(game.hand) + len(game.discard) + len(game.prizes) + stacked + len(game.attached)
