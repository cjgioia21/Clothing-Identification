"""Rules that only some decks need: Fossils, Stadiums, copied attacks, Round."""

import random

from pokedeck.battle import Battle, Spot
from pokedeck.cards import Category, Stage
from pokedeck.decklist import parse
from pokedeck.knowledge import resolve
from pokedeck.pool import load_pool

from .test_battle import make_battle

TOADS = """
Pokémon: 9
4 Tympole BLK 19
2 Palpitoad BLK 20
1 Seismitoad 30C 84
1 Tirtouga BLK 22
1 Mew ex 30C 152

Trainer: 4
2 Antique Cover Fossil SCR 129
1 Fossil Quarry PBL 76
1 Neutralization Zone SFA 60

Energy: 4
4 Basic Water Energy
"""


def toad_resolution():
    deck = parse(TOADS, name="toads")
    return deck, resolve(deck)


def test_a_fossil_becomes_a_basic_pokemon():
    _, resolution = toad_resolution()
    fossil = resolution.get("Antique Cover Fossil")
    assert fossil.category is Category.POKEMON
    assert fossil.stage is Stage.BASIC
    assert fossil.is_basic_pokemon and fossil.fossil
    assert fossil.hp == 60
    assert fossil.retreat > 5  # it cannot retreat


def test_a_fossil_pokemon_can_be_evolved():
    _, resolution = toad_resolution()
    assert resolution.get("Tirtouga").evolves_from == "Antique Cover Fossil"
    assert resolution.info("Antique Cover Fossil") is not None


def test_ball_searches_do_not_find_fossils():
    from pokedeck.scripts import matches

    _, resolution = toad_resolution()
    assert not matches(resolution.get("Antique Cover Fossil"), "basic_pokemon")
    assert matches(resolution.get("Antique Cover Fossil"), "fossil")
    assert matches(resolution.get("Tympole"), "basic_pokemon")


def test_round_scales_with_the_pokemon_that_share_it():
    _, resolution = toad_resolution()
    battle = make_battle()
    battle.setup()
    tympole = resolution.get("Tympole")
    round_attack = next(a for a in tympole.attacks if a.name == "Round")
    side = battle.sides[0]
    side.active = Spot(stack=[tympole], turn_played=1)
    side.bench = []
    target = battle.sides[1].active

    assert battle.attack_damage(0, round_attack, side.active, target) == 20
    side.bench = [Spot(stack=[resolution.get("Palpitoad")], turn_played=1),
                  Spot(stack=[tympole], turn_played=1)]
    assert battle.attack_damage(0, round_attack, side.active, target) == 60


def test_a_stadium_can_blank_rule_box_attackers():
    _, resolution = toad_resolution()
    battle = make_battle()
    battle.setup()
    pool = load_pool()
    attacker = Spot(stack=[pool.lookup("Dragapult ex", "TWM", "130")], turn_played=1)
    toad = Spot(stack=[resolution.get("Palpitoad")], turn_played=1)
    ex_target = Spot(stack=[resolution.get("Mew ex")], turn_played=1)

    assert battle.final_damage(200, attacker, toad) == 200
    battle.stadium = resolution.get("Neutralization Zone")
    battle.stadium_owner = 0
    assert battle.final_damage(200, attacker, toad) == 0
    assert battle.final_damage(200, attacker, ex_target) == 200


def test_stadium_abilities_are_once_per_player_per_turn():
    deck, resolution = toad_resolution()
    battle = make_battle()
    battle.setup()
    battle.turn = 3
    battle.stadium = resolution.get("Fossil Quarry")
    battle.stadium_owner = 0
    side = battle.sides[0]
    side.stadium_used = False
    side.deck = [resolution.get("Antique Cover Fossil")] * 3
    side.bench = []

    assert battle.stadium_ability(0) is not None
    assert battle.policies[0].use_stadium(battle, 0)
    assert len(side.bench) == 2
    assert battle.stadium_ability(0) is None  # already used this turn


def test_an_ability_can_copy_benched_attacks():
    _, resolution = toad_resolution()
    battle = make_battle()
    battle.setup()
    pool = load_pool()
    side = battle.sides[0]
    side.active = Spot(stack=[resolution.get("Mew ex")], turn_played=1,
                       energy=[pool.lookup("Basic Water Energy")] * 2)
    side.bench = [Spot(stack=[resolution.get("Tympole")], turn_played=1)]
    assert battle.copies_bench_attacks(side.active)
    assert "Round" in {a.name for a in battle.usable_attacks(0)}

    side.active = Spot(stack=[resolution.get("Tympole")], turn_played=1,
                       energy=[pool.lookup("Basic Water Energy")] * 2)
    assert not battle.copies_bench_attacks(side.active)


def test_hand_disruption_trims_the_opponent():
    from pokedeck.scripts import run

    battle = make_battle()
    battle.setup()
    pool = load_pool()
    squeeze = pool.lookup("Xerosic's Machinations", "SFA", "64")
    foe = battle.sides[1]
    foe.hand = [pool.lookup("Ultra Ball")] * 6
    run(battle, 0, squeeze.effects)
    assert len(foe.hand) == 3
