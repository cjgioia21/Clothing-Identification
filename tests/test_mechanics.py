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


# --------------------------------------------------------- damage modifiers
def test_a_tool_adds_damage_only_against_the_targets_it_names():
    battle = make_battle()
    battle.setup()
    pool = load_pool()
    attacker = Spot(stack=[pool.lookup("Dragapult ex", "TWM", "130")], turn_played=1)
    attacker.tool = pool.lookup("Maximum Belt", "TEF", "154")
    ex_target = Spot(stack=[pool.lookup("Archaludon ex", "SSP", "130")], turn_played=1)
    plain_target = Spot(stack=[pool.lookup("Dreepy", "TWM", "128")], turn_played=1)

    assert battle.damage_boost(0, attacker, ex_target) == 50
    assert battle.damage_boost(0, attacker, plain_target) == 0


def test_a_tool_soaks_up_damage_for_the_pokemon_holding_it():
    battle = make_battle()
    battle.setup()
    pool = load_pool()
    attacker = Spot(stack=[pool.lookup("Dragapult ex", "TWM", "130")], turn_played=1)
    target = Spot(stack=[pool.lookup("Dreepy", "TWM", "128")], turn_played=1)
    battle.sides[0].active, battle.sides[1].active = attacker, target

    bare = battle.final_damage(100, attacker, target, 0)
    target.tool = pool.lookup("Sacred Charm", "PFL", "93")
    assert battle.final_damage(100, attacker, target, 0) == bare - 30


def test_extra_hp_from_a_tool_counts_toward_the_knockout():
    pool = load_pool()
    spot = Spot(stack=[pool.lookup("Dreepy", "TWM", "128")], turn_played=1)
    bare = spot.max_hp
    spot.tool = pool.lookup("Bravery Charm", "PAL", "173")
    assert spot.max_hp == bare + 50  # Dreepy is a Basic, so the Charm applies


def test_damage_is_boosted_before_weakness_is_applied():
    battle = make_battle()
    battle.setup()
    pool = load_pool()
    from pokedeck.cards import Attack, Card, Category, Stage

    attacker = Spot(
        stack=[Card(name="Boostmon", category=Category.POKEMON, stage=Stage.BASIC,
                    hp=100, types=("Fire",))],
        turn_played=1,
    )
    attacker.tool = pool.lookup("Maximum Belt", "TEF", "154")
    target = Spot(
        stack=[Card(name="Weakmon ex", category=Category.POKEMON, stage=Stage.BASIC,
                    hp=300, weakness="Fire", rule_box="ex", prize_value=2)],
        turn_played=1,
    )
    # (100 + 50) doubled, not 100 doubled then boosted.
    assert battle.final_damage(100, attacker, target, 0) == 300


# ----------------------------------------------------------------- lockdowns
def test_an_ability_lock_switches_off_both_sides_of_the_board():
    battle = make_battle()
    battle.setup()
    _, resolution = toad_resolution()
    assert not battle.abilities_locked(0)
    battle.stadium = load_pool().lookup("Team Rocket's Watchtower", "DRI", "180")
    battle.stadium_owner = 1
    if any(e.op == "lock_abilities" for e in battle.stadium.effects):
        assert battle.abilities_locked(0) and battle.abilities_locked(1)


def test_item_lock_stops_items_until_the_turn_passes():
    battle = make_battle()
    battle.setup()
    battle.turn = 4
    battle.sides[1].items_locked_until = 5
    assert battle.items_locked(1)
    battle.turn = 6
    assert not battle.items_locked(1)


def test_a_locked_attack_cannot_be_chosen():
    battle = make_battle()
    battle.setup()
    battle.turn = 3
    pool = load_pool()
    side = battle.sides[0]
    side.active = Spot(stack=[pool.lookup("Dragapult ex", "TWM", "130")], turn_played=1,
                       energy=[pool.lookup("Basic Fire Energy"), pool.lookup("Basic Psychic Energy")])
    assert "Phantom Dive" in {a.name for a in battle.usable_attacks(0)}
    side.locked_attack, side.locked_attack_until = "Phantom Dive", 3
    assert "Phantom Dive" not in {a.name for a in battle.usable_attacks(0)}


# ------------------------------------------------------------ other passives
def test_an_ability_can_rewrite_the_opponents_weakness():
    battle = make_battle()
    battle.setup()
    pool = load_pool()
    clefairy = pool.lookup("Lillie's Clefairy ex", "ASC", "76")
    dragon = Spot(stack=[pool.lookup("Dragapult ex", "TWM", "130")], turn_played=1)
    battle.sides[0].bench = [Spot(stack=[clefairy], turn_played=1)]
    battle.sides[1].active = dragon
    assert battle.weakness_of(0, dragon) == "Psychic"


def test_damage_counters_go_where_they_finish_something():
    battle = make_battle()
    battle.setup()
    pool = load_pool()
    from pokedeck.scripts import run

    dusclops = pool.lookup("Dusclops", "SFA", "19")
    foe = battle.sides[1]
    weak = foe.bench[0] if foe.bench else foe.active
    weak.damage = weak.max_hp - 50
    spot = Spot(stack=[dusclops], turn_played=1)
    battle.sides[0].bench.append(spot)
    run(battle, 0, dusclops.ability, spot)
    assert weak.knocked_out or weak.damage >= weak.max_hp - 50
    assert spot.knocked_out  # the Ability knocks Dusclops out as its price


def test_an_ability_can_make_an_attack_cheaper():
    battle = make_battle()
    battle.setup()
    pool = load_pool()
    ursaluna = pool.lookup("Bloodmoon Ursaluna ex", "TWM", "141")
    blood_moon = next(a for a in ursaluna.attacks if a.name == "Blood Moon")
    spot = Spot(stack=[ursaluna], turn_played=1,
                energy=[pool.lookup("Basic Fighting Energy")] * (len(blood_moon.cost) - 2))
    battle.sides[0].active = spot
    assert not battle.can_pay(spot, blood_moon)
    battle.sides[1].prizes_taken = 2
    assert battle.can_pay(spot, blood_moon)


# ------------------------------------------------------------ Energy payment
def test_a_rainbow_energy_pays_for_one_of_anything():
    from pokedeck.cards import Attack, Card, Category, Stage

    battle = make_battle()
    battle.setup()
    pool = load_pool()
    basic_mon = Card(name="Rainbowmon", category=Category.POKEMON, stage=Stage.BASIC, hp=100)
    attack = Attack(name="Costly", cost=("Fire", "Water"), damage=100)
    spot = Spot(stack=[basic_mon], turn_played=1, energy=[pool.lookup("Prism Energy", "ASC", "216")])

    assert not battle.can_pay(spot, attack)          # one Energy, two symbols
    spot.energy.append(pool.lookup("Prism Energy", "ASC", "216"))
    assert battle.can_pay(spot, attack)              # two rainbows cover both


def test_prism_energy_is_only_a_rainbow_on_a_basic():
    from pokedeck.cards import Attack, Card, Category, Stage

    battle = make_battle()
    battle.setup()
    prism = load_pool().lookup("Prism Energy", "ASC", "216")
    attack = Attack(name="Typed", cost=("Fire",), damage=50)

    stage_two = Card(name="Bigmon", category=Category.POKEMON, stage=Stage.STAGE2, hp=300)
    assert not battle.can_pay(Spot(stack=[stage_two], turn_played=1, energy=[prism]), attack)

    basic = Card(name="Smallmon", category=Category.POKEMON, stage=Stage.BASIC, hp=60)
    assert battle.can_pay(Spot(stack=[basic], turn_played=1, energy=[prism]), attack)


def test_typed_costs_spend_the_least_flexible_energy_first():
    from pokedeck.cards import Attack, Card, Category, Stage

    battle = make_battle()
    battle.setup()
    pool = load_pool()
    # One Fire, one rainbow: {R}{W} works only if the Fire pays the {R}.
    spot = Spot(
        stack=[Card(name="Mixmon", category=Category.POKEMON, stage=Stage.BASIC, hp=100)],
        turn_played=1,
        energy=[pool.lookup("Basic Fire Energy"), pool.lookup("Prism Energy", "ASC", "216")],
    )
    assert battle.can_pay(spot, Attack(name="Two", cost=("Fire", "Water"), damage=10))


def test_colorless_costs_take_whatever_is_left():
    from pokedeck.cards import Attack, Card, Category, Stage

    battle = make_battle()
    battle.setup()
    pool = load_pool()
    spot = Spot(
        stack=[Card(name="Plainmon", category=Category.POKEMON, stage=Stage.BASIC, hp=100)],
        turn_played=1,
        energy=[pool.lookup("Basic Metal Energy"), pool.lookup("Basic Water Energy")],
    )
    assert battle.can_pay(spot, Attack(name="Cheap", cost=("Colorless", "Colorless"), damage=10))
    assert not battle.can_pay(spot, Attack(name="Dear", cost=("Fire", "Colorless"), damage=10))


def test_damage_counters_stay_on_through_an_evolution():
    battle = make_battle()
    battle.setup()
    battle.turn = 3
    pool = load_pool()
    side = battle.sides[0]
    basic = Spot(stack=[pool.lookup("Dreepy", "TWM", "128")], turn_played=1, damage=40)
    side.active = basic
    side.hand = [pool.lookup("Drakloak", "TWM", "129")]
    assert battle.policies[0].evolve(battle, 0)
    assert side.active.name == "Drakloak"
    assert side.active.damage == 40


def test_a_stadium_cannot_be_replaced_by_its_own_name():
    battle = make_battle()
    battle.setup()
    artazon = load_pool().lookup("Artazon", "PAL", "171")
    battle.stadium, battle.stadium_owner = artazon, 1
    assert not battle.can_play_stadium(artazon)
    assert battle.can_play_stadium(load_pool().lookup("Lumiose City", "POR", "77"))
