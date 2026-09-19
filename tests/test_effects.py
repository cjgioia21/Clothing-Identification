from pokedeck.effects import compile_ability, compile_attack, compile_text, parse_damage
from pokedeck.pool import load_pool


def test_parse_damage_handles_printed_forms():
    assert parse_damage("180+") == (180, "+")
    assert parse_damage("30×") == (30, "x")
    assert parse_damage("120") == (120, "")
    assert parse_damage(None) == (0, "")


def test_prize_scaling_attack():
    attack = compile_attack({
        "name": "Burning Darkness",
        "cost": ["Fire", "Fire"],
        "damage": "180+",
        "effect": "This attack does 30 more damage for each Prize card your opponent has taken.",
    })
    assert attack.damage == 180
    assert attack.scripted
    assert attack.effects[0].op == "bonus_per"
    assert attack.effects[0].filter == "opponent_prizes_taken"


def test_discard_scaling_attack():
    attack = compile_attack({
        "name": "Bellowing Thunder",
        "cost": ["Lightning", "Fighting"],
        "damage": "70×",
        "effect": "You may discard any amount of Basic Energy from your Pokémon. "
                  "This attack does 70 damage for each card you discarded in this way.",
    })
    assert attack.scripted
    assert [e.op for e in attack.effects] == ["discard_energy_scale", "discard_energy_scale"]
    assert max(e.n for e in attack.effects) == 70


def test_damage_counter_spread():
    attack = compile_attack({
        "name": "Phantom Dive",
        "damage": "200",
        "effect": "Put 6 damage counters on your opponent's Benched Pokémon in any way you like.",
    })
    assert attack.effects[0].op == "bench_counters"
    assert attack.effects[0].n == 60


def test_status_and_unmodelled_text():
    effects, leftover = compile_text(
        "Your opponent's Active Pokémon is now Asleep. Something unprecedented happens."
    )
    assert effects[0].op == "status" and effects[0].filter == "asleep"
    assert leftover == ["Something unprecedented happens."]


def test_unreadable_text_marks_the_attack_partial():
    attack = compile_attack({"name": "Odd", "damage": "10", "effect": "Do something inscrutable."})
    assert not attack.scripted
    assert attack.damage == 10


def test_ability_triggers():
    _, trigger, _ = compile_ability({
        "effect": "When you play this Pokémon from your hand to evolve 1 of your Pokémon during "
                  "your turn, you may search your deck for up to 3 Basic {R} Energy cards and "
                  "attach them to your Pokémon in any way you like. Then, shuffle your deck."
    })
    assert trigger == "on_evolve"

    _, bench_trigger, _ = compile_ability({
        "effect": "When you play this Pokémon from your hand onto your Bench during your turn, "
                  "you may draw 3 cards."
    })
    assert bench_trigger == "on_play"


def test_real_trainers_compile():
    pool = load_pool()
    research = [e.op for e in pool.lookup("Professor's Research").effects]
    assert research == ["discard_hand", "draw"]
    assert [e.op for e in pool.lookup("Iono").effects] == ["shuffle_hand_into_deck", "draw_prizes"]
    assert [e.op for e in pool.lookup("Boss's Orders").effects] == ["switch_opponent"]
    nest = pool.lookup("Nest Ball").effects[0]
    assert (nest.op, nest.filter, nest.dest) == ("search", "basic_pokemon", "bench")
    ultra = [e.op for e in pool.lookup("Ultra Ball").effects]
    assert ultra == ["discard_from_hand", "search"]


def test_infernal_reign_accelerates_energy():
    card = load_pool().lookup("Charizard ex", "OBF", "125")
    assert card.ability_trigger == "on_evolve"
    assert card.ability[0].op == "attach_energy"
    assert card.ability[0].n == 3
