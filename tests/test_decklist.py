import pytest

from pokedeck.cards import Category
from pokedeck.decklist import DecklistError, format_deck, is_basic_energy_name, parse, validate


def test_parses_ptcg_live_export(charizard_deck):
    assert charizard_deck.size == 60
    charmander = charizard_deck.entry_for("Charmander")
    assert (charmander.count, charmander.set_code, charmander.number) == (4, "PAF", "7")
    assert charmander.category is Category.POKEMON


def test_parses_without_set_codes():
    deck = parse("Pokémon: 4\n4 Charmander\n\nEnergy: 2\n2 Basic Fire Energy")
    assert [e.name for e in deck.entries] == ["Charmander", "Basic Fire Energy"]
    assert deck.entry_for("Charmander").set_code is None


def test_parses_alternate_headers():
    deck = parse("Pokemon (1)\n1 Comfey LOR 79\nTrainer (1)\n1 Iono PAL 185")
    assert [e.category for e in deck.entries] == [Category.POKEMON, Category.TRAINER]


def test_ignores_comments_and_totals():
    deck = parse("# my deck\n4 Iono PAL 185\nTotal Cards: 4")
    assert deck.size == 4


def test_rejects_garbage():
    with pytest.raises(DecklistError):
        parse("four Iono")
    with pytest.raises(DecklistError):
        parse("")


def test_count_of_is_case_insensitive(charizard_deck):
    assert charizard_deck.count_of("charizard EX") == 3
    assert charizard_deck.count_of("Pikachu") == 0


def test_cards_expands_every_copy(charizard_deck):
    cards = charizard_deck.cards()
    assert len(cards) == 60
    assert cards.count("Charmander") == 4


def test_validate_accepts_a_legal_deck(charizard_deck):
    assert validate(charizard_deck) == []


def test_validate_flags_size_and_copies():
    deck = parse("Pokémon: 5\n5 Charmander PAF 7\nTrainer: 1\n1 Iono PAL 185")
    messages = [i.message for i in validate(deck) if i.level == "error"]
    assert any("expected 60" in m for m in messages)
    assert any("limit 4" in m for m in messages)


def test_basic_energy_is_exempt_from_the_copy_limit():
    deck = parse("Pokémon: 4\n4 Charmander PAF 7\nEnergy: 20\n20 Basic Fire Energy SVE 2")
    assert all("Basic Fire Energy" not in i.message for i in validate(deck))


def test_deck_without_pokemon_is_illegal():
    deck = parse("Trainer: 4\n4 Iono PAL 185")
    assert any("no Pokémon" in i.message for i in validate(deck))


def test_format_round_trips(charizard_deck):
    reparsed = parse(format_deck(charizard_deck))
    assert [(e.count, e.name) for e in reparsed.entries] == [
        (e.count, e.name) for e in charizard_deck.entries
    ]


def test_is_basic_energy_name():
    assert is_basic_energy_name("Basic Fire Energy")
    assert not is_basic_energy_name("Jet Energy")


def test_energy_symbols_are_read_as_the_full_name():
    deck = parse("Energy: 8\n5 Basic {F} Energy MEE 14\n3 {W} Energy")
    assert [e.name for e in deck.entries] == ["Basic Fighting Energy", "Basic Water Energy"]


def test_bare_type_energy_is_basic_energy():
    deck = parse("Energy: 4\n4 Fighting Energy")
    assert deck.entries[0].name == "Basic Fighting Energy"
    assert is_basic_energy_name(deck.entries[0].name)


def test_set_codes_with_digits_parse():
    deck = parse("Pokémon: 3\n3 Seismitoad 30C 84")
    entry = deck.entries[0]
    assert (entry.name, entry.set_code, entry.number) == ("Seismitoad", "30C", "84")


def test_a_header_that_disagrees_with_its_lines_is_flagged():
    deck = parse("Pokémon: 8\n4 Tympole BLK 19\n4 Budew PRE 4\n2 Mew ex 30C 152")
    messages = [i.message for i in validate(deck) if i.level == "warning"]
    assert any("header says 8" in m and "add up to 10" in m for m in messages)
