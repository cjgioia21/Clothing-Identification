from pokedeck.decklist import parse
from pokedeck.knowledge import resolve
from pokedeck.legality import STANDARD_MARKS, card_is_legal, check, is_legal, marks_for
from pokedeck.pool import load_pool

import pytest


def test_standard_is_the_current_marks():
    assert STANDARD_MARKS == {"H", "I", "J"}
    assert marks_for("standard") == STANDARD_MARKS
    assert "G" in marks_for("any")
    with pytest.raises(ValueError):
        marks_for("gym-leader-challenge")


def test_rotated_cards_are_not_legal():
    pool = load_pool()
    assert not card_is_legal(pool.lookup("Charizard ex", "OBF", "125"))  # mark G
    assert card_is_legal(pool.lookup("Dragapult ex", "TWM", "130"))      # mark H


def test_basic_energy_never_rotates():
    assert card_is_legal(load_pool().lookup("Basic Fire Energy"))


def test_the_example_decks_are_legal(legal_deck, legal_kb):
    assert is_legal(legal_deck, legal_kb)
    assert check(legal_deck, legal_kb) == []


def test_a_rotated_deck_is_reported_card_by_card(charizard_deck, charizard_kb):
    issues = check(charizard_deck, charizard_kb)
    assert not is_legal(charizard_deck, charizard_kb)
    assert all(i.level == "error" for i in issues)
    assert any("Charizard ex" in i.message and "mark G" in i.message for i in issues)


def test_the_any_format_accepts_older_cards(charizard_deck, charizard_kb):
    assert is_legal(charizard_deck, charizard_kb, "any")


def test_one_ace_spec_is_allowed_and_two_are_not():
    one = parse("Pokémon: 4\n4 Dreepy ASH 158\n\nTrainer: 1\n1 Hero's Cape TEF 152")
    assert is_legal(one, resolve(one))

    two = parse("Pokémon: 4\n4 Dreepy ASH 158\n\nTrainer: 2\n1 Hero's Cape TEF 152\n1 Max Rod PRE 116")
    issues = [i.message for i in check(two, resolve(two)) if i.level == "error"]
    assert any("ACE SPEC" in m for m in issues)


def test_cards_with_no_printed_data_are_flagged_as_unverified():
    deck = parse("Pokémon: 4\n4 Glitchmon XYZ 1")
    issues = check(deck, resolve(deck))
    assert [i.level for i in issues] == ["warning"]
    assert "legality unverified" in issues[0].message


def test_every_gauntlet_deck_is_standard_legal():
    from pokedeck.gauntlet import load_field

    for deck, resolution in load_field():
        assert is_legal(deck, resolution), deck.name
