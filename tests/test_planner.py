import random

import pytest

from pokedeck.battle import Battle, Spot
from pokedeck.scoring import evaluate
from pokedeck.planner import ChampionPolicy, apply_action, legal_actions
from pokedeck.policy import Policy
from pokedeck.pool import load_pool

from .test_battle import make_battle


def played_out(seed=0, turns=6, first=0):
    battle = make_battle(seed=seed, first=first)
    battle.setup()
    for _ in range(turns):
        battle.turn += 1
        battle.take_turn(battle.current)
        if battle.finished:
            break
        battle.between_turns(battle.current)
        battle.current = 1 - battle.current
    return battle


# ------------------------------------------------------------------ cloning
def test_a_clone_is_independent_of_the_real_game():
    battle = played_out()
    clone = battle.clone(seed=1)
    clone.sides[0].hand.append(clone.sides[0].deck.pop())
    clone.sides[0].active.damage += 50
    assert len(clone.sides[0].hand) != len(battle.sides[0].hand)
    assert clone.sides[0].active.damage != battle.sides[0].active.damage


def test_determinizing_keeps_what_the_player_can_see():
    battle = played_out()
    clone = battle.clone(determinize_for=0, seed=7)
    mine, theirs = battle.sides[0], battle.sides[1]
    assert [c.name for c in clone.sides[0].hand] == [c.name for c in mine.hand]
    assert len(clone.sides[0].deck) == len(mine.deck)
    assert len(clone.sides[1].hand) == len(theirs.hand)
    assert len(clone.sides[1].prizes) == len(theirs.prizes)
    assert sorted(c.name for c in clone.sides[0].deck + clone.sides[0].prizes) == \
        sorted(c.name for c in mine.deck + mine.prizes)


def test_determinizing_reshuffles_what_it_cannot():
    battle = played_out()
    hands = {
        tuple(sorted(c.name for c in battle.clone(determinize_for=0, seed=s).sides[1].hand))
        for s in range(6)
    }
    assert len(hands) > 1  # the opponent's hand is not read off the table


def test_the_real_game_keeps_its_own_randomness():
    battle = played_out()
    before = battle.rng.random()
    battle.clone(determinize_for=0, seed=3)
    battle.clone(determinize_for=0, seed=4)
    replay = random.Random()
    replay.setstate(battle.rng.getstate())
    assert replay.random() == battle.rng.random()
    assert before != replay.random()


# ------------------------------------------------------------------- actions
def test_actions_cover_the_turn():
    battle = played_out(turns=4)
    kinds = {a.kind for a in legal_actions(battle, battle.current)}
    assert kinds <= {"ability", "bench", "evolve", "energy", "supporter", "item",
                     "tool", "stadium", "retreat"}


def test_duplicate_cards_collapse_into_one_action():
    battle = played_out()
    side = battle.sides[0]
    pool = load_pool()
    side.hand = [pool.lookup("Carmine", "TWM", "145")] * 4
    side.supporter_used = False
    battle.turn = 4
    supporters = [a for a in legal_actions(battle, 0) if a.kind == "supporter"]
    assert len(supporters) == 1


def test_applying_an_action_changes_only_the_board_it_is_given():
    battle = played_out()
    battle.turn += 1
    side = battle.sides[0]
    side.energy_attached = 0
    energy = next((c for c in side.hand if c.category.value == "energy"), None)
    if energy is None:
        energy = load_pool().lookup("Basic Fire Energy")
        side.hand.append(energy)
    action = next(a for a in legal_actions(battle, 0) if a.kind == "energy")

    clone = battle.clone(seed=2)
    assert apply_action(clone, 0, action)
    assert clone.sides[0].energy_attached == 1
    assert side.energy_attached == 0


# ---------------------------------------------------------------- evaluation
def test_evaluation_is_symmetric():
    battle = played_out()
    assert evaluate(battle, 0) == pytest.approx(-evaluate(battle, 1))


def test_winning_beats_losing():
    battle = played_out()
    battle.finished = True
    battle.winner = 0
    assert evaluate(battle, 0) > 1000
    assert evaluate(battle, 1) < -1000


def test_prizes_taken_dominate_the_score():
    battle = played_out()
    before = evaluate(battle, 0)
    battle.sides[0].prizes_taken += 2
    assert evaluate(battle, 0) > before + 100


# ------------------------------------------------------------------ strength
def test_the_champion_outplays_the_greedy_policy():
    """Same decks, same seeds, shipped settings — only the player differs."""
    from .test_battle import DRAGAPULT
    from pokedeck.battle import BattleDeck
    from pokedeck.decklist import parse
    from pokedeck.knowledge import resolve

    deck = parse(DRAGAPULT, name="mirror")
    built = BattleDeck.build(deck, resolve(deck))
    wins = 0
    games = 30
    for seed in range(games):
        champion_side = seed % 2
        champion = ChampionPolicy(seed=seed)  # the settings the tool ships with
        players = (champion, Policy()) if champion_side == 0 else (Policy(), champion)
        result = Battle((built, built), players, random.Random(seed), first=seed % 2).play()
        wins += result.winner == champion_side
    assert wins >= games * 0.55
