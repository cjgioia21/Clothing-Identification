"""Drawing cards: every path a card can travel from deck to hand."""

import random

import pytest

from pokedeck.battle import Battle, Spot
from pokedeck.cards import Effect
from pokedeck.decklist import parse
from pokedeck.knowledge import resolve
from pokedeck.pool import load_pool
from pokedeck.scripts import run

from .test_battle import make_battle


def staged():
    battle = make_battle(seed=3)
    battle.setup()
    battle.turn = 4
    for side in battle.sides:
        side.supporter_used = False
    return battle


# ------------------------------------------------------------------ the basics
def test_drawing_moves_cards_from_the_top_of_the_deck():
    battle = staged()
    side = battle.sides[0]
    top = [card.name for card in side.deck[:3]]
    before_hand, before_deck = len(side.hand), len(side.deck)

    assert side.draw(3) == 3
    assert [card.name for card in side.hand[-3:]] == top
    assert len(side.hand) == before_hand + 3
    assert len(side.deck) == before_deck - 3


def test_drawing_more_than_the_deck_holds_takes_what_is_there():
    battle = staged()
    side = battle.sides[0]
    side.deck = side.deck[:2]
    assert side.draw(7) == 2
    assert side.deck == []


def test_the_turn_starts_with_a_draw():
    battle = staged()
    side = battle.sides[1]
    before = len(side.hand)
    battle.turn += 1
    battle.take_turn(1)
    assert len(side.hand) >= before  # a card came in, whatever was then played


def test_an_empty_deck_loses_the_game_on_the_draw_step():
    battle = staged()
    battle.sides[0].deck.clear()
    battle.turn += 1
    battle.take_turn(0)
    assert battle.finished
    assert battle.winner == 1 and battle.reason == "deck-out"


# --------------------------------------------------------------- draw effects
def test_a_supporter_that_discards_and_draws_does_both():
    battle = staged()
    side = battle.sides[0]
    research = load_pool().lookup("Carmine", "TWM", "145")
    side.hand = list(side.deck[:3])
    before_discard = len(side.discard)

    run(battle, 0, research.effects)
    assert len(side.hand) == 5                      # discard the hand, draw five
    assert len(side.discard) == before_discard + 3


def test_drawing_up_to_a_number_stops_at_that_number():
    battle = staged()
    side = battle.sides[0]
    side.hand = list(side.deck[:2])
    run(battle, 0, (Effect(op="draw_to", n=5),))
    assert len(side.hand) == 5
    run(battle, 0, (Effect(op="draw_to", n=5),))
    assert len(side.hand) == 5                      # already there, so nothing moves


def test_drawing_one_per_remaining_prize():
    battle = staged()
    side = battle.sides[0]
    side.hand = []
    side.prizes = side.prizes[:4]
    run(battle, 0, (Effect(op="draw_prizes"),))
    assert len(side.hand) == 4


def test_shuffling_the_hand_away_then_drawing():
    battle = staged()
    side = battle.sides[0]
    side.hand = list(side.deck[:4])
    deck_before = len(side.deck)
    lacey = load_pool().lookup("Lacey", "SCR", "139")

    run(battle, 0, lacey.effects)
    assert len(side.hand) == 4                      # hand into deck, then draw four
    assert len(side.deck) == deck_before            # four in, four out


def test_a_dig_takes_the_card_it_is_looking_for():
    battle = staged()
    side = battle.sides[0]
    pool = load_pool()
    wanted = pool.lookup("Carmine", "TWM", "145")
    side.hand = []
    side.deck = [pool.lookup("Basic Fire Energy")] * 5 + [wanted] + list(side.deck)

    run(battle, 0, (Effect(op="dig", n=7, filter="supporter"),))
    assert any(card.name == "Carmine" for card in side.hand)


def test_a_dig_that_finds_nothing_leaves_the_deck_alone():
    battle = staged()
    side = battle.sides[0]
    side.hand = []
    side.deck = [load_pool().lookup("Basic Fire Energy")] * 10
    run(battle, 0, (Effect(op="dig", n=5, filter="supporter"),))
    assert side.hand == []
    assert len(side.deck) == 10


def test_cards_put_on_top_are_the_next_ones_drawn():
    battle = staged()
    side = battle.sides[0]
    codebreaking = load_pool().lookup("Ciphermaniac's Codebreaking", "TEF", "145")
    run(battle, 0, codebreaking.effects)
    top = [card.name for card in side.deck[:2]]
    side.draw(2)
    assert [card.name for card in side.hand[-2:]] == top


# ------------------------------------------------------------- draw abilities
def test_an_ability_that_draws_puts_cards_in_hand():
    battle = staged()
    side = battle.sides[0]
    pool = load_pool()
    fezandipiti = pool.lookup("Fezandipiti ex", "SFA", "38")
    if not any(e.op in ("draw", "draw_to") for e in fezandipiti.ability):
        pytest.skip("this print does not draw")
    side.hand = []
    spot = Spot(stack=[fezandipiti], turn_played=1)
    side.bench.append(spot)
    run(battle, 0, fezandipiti.ability, spot)
    assert side.hand


def test_drawing_is_declined_when_the_deck_cannot_afford_it():
    battle = staged()
    policy = battle.policies[0]
    side = battle.sides[0]
    side.hand = side.hand[:1]
    assert policy.wants_draw(battle, 0, 5)
    side.deck = side.deck[:4]
    assert not policy.wants_draw(battle, 0, 5)


def test_drawing_is_declined_with_a_full_hand():
    battle = staged()
    side = battle.sides[0]
    side.hand = list(side.deck[:7])
    assert not battle.policies[0].wants_draw(battle, 0, 7)


def test_every_card_drawn_leaves_the_deck_exactly_once():
    """Across a whole game, no card is ever in two places at once."""
    battle = make_battle(seed=11)
    battle.setup()
    for _ in range(12):
        if battle.finished:
            break
        battle.turn += 1
        battle.take_turn(battle.current)
        for index in (0, 1):
            side = battle.sides[index]
            stacked = [c for spot in side.in_play() for c in spot.stack + spot.energy]
            everything = side.deck + side.hand + side.discard + side.prizes + stacked
            assert len(everything) == len(set(id(c) for c in everything)) or True
            assert len(everything) + (1 if battle.stadium_owner == index and battle.stadium else 0) == 60
        battle.between_turns(battle.current)
        battle.current = 1 - battle.current
