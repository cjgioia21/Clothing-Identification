from pokedeck.engine import Config
from pokedeck.simulate import run


def test_report_covers_every_requested_turn(charizard_deck, charizard_kb):
    config = Config(turns=3, goals=(("Charizard ex",), ("Rare Candy", "Charmander")))
    report = run(charizard_deck, charizard_kb, config, games=200, seed=1)
    assert report.games == 200
    assert [t.turn for t in report.turn_stats] == [1, 2, 3]
    assert [g.name for g in report.goals] == ["Charizard ex", "Rare Candy + Charmander"]


def test_goal_odds_are_cumulative(charizard_deck, charizard_kb):
    config = Config(turns=4, goals=(("Charizard ex",),))
    report = run(charizard_deck, charizard_kb, config, games=300, seed=2)
    odds = [report.goals[0].by_turn[t] for t in range(5)]
    assert odds == sorted(odds)
    assert 0.0 <= odds[0] <= odds[-1] <= 1.0


def test_never_and_reached_add_up(charizard_deck, charizard_kb):
    config = Config(turns=3, goals=(("Charizard ex",),))
    report = run(charizard_deck, charizard_kb, config, games=300, seed=3)
    goal = report.goals[0]
    assert abs(goal.by_turn[3] + goal.never - 1.0) < 1e-9


def test_in_play_goals_are_slower_than_in_hand_goals(charizard_deck, charizard_kb):
    config = Config(turns=3, goals=(("Charizard ex",), ("play:Charizard ex",)))
    report = run(charizard_deck, charizard_kb, config, games=400, seed=4)
    in_hand, in_play = report.goals
    assert in_play.by_turn[3] < in_hand.by_turn[3]
    assert in_play.by_turn[1] == 0.0  # nothing evolves on turn one


def test_seeds_make_runs_reproducible(charizard_deck, charizard_kb):
    config = Config(turns=2, goals=(("Charizard ex",),))
    first = run(charizard_deck, charizard_kb, config, games=150, seed=7)
    second = run(charizard_deck, charizard_kb, config, games=150, seed=7)
    third = run(charizard_deck, charizard_kb, config, games=150, seed=8)
    assert first.goals[0].by_turn == second.goals[0].by_turn
    assert first.goals[0].by_turn != third.goals[0].by_turn


def test_simulated_mulligan_rate_matches_the_maths(charizard_deck, charizard_kb):
    from pokedeck.odds import mulligan_rate

    report = run(charizard_deck, charizard_kb, Config(turns=1), games=4000, seed=5)
    expected = mulligan_rate(7, 60)  # the deck runs seven Basics
    assert abs(report.mulligan_rate - expected) < 0.03


def test_confidence_margin_shrinks_with_more_games(charizard_deck, charizard_kb):
    small = run(charizard_deck, charizard_kb, Config(turns=1), games=100, seed=6)
    large = run(charizard_deck, charizard_kb, Config(turns=1), games=2000, seed=6)
    assert large.margin(0.5) < small.margin(0.5)


def test_prized_odds_are_reported_per_goal(charizard_deck, charizard_kb):
    config = Config(turns=2, goals=(("Charizard ex",),))
    report = run(charizard_deck, charizard_kb, config, games=2000, seed=9)
    assert 0.2 < report.goals[0].prized < 0.35  # three copies in a 60-card deck
