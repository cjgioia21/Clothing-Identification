import json

import pytest

from pokedeck.cli import default_goals, main
from pokedeck.knowledge import resolve

from .conftest import CHARIZARD, DRAGAPULT


@pytest.fixture
def deck_path(tmp_path):
    """A Standard-legal list, written where the CLI can read it."""
    path = tmp_path / "dragapult.txt"
    path.write_text(DRAGAPULT, encoding="utf-8")
    return str(path)


@pytest.fixture
def rotated_path(tmp_path):
    path = tmp_path / "rotated.txt"
    path.write_text(CHARIZARD, encoding="utf-8")
    return str(path)


def test_check_reports_a_legal_deck(deck_path, capsys):
    assert main(["check", deck_path]) == 0
    out = capsys.readouterr().out
    assert "60 cards" in out
    assert "mulligan rate" in out
    assert "Format (standard)" in out
    assert "legal — every card" in out


def test_check_rejects_a_rotated_deck(rotated_path, capsys):
    assert main(["check", rotated_path]) == 1
    out = capsys.readouterr().out
    assert "not legal in standard" in out
    assert "regulation mark G" in out


def test_check_can_ignore_the_format(rotated_path, capsys):
    assert main(["check", rotated_path, "--format", "any"]) == 0
    assert "Format (any)" in capsys.readouterr().out


def test_check_exits_nonzero_on_an_illegal_deck(tmp_path, capsys):
    path = tmp_path / "bad.txt"
    path.write_text("Pokémon: 5\n5 Charmander PAF 7", encoding="utf-8")
    assert main(["check", str(path)]) == 1
    assert "limit 4" in capsys.readouterr().out


def test_check_json_is_machine_readable(deck_path, capsys):
    main(["check", deck_path, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["size"] == 60
    assert payload["issues"] == []


def test_sim_prints_goal_rows(deck_path, capsys):
    assert main(["sim", deck_path, "-n", "50", "--turns", "2", "--goal", "Dragapult ex"]) == 0
    out = capsys.readouterr().out
    assert "Dragapult ex" in out
    assert "Turn by turn" in out


def test_sim_json_round_trips(deck_path, capsys):
    main(["sim", deck_path, "-n", "40", "--turns", "2", "--goal", "Rare Candy + Dreepy", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["games"] == 40
    assert payload["goals"][0]["name"] == "Rare Candy + Dreepy"


def test_sim_rejects_a_goal_that_is_not_in_the_deck(deck_path, capsys):
    assert main(["sim", deck_path, "-n", "10", "--goal", "Pikachu ex"]) == 2
    assert "not in" in capsys.readouterr().err


def test_hand_deals_the_requested_number_of_hands(deck_path, capsys):
    main(["hand", deck_path, "-n", "3", "--seed", "1", "--json"])
    hands = json.loads(capsys.readouterr().out)
    assert len(hands) == 3
    assert all(len(hand) == 7 for hand in hands)


def test_odds_table_lists_named_cards(deck_path, capsys):
    main(["odds", deck_path, "--card", "rare candy", "--turns", "1"])
    out = capsys.readouterr().out
    assert "Rare Candy" in out
    assert "39.9%" in out  # four-of in the opening seven


def test_compare_lines_up_two_decks(deck_path, capsys):
    main(["compare", deck_path, deck_path, "-n", "30", "--turns", "1", "--goal", "Dragapult ex"])
    out = capsys.readouterr().out
    assert out.count("dragapult.txt") == 2


def test_gauntlet_plays_the_field(deck_path, capsys):
    assert main(["gauntlet", deck_path, "-n", "2", "--decks", "5"]) == 0
    out = capsys.readouterr().out
    assert "vs the gauntlet" in out
    assert "record" in out
    assert "going second" in out


def test_gauntlet_json_reports_every_matchup(deck_path, capsys):
    main(["gauntlet", deck_path, "-n", "2", "--decks", "4", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["games"] == 8
    assert len(payload["matchups"]) == 4
    assert payload["record"]["wins"] + payload["record"]["losses"] + payload["record"]["ties"] == 8


def test_missing_file_is_an_error(capsys):
    assert main(["check", "nope.txt"]) == 2
    assert "error:" in capsys.readouterr().err


def test_default_goals_prefer_the_top_evolution(legal_deck, legal_kb):
    assert default_goals(legal_deck, legal_kb)[0] == ("Dragapult ex",)


def test_default_goals_fall_back_to_a_basic():
    from pokedeck.decklist import parse

    deck = parse("Pokémon: 4\n4 Fezandipiti ex SFA 38\nTrainer: 2\n2 Iono PAL 185")
    assert default_goals(deck, resolve(deck)) == [("Fezandipiti ex",)]
