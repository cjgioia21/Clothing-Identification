import random

from pokedeck.battle import Battle, BattleDeck, Spot
from pokedeck.cards import Attack, Card, Category, Stage
from pokedeck.decklist import parse
from pokedeck.knowledge import resolve
from pokedeck.policy import Policy
from pokedeck.pool import load_pool

from .conftest import DRAGAPULT
from .test_battle import make_battle


def test_energy_stacks_on_one_attacker_instead_of_spreading():
    battle = make_battle(seed=2)
    battle.setup()
    policy = battle.policies[0]
    pool = load_pool()
    bolt = pool.lookup("Raging Bolt ex", "TEF", "123")
    lightning = pool.lookup("Basic Lightning Energy")
    side = battle.sides[0]
    side.active = Spot(stack=[bolt], turn_played=0, energy=[lightning])
    side.bench = [Spot(stack=[bolt], turn_played=0)]
    assert policy.energy_target(battle, 0) is side.active


def test_energy_fit_prefers_the_type_the_attack_still_needs():
    battle = make_battle()
    battle.setup()
    pool = load_pool()
    bolt = pool.lookup("Raging Bolt ex", "TEF", "123")
    lightning = pool.lookup("Basic Lightning Energy")
    fighting = pool.lookup("Basic Fighting Energy")
    spot = Spot(stack=[bolt], turn_played=0, energy=[lightning])
    policy = battle.policies[0]
    assert policy.energy_fit(battle, 0, fighting, spot) > policy.energy_fit(battle, 0, lightning, spot)


def test_best_attack_takes_the_knockout():
    battle = make_battle()
    battle.setup()
    pool = load_pool()
    charizard = pool.lookup("Charizard ex", "OBF", "125")
    fire = pool.lookup("Basic Fire Energy")
    battle.sides[0].active = Spot(stack=[charizard], turn_played=0, energy=[fire, fire])
    target = battle.sides[1].active
    target.damage = target.max_hp - 10
    attack, damage = battle.policies[0].best_attack(battle, 0)
    assert attack.name == "Burning Darkness"
    assert damage >= target.remaining_hp


def test_a_blank_attack_is_skipped_when_it_only_costs_resources():
    battle = make_battle()
    battle.setup()
    policy = battle.policies[0]
    blank = Attack(name="Nothing", cost=("Colorless",), damage=0)
    card = Card(name="Blank", category=Category.POKEMON, stage=Stage.BASIC, hp=100, attacks=(blank,))
    energy = load_pool().lookup("Basic Fire Energy")
    battle.sides[0].active = Spot(stack=[card], turn_played=0, energy=[energy])
    before = battle.sides[1].active.damage
    policy.attack(battle, 0)
    assert battle.sides[1].active.damage == before


def test_draw_is_refused_when_the_deck_is_nearly_empty():
    battle = make_battle()
    battle.setup()
    policy = battle.policies[0]
    battle.sides[0].hand = battle.sides[0].hand[:2]
    assert policy.wants_draw(battle, 0, 5)
    battle.sides[0].deck = battle.sides[0].deck[:4]
    assert not policy.wants_draw(battle, 0, 5)


def test_draw_is_refused_with_a_full_hand():
    battle = make_battle()
    battle.setup()
    policy = battle.policies[0]
    battle.sides[0].hand = battle.sides[0].hand + battle.sides[0].deck[:6]
    assert not policy.wants_draw(battle, 0, 7)


def test_gust_target_prefers_a_knockout():
    battle = make_battle()
    battle.setup()
    foe = battle.sides[1]
    while len(foe.bench) < 2:
        foe.bench_pokemon(load_pool().lookup("Ralts", "SVI", "84"), 0)
    fragile = foe.bench[0]
    fragile.damage = fragile.max_hp - 10
    pool = load_pool()
    battle.sides[0].active = Spot(
        stack=[pool.lookup("Charizard ex", "OBF", "125")],
        turn_played=0,
        energy=[pool.lookup("Basic Fire Energy")] * 2,
    )
    assert battle.policies[0].gust_target(battle, 0) is fragile


def test_promotion_prefers_a_pokemon_that_can_attack():
    battle = make_battle()
    battle.setup()
    pool = load_pool()
    side = battle.sides[0]
    ready = Spot(stack=[pool.lookup("Charizard ex", "OBF", "125")], turn_played=0,
                 energy=[pool.lookup("Basic Fire Energy")] * 2)
    side.bench = [Spot(stack=[pool.lookup("Ralts", "SVI", "84")], turn_played=0), ready]
    assert battle.policies[0].choose_promotion(battle, 0) is ready


def test_rare_candy_is_valued_when_a_stage_two_can_use_it():
    deck = parse(DRAGAPULT, name="A")
    resolution = resolve(deck)
    battle = make_battle(seed=5)
    battle.setup()
    battle.turn = 2
    side = battle.sides[0]
    pool = load_pool()
    side.active = Spot(stack=[resolution.get("Dreepy")], turn_played=1)
    side.hand = [resolution.get("Dragapult ex"), resolution.get("Rare Candy")]
    policy = battle.policies[0]
    assert policy.card_value(battle, 0, resolution.get("Rare Candy")) == 9


def test_both_sides_use_the_same_policy_and_games_are_reproducible():
    first = make_battle(seed=11).play()
    second = make_battle(seed=11).play()
    assert (first.winner, first.turns, first.prizes_taken) == (second.winner, second.turns, second.prizes_taken)
