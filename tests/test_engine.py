import random

from pokedeck.engine import BENCH_LIMIT, Config, Game, InPlay, play_game
from .conftest import make_game, zones_total

ALL_ENERGY = "Energy: 60\n60 Basic Fire Energy SVE 2"
ONE_BASIC = "Pokémon: 1\n1 Charmander PAF 7\n\nEnergy: 59\n59 Basic Fire Energy SVE 2"
EVOLUTION_LINE = "Pokémon: 60\n20 Charmander PAF 7\n40 Charmeleon PAF 8"
CANDY_LINE = (
    "Pokémon: 40\n20 Charmander PAF 7\n20 Charizard ex OBF 125\n\n"
    "Trainer: 20\n20 Rare Candy SVI 191"
)


def test_a_deck_with_no_basics_cannot_start():
    game = make_game(ALL_ENERGY)
    game.setup()
    assert game.stuck
    assert game.active is None


def test_setup_mulligans_until_a_basic_shows_up():
    game = make_game(ONE_BASIC, seed=3)
    game.setup()
    assert not game.stuck
    assert game.mulligans > 0
    assert game.active.name == "Charmander"


def test_setup_deals_seven_prizes_and_benches_spare_basics(charizard_deck, charizard_kb):
    game = Game(charizard_kb, charizard_deck.cards(), Config(), random.Random(11))
    game.setup()
    assert len(game.prizes) == 6
    assert len(game.hand) + 1 + len(game.bench) == 7
    assert all(game.card(spot.name).is_basic_pokemon for spot in game.in_play())


def test_no_card_is_created_or_lost(charizard_deck, charizard_kb):
    for seed in range(15):
        game = Game(charizard_kb, charizard_deck.cards(), Config(turns=4), random.Random(seed))
        game.setup()
        assert zones_total(game) == 60
        for _ in range(4):
            game.play_turn()
            assert zones_total(game) == 60


def test_nothing_evolves_on_the_first_turn():
    game = make_game(EVOLUTION_LINE, seed=5)
    game.setup()
    game.play_turn()
    assert [spot.name for spot in game.in_play()] == ["Charmander"] * len(game.in_play())


def test_evolution_happens_once_the_basic_has_waited_a_turn():
    game = make_game(EVOLUTION_LINE, seed=5)
    game.setup()
    game.play_turn()
    game.play_turn()
    assert "Charmeleon" in [spot.name for spot in game.in_play()]


def test_rare_candy_skips_the_middle_stage():
    game = make_game(CANDY_LINE, Config(turns=2, goals=(("Charizard ex",),)), seed=2)
    game.setup()
    game.play_turn()
    game.play_turn()
    board = [spot.name for spot in game.in_play()]
    assert "Charizard ex" in board
    assert "Rare Candy" in game.discard


def test_one_energy_attachment_per_turn(charizard_deck, charizard_kb):
    game = Game(charizard_kb, charizard_deck.cards(), Config(turns=3), random.Random(4))
    game.setup()
    for turn in range(1, 4):
        game.play_turn()
        assert game.energy_in_play() <= turn


def test_ultra_ball_pays_two_cards_for_a_pokemon():
    game = make_game(CANDY_LINE + "\n4 Ultra Ball SVI 196")
    game.setup()
    game.turn = 1
    game.hand = ["Ultra Ball", "Rare Candy", "Rare Candy"]
    game.deck = ["Charizard ex"] * 5
    assert game._play_utility_items()
    assert "Charizard ex" in game.hand
    assert game.discard.count("Rare Candy") == 2


def test_ultra_ball_is_not_played_without_the_discard_cost():
    game = make_game(CANDY_LINE + "\n4 Ultra Ball SVI 196")
    game.setup()
    game.turn = 1
    game.hand = ["Ultra Ball", "Rare Candy"]
    game.deck = ["Charizard ex"] * 5
    assert not game._play_utility_items()
    assert game.hand == ["Ultra Ball", "Rare Candy"]


def test_nest_ball_puts_a_basic_straight_onto_the_bench():
    game = make_game("Pokémon: 40\n40 Charmander PAF 7\n\nTrainer: 20\n20 Nest Ball SVI 181")
    game.setup()
    game.turn = 1
    bench_before = len(game.bench)
    game.hand = ["Nest Ball"]
    assert game._play_setup_items()
    assert len(game.bench) == bench_before + 1


def test_search_respects_the_bench_limit():
    game = make_game("Pokémon: 40\n40 Charmander PAF 7\n\nTrainer: 20\n20 Nest Ball SVI 181")
    game.setup()
    game.turn = 1
    game.bench = [InPlay(stack=["Charmander"], turn_played=1) for _ in range(BENCH_LIMIT)]
    game.hand = ["Nest Ball"]
    assert not game._play_setup_items()
    assert len(game.bench) == BENCH_LIMIT


def test_professors_research_dumps_the_hand_and_draws_seven():
    game = make_game(CANDY_LINE + "\n4 Professor's Research SVI 189")
    game.setup()
    game.turn = 1
    game.hand = ["Professor's Research", "Rare Candy"]
    game.deck = ["Charmander"] * 20
    assert game._play_supporter()
    assert len(game.hand) == 7
    assert "Rare Candy" in game.discard


def test_a_full_hand_of_combo_pieces_holds_back_professors_research():
    config = Config(goals=(("Rare Candy", "Charizard ex"),))
    game = make_game(CANDY_LINE + "\n4 Professor's Research SVI 189", config)
    game.setup()
    game.turn = 1
    game.hand = ["Professor's Research", "Rare Candy", "Charizard ex", "Charmander", "Charmander", "Charmander"]
    game.deck = ["Charmander"] * 20
    assert not game._play_supporter()

    game.config = Config(goals=config.goals, keep_goal_cards=False)
    assert game._play_supporter()


def test_abilities_fire_once_per_turn():
    game = make_game("Pokémon: 60\n30 Bidoof CRZ 111\n30 Bibarel CRZ 121")
    game.setup()
    game.turn = 2
    game.bench = [InPlay(stack=["Bidoof", "Bibarel"], turn_played=1)]
    game.hand = []
    game.deck = ["Bidoof"] * 20
    assert game._use_abilities()
    assert len(game.hand) == 5
    assert not game._use_abilities()


def test_on_play_abilities_fire_when_the_pokemon_is_benched():
    game = make_game(
        "Pokémon: 50\n40 Charmander PAF 7\n10 Lumineon V BRS 40\n\n"
        "Trainer: 10\n10 Professor's Research SVI 189"
    )
    game.setup()
    game.turn = 1
    game.bench = []
    game.hand = []
    game.deck = ["Professor's Research"] * 5
    game._bench_card("Lumineon V")
    assert "Professor's Research" in game.hand


def test_goals_are_scored_the_moment_the_pieces_line_up():
    config = Config(turns=2, goals=(("Charmander", "Rare Candy"),))
    game = make_game(CANDY_LINE, config, seed=1)
    game.setup()
    assert game.goal_turn["Charmander + Rare Candy"] in (0, None)
    game.play_turn()
    assert game.goal_turn["Charmander + Rare Candy"] is not None


def test_play_game_reports_the_opening_seven(charizard_deck, charizard_kb):
    result = play_game(charizard_kb, charizard_deck.cards(), Config(turns=2), random.Random(9))
    assert len(result.opening_hand) == 7
    assert len(result.prizes) == 6
    assert len(result.snapshots) == 2
    assert result.opening_basics >= 1


def test_identical_seeds_replay_identically(charizard_deck, charizard_kb):
    config = Config(turns=3, goals=(("Charizard ex",),))
    first = play_game(charizard_kb, charizard_deck.cards(), config, random.Random(42))
    second = play_game(charizard_kb, charizard_deck.cards(), config, random.Random(42))
    assert first.opening_hand == second.opening_hand
    assert first.goal_turn == second.goal_turn
