"""The cards the supplied 100-deck field brought with it."""

import pytest

from pokedeck.battle import Battle, Spot
from pokedeck.cards import Attack, Card, Category, Effect, Stage, Subtype
from pokedeck.effects import compile_text
from pokedeck.policy import Policy
from pokedeck.pool import load_pool
from pokedeck.scripts import gated, run, useful

from .test_battle import make_battle
from .test_card_behaviour import ability, basic


@pytest.fixture
def battle():
    game = make_battle()
    game.setup()
    game.turn = 5
    for index in (0, 1):
        fill_bench(game, index)
    return game


def fill_bench(battle, index, count=2):
    """setup() leaves the Bench empty; most of these cards need one."""
    side = battle.sides[index]
    while len(side.bench) < count:
        spare = next((c for c in side.deck if c.is_basic_pokemon), None)
        if spare is None:
            break
        side.deck.remove(spare)
        side.bench_pokemon(spare, 1)
    for spot in side.in_play():
        spot.turn_played = 1


def stadium(battle, text, name="Somewhere"):
    card = Card(name=name, category=Category.TRAINER, subtype=Subtype.STADIUM,
                effects=tuple(compile_text(text)[0]), ability_text=text)
    battle.stadium, battle.stadium_owner = card, 0
    return card


# ------------------------------------------------------------- damage riders
@pytest.mark.parametrize("text, setup, expected", [
    ("If this Pokémon has any damage counters on it, this attack does 150 more damage.",
     lambda b: setattr(b.sides[0].active, "damage", 30), 250),
    ("If this Pokémon has any damage counters on it, this attack does 150 more damage.",
     lambda b: None, 100),
    ("If your Benched Pokémon have any damage counters on them, this attack does 110 more damage.",
     lambda b: setattr(b.sides[0].bench[0], "damage", 10), 210),
    ("If there are 3 or fewer cards in your deck, this attack does 200 more damage.",
     lambda b: b.sides[0].deck.__setitem__(slice(None), b.sides[0].deck[:2]), 300),
])
def test_conditional_damage_riders(battle, text, setup, expected):
    effects, unread = compile_text(text)
    assert not unread
    attack = Attack(name="Swing", cost=(), damage=100, effects=tuple(effects))
    setup(battle)
    spot, target = battle.sides[0].active, battle.sides[1].active
    assert battle.attack_damage(0, attack, spot, target, {}) == expected


def test_a_pokemon_that_just_switched_in_hits_harder(battle):
    effects, unread = compile_text(
        "If this Pokémon moved from your Bench to the Active Spot this turn, "
        "this attack does 170 more damage.")
    assert not unread
    attack = Attack(name="Leap", cost=(), damage=100, effects=tuple(effects))
    side = battle.sides[0]
    spot, target = side.active, battle.sides[1].active
    assert battle.attack_damage(0, attack, spot, target, {}) == 100
    battle.switch_active(0, side.bench[0])
    assert battle.attack_damage(0, attack, side.active, target, {}) == 270


# --------------------------------------------------------- outright knockouts
def test_an_attack_can_knock_out_on_a_condition_rather_than_damage(battle):
    effects, _ = compile_text(
        "If your opponent's Active Pokémon is affected by a Special Condition, "
        "it is Knocked Out.")
    target = battle.sides[1].active
    target.condition = "asleep"
    battle.apply_attack_effect(0, effects[0], battle.sides[0].active, target)
    assert target.knocked_out


def test_the_exact_counter_knockout_needs_exactly_that_many(battle):
    effects, _ = compile_text(
        "If your opponent's Active Pokémon has exactly 6 damage counters on it, "
        "that Pokémon is Knocked Out.")
    target = battle.sides[1].active
    target.damage = 50
    battle.apply_attack_effect(0, effects[0], battle.sides[0].active, target)
    assert not target.knocked_out
    target.damage = 60
    battle.apply_attack_effect(0, effects[0], battle.sides[0].active, target)
    assert target.knocked_out


# ------------------------------------------------------------- can it attack?
def test_a_pokemon_that_needs_a_full_team_waits_for_one(battle):
    card = basic("Bossmon", ability=ability(
        "This Pokémon can't attack unless you have 4 or more Team Rocket's Pokémon in play."))
    side = battle.sides[0]
    side.active = Spot(stack=[card], turn_played=0)
    side.bench = [Spot(stack=[basic("Team Rocket's Grunt")], turn_played=0)]
    assert not battle.can_attack(0)
    side.bench += [Spot(stack=[basic(f"Team Rocket's Mook {n}")], turn_played=0)
                   for n in range(3)]
    assert battle.can_attack(0)


# ----------------------------------------------------------------- the Tools
def test_a_stadium_can_switch_every_tool_off(battle):
    pool = load_pool()
    charm = pool.lookup("Bravery Charm", "PAL", "173")
    spot = Spot(stack=[basic("Smallmon", hp=60)], turn_played=0, tool=charm)
    battle.sides[0].active = spot
    assert spot.max_hp == 60 + charm.effects[0].n
    assert battle.tool_of(spot) is charm

    stadium(battle, "Pokémon Tools attached to each Pokémon (both yours and your "
                    "opponent's) have no effect.", name="Jamming Tower")
    assert battle.tools_locked()
    assert battle.tool_of(spot) is None
    assert battle.retreat_cost(0, spot) == spot.card.retreat


def test_a_prize_shield_tool_costs_the_attacker_a_prize(battle):
    pearl = Card(name="Pearl", category=Category.TRAINER, subtype=Subtype.TOOL,
                 effects=tuple(compile_text(
                     "If the Lillie's Pokémon this card is attached to is Knocked Out by "
                     "damage from an attack from your opponent's Pokémon, that player "
                     "takes 1 fewer Prize card.")[0]))
    assert [e.op for e in pearl.effects] == ["prize_reduction"]
    side = battle.sides[1]
    side.active = Spot(stack=[basic("Bigmon", rule_box="ex", prize_value=2)],
                       turn_played=0, tool=pearl)
    side.active.damage = side.active.max_hp
    before = battle.sides[0].prizes_taken
    battle.check_knockouts()
    assert battle.sides[0].prizes_taken == before + 1   # two, less the shield


# --------------------------------------------------------------- the Stadiums
def test_benching_under_risky_ruins_costs_damage(battle):
    stadium(battle, "Whenever any player puts a Basic non-{D} Pokémon onto their Bench "
                    "during their turn, place 2 damage counters on that Pokémon.",
            name="Risky Ruins")
    side = battle.sides[0]
    spot = side.bench_pokemon(basic("Newmon"), battle.turn)
    Policy().on_bench(battle, 0, spot)
    assert spot.damage == 20


def test_a_stadium_can_let_a_pokemon_evolve_the_turn_it_arrives(battle):
    spot = Spot(stack=[basic("Sprout")], turn_played=battle.turn)
    battle.sides[0].active = spot
    assert not battle.can_evolve(0, spot)
    stadium(battle, "Each player's {G} Pokémon can evolve into {G} Pokémon during the "
                    "turn they play those Pokémon, except during their first turn.",
            name="Forest of Vitality")
    assert battle.can_evolve(0, spot)


def test_energy_on_board_can_make_a_pokemon_condition_proof(battle):
    stadium(battle, "Each Pokémon that has any Energy attached (both yours and your "
                    "opponent's) recovers from all Special Conditions and can't be "
                    "affected by any Special Conditions.", name="Festival Grounds")
    target = battle.sides[1].active
    asleep = Effect(op="status", filter="asleep")

    target.energy.clear()
    battle.apply_attack_effect(0, asleep, battle.sides[0].active, target)
    assert target.condition == "asleep"        # nothing attached, nothing to protect it

    target.condition = None
    target.energy.append(load_pool().lookup("Basic Fire Energy", "SVE", "2"))
    battle.apply_attack_effect(0, asleep, battle.sides[0].active, target)
    assert target.condition is None


def test_a_cage_keeps_damage_counters_off_the_bench(battle):
    stadium(battle, "Prevent all damage counters from being placed on Benched Pokémon "
                    "(both yours and your opponent's) by effects of attacks and "
                    "Abilities from the opponent's Pokémon.", name="Battle Cage")
    benched = battle.sides[1].bench[0]
    assert battle.counters_shielded(benched, 1)
    assert not battle.counters_shielded(battle.sides[1].active, 1)


# ------------------------------------------------------- borrowing an attack
def test_a_copied_attack_can_be_restricted_to_one_family(battle):
    borrower = basic("N's Zoroark ex", ability=ability(
        "Choose 1 of your Benched N's Pokémon's attacks and use it as this attack."))
    friend = basic("N's Friend", attacks=(Attack(name="Together", cost=(), damage=90),))
    stranger = basic("Someone Else", attacks=(Attack(name="Alone", cost=(), damage=90),))
    side = battle.sides[0]
    side.active = Spot(stack=[borrower], turn_played=0)
    side.bench = [Spot(stack=[friend], turn_played=0), Spot(stack=[stranger], turn_played=0)]
    assert battle.copies_bench_attacks(side.active) == "n's"
    names = {a.name for a in battle.usable_attacks(0)}
    assert "Together" in names and "Alone" not in names


# ------------------------------------------------------------ Trainer timing
def test_a_late_game_trainer_waits_for_the_prize_count(battle):
    script = compile_text(
        "You can use this card only if your opponent has 3 or fewer Prize cards "
        "remaining. Each player shuffles their hand into their deck.")[0]
    assert gated(battle, 0, script, None)
    del battle.sides[1].prizes[:3]
    assert not gated(battle, 0, script, None)


def test_a_trainer_banned_on_turn_one_stays_in_hand(battle):
    script = compile_text("You can't use this card during your first turn. Draw 3 cards.")[0]
    battle.turn = 1
    assert gated(battle, 0, script, None)
    battle.turn = 4
    assert not gated(battle, 0, script, None)


# ------------------------------------------------------------- board recovery
def test_a_pokemon_can_pick_itself_up_off_the_board(battle):
    effects, unread = compile_text("Put this Pokémon and all attached cards into your hand.")
    assert not unread
    side = battle.sides[0]
    spot = side.bench[0]
    card, extra = spot.stack[0], load_pool().lookup("Basic Fire Energy", "SVE", "2")
    spot.energy.append(extra)
    run(battle, 0, effects, spot)
    assert spot not in side.bench
    assert card in side.hand and extra in side.hand
