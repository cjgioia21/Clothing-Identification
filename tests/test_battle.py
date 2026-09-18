import random

import pytest

from pokedeck.battle import ASLEEP, PARALYZED, Battle, BattleDeck, Side, Spot
from pokedeck.cards import Attack, Card, Category, Stage, Subtype
from pokedeck.decklist import parse
from pokedeck.knowledge import resolve
from pokedeck.policy import Policy
from pokedeck.pool import load_pool

from .conftest import DRAGAPULT, RAGING_BOLT


def make_battle(seed=0, first=0, a=DRAGAPULT, b=RAGING_BOLT, **kwargs):
    decks = []
    for text, name in ((a, "A"), (b, "B")):
        deck = parse(text, name=name)
        decks.append(BattleDeck.build(deck, resolve(deck)))
    return Battle(tuple(decks), (Policy(), Policy()), random.Random(seed), first=first, **kwargs)


def card_total(battle: Battle, index: int) -> int:
    """Every card that belongs to one player, wherever it currently sits."""
    side = battle.sides[index]
    stacked = sum(len(s.stack) + len(s.energy) + (1 if s.tool else 0) for s in side.in_play())
    stadium = 1 if battle.stadium is not None and battle.stadium_owner == index else 0
    return len(side.deck) + len(side.hand) + len(side.discard) + len(side.prizes) + stacked + stadium


@pytest.fixture
def battle():
    return make_battle()


def test_setup_deals_hands_prizes_and_a_starter(battle):
    assert battle.setup()
    for index, side in enumerate(battle.sides):
        assert len(side.prizes) == 6
        assert side.active is not None
        assert side.active.card.is_basic_pokemon
        assert card_total(battle, index) == 60


def test_no_basics_means_the_game_cannot_start():
    energy_only = "Energy: 60\n60 Basic Fire Energy SVE 2"
    battle = make_battle(a=energy_only)
    assert not battle.setup()
    assert battle.reason == "no-basics"


def test_cards_are_conserved_through_a_whole_game():
    for seed in range(5):
        battle = make_battle(seed=seed)
        battle.setup()
        while not battle.finished and battle.turn < 20:
            battle.turn += 1
            battle.take_turn(battle.current)
            battle.between_turns(battle.current)
            battle.current = 1 - battle.current
            for index in (0, 1):
                assert card_total(battle, index) == 60


def test_the_player_going_first_cannot_attack_on_turn_one(battle):
    battle.setup()
    battle.turn = 1
    assert not battle.can_attack(0)
    assert battle.can_attack(1)


def test_weakness_doubles_and_resistance_subtracts(battle):
    pool = load_pool()
    grass = Card(name="Grassmon", category=Category.POKEMON, stage=Stage.BASIC, hp=200, types=("Grass",))
    weak = Card(name="Weakmon", category=Category.POKEMON, stage=Stage.BASIC, hp=200, weakness="Grass")
    tough = Card(name="Toughmon", category=Category.POKEMON, stage=Stage.BASIC, hp=200,
                 resistance="Grass", resistance_value=30)
    attacker = Spot(stack=[grass], turn_played=0)
    assert battle.final_damage(100, attacker, Spot(stack=[weak], turn_played=0)) == 200
    assert battle.final_damage(100, attacker, Spot(stack=[tough], turn_played=0)) == 70
    assert pool.lookup("Charizard ex", "OBF", "125").weakness == "Grass"


def test_knockout_awards_the_printed_prize_count(battle):
    battle.setup()
    target = battle.sides[1].active
    target.damage = target.max_hp
    before = battle.sides[0].prizes_taken
    battle.check_knockouts()
    assert battle.sides[0].prizes_taken == before + target.prize_value


def test_taking_the_last_prize_wins(battle):
    battle.setup()
    battle.sides[0].prizes = battle.sides[0].prizes[:1]
    battle.take_prizes(0, 1)
    assert battle.finished and battle.winner == 0 and battle.reason == "prizes"


def test_running_out_of_pokemon_loses(battle):
    battle.setup()
    side = battle.sides[1]
    side.bench.clear()
    side.active.damage = side.active.max_hp
    battle.check_knockouts()
    assert battle.finished and battle.winner == 0 and battle.reason == "bench-out"


def test_running_out_of_cards_loses(battle):
    battle.setup()
    battle.sides[0].deck.clear()
    battle.turn = 3
    battle.take_turn(0)
    assert battle.finished and battle.winner == 1 and battle.reason == "deck-out"


def test_energy_costs_are_checked_by_type(battle):
    pool = load_pool()
    fire = pool.lookup("Basic Fire Energy")
    water = pool.lookup("Basic Water Energy")
    charizard = pool.lookup("Charizard ex", "OBF", "125")
    spot = Spot(stack=[charizard], turn_played=0)
    attack = charizard.attacks[0]  # {R}{R}
    assert not battle.can_pay(spot, attack)
    spot.energy = [fire]
    assert not battle.can_pay(spot, attack)
    spot.energy = [fire, fire]
    assert battle.can_pay(spot, attack)
    spot.energy = [fire, water]
    assert not battle.can_pay(spot, attack)


def test_colorless_costs_accept_anything(battle):
    water = load_pool().lookup("Basic Water Energy")
    card = Card(name="Blob", category=Category.POKEMON, stage=Stage.BASIC, hp=100,
                attacks=(Attack(name="Tackle", cost=("Colorless", "Colorless"), damage=20),))
    spot = Spot(stack=[card], turn_played=0, energy=[water, water])
    assert battle.can_pay(spot, card.attacks[0])


def test_poison_and_burn_damage_between_turns(battle):
    battle.setup()
    spot = battle.sides[1].active
    spot.poisoned = True
    spot.burned = True
    before = spot.damage
    battle.between_turns(0)
    assert spot.damage >= before + 30


def test_sleep_and_paralysis_stop_an_attack(battle):
    battle.setup()
    battle.turn = 4
    battle.sides[0].active.condition = ASLEEP
    assert not battle.can_attack(0)
    battle.sides[0].active.condition = PARALYZED
    assert not battle.can_attack(0)
    battle.sides[0].active.condition = None
    assert battle.can_attack(0)


def test_conditions_clear_when_the_pokemon_is_switched(battle):
    battle.setup()
    side = battle.sides[0]
    if not side.bench:
        side.bench_pokemon(load_pool().lookup("Charmander", "PAF", "7"), 0)
    side.active.condition = ASLEEP
    side.active.poisoned = True
    old = side.active
    battle.switch_active(0, side.bench[0])
    assert old.condition is None and not old.poisoned
    assert side.active is not old


def test_scaling_attacks_discard_exactly_what_they_need(battle):
    battle.setup()
    pool = load_pool()
    bolt = pool.lookup("Raging Bolt ex", "TEF", "123")
    lightning = pool.lookup("Basic Lightning Energy")
    spot = Spot(stack=[bolt], turn_played=0, energy=[lightning] * 4)
    battle.sides[0].active = spot
    target = battle.sides[1].active
    target.damage = target.max_hp - 140  # two discards are enough
    attack = next(a for a in bolt.attacks if a.name == "Bellowing Thunder")
    plan = battle.attack_plan(0, attack, spot, target)
    assert plan["discard_k"] == 2
    assert battle.attack_damage(0, attack, spot, target, plan) == 140


def test_spread_damage_takes_knockouts_first(battle):
    battle.setup()
    side = battle.sides[1]
    if not side.bench:
        side.bench_pokemon(load_pool().lookup("Dreepy", "ASH", "158") or side.active.card, 1)
    weak = side.bench[0]
    weak.damage = weak.max_hp - 20
    battle.spread_damage(1, 60)
    assert weak.knocked_out


def test_a_finished_game_reports_a_winner_and_a_reason():
    result = make_battle(seed=7).play()
    assert result.reason in ("prizes", "deck-out", "bench-out", "turn-limit")
    assert result.winner in (0, 1, None)
    assert result.turns > 0
