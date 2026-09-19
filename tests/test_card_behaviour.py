"""Cards whose printed text the audit found the engine was skipping."""

import random

import pytest

from pokedeck.battle import Battle, Spot
from pokedeck.cards import Attack, Card, Category, Effect, Stage, Subtype
from pokedeck.effects import compile_text
from pokedeck.policy import Policy
from pokedeck.pool import load_pool

from .test_battle import make_battle


def ability(text: str) -> tuple[Effect, ...]:
    return tuple(compile_text(text)[0])


def basic(name="Rock", **kwargs) -> Card:
    fields = dict(name=name, category=Category.POKEMON, stage=Stage.BASIC, hp=100)
    fields.update(kwargs)
    return Card(**fields)


@pytest.fixture
def battle():
    game = make_battle()
    game.setup()
    game.turn = 5
    return game


# --------------------------------------------------------------- Ignition Energy
def test_ignition_energy_is_one_on_a_basic_and_three_on_an_evolution():
    pool = load_pool()
    ignition, _ = pool.lookup_print("Ignition Energy", "PFL", "124")
    assert ignition.energy_bonus_if == "evolution"

    rookie = Spot(stack=[basic()], turn_played=0, energy=[ignition])
    grown = Spot(stack=[basic(stage=Stage.STAGE1)], turn_played=0, energy=[ignition])
    assert len(rookie.energy_units()) == 1
    assert len(grown.energy_units()) == 3


def test_ignition_energy_is_discarded_when_the_turn_ends(battle):
    pool = load_pool()
    ignition, _ = pool.lookup_print("Ignition Energy", "PFL", "124")
    side = battle.sides[0]
    side.active.energy.append(ignition)
    battle.discard_spent_energy(0)
    assert ignition not in side.active.energy
    assert ignition in side.discard


# ------------------------------------------------------------------ Quaking Fist
def test_quaking_fist_taxes_every_trainer_the_opponent_plays():
    effects, unread = compile_text(
        "During your opponent's next turn, whenever they try to use a Trainer card "
        "from their hand, they flip a coin. If tails, your opponent discards that "
        "Trainer card instead of using it."
    )
    assert not unread
    assert [e.op for e in effects] == ["tax_trainers"]


def test_a_taxed_trainer_is_discarded_instead_of_used(battle):
    side = battle.sides[1]
    side.trainer_tax_until = battle.turn
    side.trainer_tax = 100          # every flip comes down tails
    assert battle.trainer_taxed(1)
    side.trainer_tax = 0
    assert not battle.trainer_taxed(1)


def test_the_tax_expires_with_the_turn(battle):
    side = battle.sides[1]
    side.trainer_tax_until = battle.turn - 1
    side.trainer_tax = 100
    assert not battle.trainer_taxed(1)


def test_a_taxed_supporter_still_costs_the_supporter_for_the_turn(battle):
    pool = load_pool()
    side = battle.sides[0]
    side.hand = [pool.lookup("Professor's Research", "SVI", "189")]
    side.trainer_tax_until = battle.turn
    side.trainer_tax = 100
    before = len(side.hand) + len(side.deck)
    assert Policy().play_supporter(battle, 0)
    assert side.supporter_used
    assert len(side.deck) + len(side.hand) == before - 1   # drawn nothing, lost the card
    assert side.discard[-1].name == "Professor's Research"


# ------------------------------------------------------------------ Born to Slack
def test_a_pokemon_that_needs_a_rule_box_opponent_cannot_attack_a_plain_board(battle):
    slacker = basic("Slackmon", ability=ability(
        "If your opponent has no Pokémon ex or Pokémon V in play, this Pokémon can't attack."))
    battle.sides[0].active = Spot(stack=[slacker], turn_played=0)
    battle.sides[1].active = Spot(stack=[basic("Plainmon")], turn_played=0)
    battle.sides[1].bench = []
    assert not battle.can_attack(0)

    battle.sides[1].active = Spot(stack=[basic("Bigmon", rule_box="ex")], turn_played=0)
    assert battle.can_attack(0)


# ----------------------------------------------------------------- Fighting Roar
def test_fighting_roar_lets_a_pokemon_evolve_the_turn_it_is_played(battle):
    roarer = basic("Roarmon", ability=ability(
        "If your opponent's Active Pokémon is a Pokémon ex, this Pokémon can evolve "
        "during your first turn or the turn you play it."))
    spot = Spot(stack=[roarer], turn_played=battle.turn)
    battle.sides[0].active = spot

    battle.sides[1].active = Spot(stack=[basic("Plainmon")], turn_played=0)
    assert not battle.can_evolve(0, spot)

    battle.sides[1].active = Spot(stack=[basic("Bigmon", rule_box="ex")], turn_played=0)
    assert battle.can_evolve(0, spot)


def test_evolution_still_waits_a_turn_without_that_ability(battle):
    spot = Spot(stack=[basic("Plainmon")], turn_played=battle.turn)
    assert not battle.can_evolve(0, spot)
    spot.turn_played = battle.turn - 1
    assert battle.can_evolve(0, spot)


# --------------------------------------------------------------- damage immunity
def test_an_ability_can_blank_attacks_from_one_kind_of_pokemon(battle):
    shielded = basic("Shieldmon", ability=(Effect(op="prevent_damage", filter="fire"),))
    target = Spot(stack=[shielded], turn_played=0)
    flame = Spot(stack=[basic("Flamemon", types=("Fire",))], turn_played=0)
    leaf = Spot(stack=[basic("Leafmon", types=("Grass",))], turn_played=0)
    assert battle.final_damage(100, flame, target, index=1) == 0
    assert battle.final_damage(100, leaf, target, index=1) == 100


def test_a_tera_shield_matches_nothing_because_the_pool_has_no_tera_flag(battle):
    """Honest gap: TCGdex carries no Tera marking, so the shield never fires."""
    shielded = basic("Milomon", ability=(Effect(op="prevent_damage", filter="tera"),))
    target = Spot(stack=[shielded], turn_played=0)
    attacker = Spot(stack=[basic("Anymon", types=("Water",))], turn_played=0)
    assert battle.final_damage(100, attacker, target, index=1) == 100


# ------------------------------------------------------------------- Piercing Gaze
def test_piercing_gaze_takes_the_card_the_opponent_would_miss_most(battle):
    pool = load_pool()
    foe = battle.sides[1]
    hand = [
        pool.lookup("Nest Ball", "SVI", "181"),
        pool.lookup("Professor's Research", "SVI", "189"),
    ]
    foe.hand = list(hand)
    policy = battle.policies[1]
    best = max(hand, key=lambda c: policy.card_value(battle, 1, c))

    from pokedeck.scripts import run
    run(battle, 0, [Effect(op="opponent_discard_filter", n=1, filter="any")])
    assert len(foe.hand) == 1
    assert foe.discard[-1].name == best.name


# ------------------------------------------------------- abilities on arrival
def test_an_ability_works_the_turn_the_pokemon_comes_into_play(battle):
    drawer = basic("Drawmon", ability=ability("Draw 2 cards."), ability_trigger="turn")
    side = battle.sides[0]
    side.hand = []
    spot = side.bench_pokemon(drawer, battle.turn)
    assert spot.turn_played == battle.turn
    assert Policy().use_abilities(battle, 0)
    assert len(side.hand) == 2


def test_but_only_once_a_turn(battle):
    drawer = basic("Drawmon", ability=ability("Draw 2 cards."), ability_trigger="turn")
    side = battle.sides[0]
    side.hand = []
    side.bench_pokemon(drawer, battle.turn)
    policy = Policy()
    assert policy.use_abilities(battle, 0)
    side.hand = []
    assert not policy.use_abilities(battle, 0)


# ------------------------------------------------------------------ free switches
def test_a_free_switch_is_refused_when_the_active_is_the_better_attacker(battle):
    hitter = basic("Hitmon", attacks=(Attack(name="Smash", cost=(), damage=100),))
    weakling = basic("Weakmon", attacks=(Attack(name="Tap", cost=(), damage=10),))
    side = battle.sides[0]
    side.active = Spot(stack=[hitter], turn_played=0)
    side.bench = [Spot(stack=[weakling], turn_played=0)]
    assert not Policy().wants_switch(battle, 0)

    side.active, side.bench[0] = side.bench[0], side.active
    assert Policy().wants_switch(battle, 0)


def test_a_free_switch_is_taken_to_dodge_a_knockout(battle):
    frail = basic("Frailmon", hp=60, attacks=(Attack(name="Tap", cost=(), damage=10),))
    sturdy = basic("Sturdymon", hp=300, attacks=(Attack(name="Tap", cost=(), damage=10),))
    battle.sides[0].active = Spot(stack=[frail], turn_played=0)
    battle.sides[0].bench = [Spot(stack=[sturdy], turn_played=0)]
    battle.sides[1].active = Spot(
        stack=[basic("Bigmon", attacks=(Attack(name="Crush", cost=(), damage=200),))],
        turn_played=0,
    )
    assert Policy().wants_switch(battle, 0)


# --------------------------------------------- the generic text the pool is full of
def test_flip_until_tails_keeps_flipping(battle):
    effects, unread = compile_text(
        "Flip a coin until you get tails. This attack does 20 more damage for each heads.")
    assert not unread
    assert {e.op for e in effects} == {"coins", "bonus_per"}
    flips = {battle._flip_coins(Effect(op="coins", filter="until_tails")) for _ in range(40)}
    assert len(flips) > 1 and min(flips) == 0


def test_milling_moves_cards_off_the_opponents_deck(battle):
    from pokedeck.scripts import run
    foe = battle.sides[1]
    top = list(foe.deck[:2])
    run(battle, 0, [Effect(op="mill", n=2)])
    assert foe.discard[-2:] == top
    assert foe.deck[:2] != top


def test_ignoring_defences_walks_through_a_shield(battle):
    target = Spot(stack=[basic("Wallmon")], turn_played=0, shield=200, shield_until=battle.turn)
    attacker = Spot(stack=[basic("Hitmon")], turn_played=0)
    assert battle.final_damage(150, attacker, target, index=0) == 0
    assert battle.final_damage(150, attacker, target, index=0, ignore_defences=True) == 150


def test_stripping_tools_before_damage(battle):
    pool = load_pool()
    tool = pool.lookup("Bravery Charm", "PAL", "173")
    target = battle.sides[1].active
    target.tool = tool
    battle._strip(0, target, "tool")
    assert target.tool is None and tool in battle.sides[1].discard


def test_a_stamp_resets_both_hands(battle):
    from pokedeck.scripts import run
    mine, foe = battle.sides
    mine.hand = mine.hand[:2]
    foe.hand = foe.hand[:6]
    run(battle, 0, [Effect(op="stamp", n=5, dest="2")])
    assert len(mine.hand) == 5
    assert len(foe.hand) == 2


def test_a_revenge_supporter_needs_a_knockout_first(battle):
    from pokedeck.scripts import gated
    script = [Effect(op="requires_knockout"), Effect(op="draw", n=5)]
    battle.sides[0].lost_on_turn = -1
    assert gated(battle, 0, script, None)
    battle.sides[0].lost_on_turn = battle.turn - 1
    assert not gated(battle, 0, script, None)


def test_thorns_poison_whatever_attacked(battle):
    thorny = basic("Thornmon", ability=(Effect(op="retaliate_status", filter="poisoned"),))
    target = Spot(stack=[thorny], turn_played=0)
    attacker = Spot(stack=[basic("Hitmon")], turn_played=0)
    battle._retaliate(0, attacker, target)
    assert attacker.poisoned


def test_your_turn_ends_stops_the_rest_of_the_turn(battle):
    from pokedeck.scripts import run
    run(battle, 0, [Effect(op="end_turn")])
    assert battle.sides[0].turn_over
    battle.sides[0].hand = list(battle.sides[0].deck[:5])
    before = len(battle.sides[0].hand)
    Policy().play_turn(battle, 0)
    assert len(battle.sides[0].hand) == before   # nothing was played
