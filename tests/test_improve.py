"""The deck-improvement scanner's surgery and candidate rules."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pokedeck.cards import Category
from pokedeck.decklist import parse
from pokedeck.knowledge import resolve
from pokedeck.legality import is_legal
from pokedeck.pool import load_pool

from tools.improve_deck import candidates, playable, variant

DECK = """
Pokémon: 8
4 Dreepy PRE 71
4 Drakloak PRE 72

Trainer: 8
4 Ultra Ball MEG 131
4 Pokégear 3.0 BLK 84

Energy: 4
4 Basic Psychic Energy
"""


@pytest.fixture
def deck():
    return parse(DECK, name="small")


@pytest.fixture
def pool():
    return load_pool()


def counts(built):
    return {e.name: e.count for e in built.entries}


# -------------------------------------------------------------- deck surgery
def test_a_swap_keeps_the_deck_the_same_size(deck, pool):
    built = variant(deck, "Pokégear 3.0", "Buddy-Buddy Poffin", pool)
    assert built.size == deck.size
    assert counts(built)["Pokégear 3.0"] == 3
    assert counts(built)["Buddy-Buddy Poffin"] == 1


def test_swapping_into_a_card_already_there_raises_its_count(deck, pool):
    thinned = variant(deck, "Ultra Ball", "Basic Psychic Energy", pool)   # 3 Ultra Ball
    built = variant(thinned, "Pokégear 3.0", "Ultra Ball", pool)
    assert counts(built)["Ultra Ball"] == 4
    assert counts(built)["Pokégear 3.0"] == 3


def test_it_will_not_take_a_card_past_four_copies(deck, pool):
    assert variant(deck, "Pokégear 3.0", "Ultra Ball", pool) is None   # would be a fifth


def test_basic_energy_is_exempt_from_the_four_copy_rule(deck, pool):
    built = variant(deck, "Pokégear 3.0", "Basic Psychic Energy", pool)
    assert counts(built)["Basic Psychic Energy"] == 5


def test_cutting_a_card_the_deck_does_not_run_is_refused(deck, pool):
    assert variant(deck, "Boss's Orders", "Ultra Ball", pool) is None


def test_a_second_ace_spec_is_refused(pool):
    text = DECK.replace("4 Pokégear 3.0 BLK 84", "3 Pokégear 3.0 BLK 84\n1 Hero's Cape TEF 152")
    loaded = parse(text, name="ace")
    assert variant(loaded, "Pokégear 3.0", "Unfair Stamp", pool) is None


def test_every_swap_it_proposes_is_a_legal_deck(pool):
    loaded = parse(DECK, name="small")
    for add in ("Buddy-Buddy Poffin", "Boss's Orders", "Basic Fire Energy", "Carmine"):
        built = variant(loaded, "Pokégear 3.0", add, pool)
        assert built is not None, add
        assert built.size == 60 or built.size == loaded.size
        assert is_legal(built, resolve(built)), add


# ----------------------------------------------------------- what can go in
def test_a_card_the_engine_cannot_fully_read_is_not_a_candidate(pool):
    unreadable = [c for c in pool.by_print.values()
                  if c.known and c.attacks and not all(a.scripted for a in c.attacks)]
    assert unreadable, "expected the pool to contain some unmodelled text"
    assert not playable(unreadable[0])


def test_rotated_cards_are_not_candidates(pool):
    rotated = next(c for c in pool.by_print.values() if c.regulation == "G")
    assert not playable(rotated)


def test_an_evolution_needs_its_line_in_the_deck(deck, pool):
    resolution = resolve(deck)
    names, skipped = candidates(deck, resolution, pool)
    assert "Dragapult ex" in names      # Dreepy -> Drakloak -> Dragapult ex
    assert "Charizard ex" not in names  # nothing in the deck evolves into it
    assert skipped["evolves from something this deck does not play"] > 0


def test_basics_trainers_and_energy_are_always_candidates(deck, pool):
    names, _ = candidates(deck, resolve(deck), pool)
    assert "Budew" in names
    assert "Boss's Orders" in names
    assert "Basic Fire Energy" in names


def test_the_scan_covers_hundreds_of_cards(deck, pool):
    names, _ = candidates(deck, resolve(deck), pool)
    assert len(names) > 400


def test_a_swap_never_writes_a_rotated_print(pool):
    """pool.lookup can return a rotated print even when a legal one exists."""
    loaded = parse(DECK, name="small")
    for add in ("Rare Candy", "Buddy-Buddy Poffin", "Boss's Orders"):
        built = variant(loaded, "Pokégear 3.0", add, pool)
        assert built is not None, add
        entry = next(e for e in built.entries if e.name == add)
        card = pool.lookup(add, entry.set_code, entry.number)
        from pokedeck.legality import card_is_legal
        assert card_is_legal(card), f"{add} {entry.set_code} {entry.number}"


def test_a_card_with_no_legal_print_is_refused(pool):
    """Reversal Energy has rotated: every print of it is regulation mark G."""
    assert all(p.regulation == "G" for p in pool.prints("Reversal Energy"))
    loaded = parse(DECK, name="small")
    assert variant(loaded, "Pokégear 3.0", "Reversal Energy", pool) is None
    names, _ = candidates(loaded, resolve(loaded), pool)
    assert "Reversal Energy" not in names
