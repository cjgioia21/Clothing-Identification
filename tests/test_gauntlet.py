import pytest

from pokedeck.decklist import parse_file, validate
from pokedeck.gauntlet import load_field, run_gauntlet
from pokedeck.knowledge import resolve


# Cards the field names that the bundled pool has no print for. Keeping the
# list here rather than deleting the cards means the gap is a stated fact, not
# something that quietly passes — a deck naming anything else fails the test.
FIELD_DATA_GAPS = {"Mysterious Rock Inn"}


def test_the_field_is_a_hundred_legal_decks():
    field = load_field()
    assert len(field) == 100
    names = {deck.name for deck, _ in field}
    assert len(names) == 100
    for deck, resolution in field:
        assert deck.size == 60
        assert not [i for i in validate(deck) if i.level == "error"]
        assert set(resolution.unknown) <= FIELD_DATA_GAPS, deck.name


def test_the_field_is_standard_legal():
    from pokedeck.legality import check as legality_check

    for deck, resolution in load_field():
        errors = [i for i in legality_check(deck, resolution) if i.level == "error"]
        assert not errors, f"{deck.name}: {errors[0].message}"


def test_every_field_deck_can_actually_play():
    for deck, resolution in load_field():
        pokemon = [c for c in resolution.cards.values() if c.hp]
        assert pokemon, deck.name
        assert any(c.attacks for c in pokemon), deck.name


def test_gauntlet_totals_add_up(charizard_deck, charizard_kb):
    field = load_field(4)
    report = run_gauntlet(charizard_deck, charizard_kb, field, games_per_deck=4, seed=1)
    assert report.games == 16
    assert report.wins + report.losses + report.ties == report.games
    assert report.first_games == report.second_games == 8
    assert len(report.matchups) == 4
    assert all(m.games == 4 for m in report.matchups)
    assert 0.0 <= report.win_rate <= 1.0


def test_matchups_are_sorted_worst_first(charizard_deck, charizard_kb):
    report = run_gauntlet(charizard_deck, charizard_kb, load_field(6), games_per_deck=4, seed=2)
    rates = [m.win_rate for m in report.sorted_matchups()]
    assert rates == sorted(rates)


def test_the_same_seed_replays_the_same_gauntlet(charizard_deck, charizard_kb):
    field = load_field(3)
    first = run_gauntlet(charizard_deck, charizard_kb, field, games_per_deck=4, seed=3)
    second = run_gauntlet(charizard_deck, charizard_kb, field, games_per_deck=4, seed=3)
    third = run_gauntlet(charizard_deck, charizard_kb, field, games_per_deck=4, seed=4)
    assert first.wins == second.wins
    assert (first.wins, first.prizes_for) != (third.wins, third.prizes_for) or first.games < 8


def test_results_are_decided_by_real_win_conditions(charizard_deck, charizard_kb):
    report = run_gauntlet(charizard_deck, charizard_kb, load_field(10), games_per_deck=4, seed=5)
    assert set(report.reasons) <= {"prizes", "deck-out", "bench-out", "turn-limit", "no-basics"}
    assert report.reasons["prizes"] > 0


def test_coverage_is_reported(charizard_deck, charizard_kb):
    report = run_gauntlet(charizard_deck, charizard_kb, load_field(2), games_per_deck=2)
    assert report.coverage == charizard_kb.coverage()
    assert report.unknown_cards == []


def test_policies_can_be_chosen_and_are_validated(charizard_deck, charizard_kb):
    from pokedeck.gauntlet import make_policy
    from pokedeck.planner import ChampionPolicy
    from pokedeck.policy import Policy

    assert isinstance(make_policy("greedy"), Policy)
    assert isinstance(make_policy("champion"), ChampionPolicy)
    with pytest.raises(ValueError):
        make_policy("world-champion")


def test_splitting_across_workers_changes_nothing(charizard_deck, charizard_kb):
    field = load_field(4)
    one = run_gauntlet(charizard_deck, charizard_kb, field, games_per_deck=2, seed=11,
                       policy="greedy", workers=1)
    many = run_gauntlet(charizard_deck, charizard_kb, field, games_per_deck=2, seed=11,
                        policy="greedy", workers=2)
    assert (one.wins, one.losses, one.prizes_for) == (many.wins, many.losses, many.prizes_for)
    assert [m.opponent for m in one.matchups] == [m.opponent for m in many.matchups]


def test_the_searching_player_runs_the_gauntlet(charizard_deck, charizard_kb):
    report = run_gauntlet(charizard_deck, charizard_kb, load_field(2), games_per_deck=2,
                          policy="champion", workers=1)
    assert report.games == 4
    assert report.policy == "champion"


def test_a_deck_of_blanks_loses_to_the_field():
    text = "Pokémon: 20\n20 Glitchmon XYZ 1\n\nEnergy: 40\n40 Basic Fire Energy SVE 2"
    from pokedeck.decklist import parse

    deck = parse(text, name="blanks")
    resolution = resolve(deck)
    report = run_gauntlet(deck, resolution, load_field(6), games_per_deck=6, seed=6, policy="greedy")
    # It cannot take a prize; it only ever wins by the opponent stalling out.
    assert report.prize_margin < -2.0
    assert report.win_rate < 0.4
    assert "Glitchmon" in report.unknown_cards
