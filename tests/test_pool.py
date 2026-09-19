from pokedeck.cards import Category, Stage, Subtype
from pokedeck.pool import load_pool


def test_pool_loads_printed_cards():
    pool = load_pool()
    assert len(pool) > 1000


def test_exact_print_is_honoured():
    pool = load_pool()
    card = pool.lookup("Charizard ex", "OBF", "125")
    assert card.card_id == "sv03-125"
    assert card.hp == 330
    assert card.stage is Stage.STAGE2
    assert card.evolves_from == "Charmeleon"
    assert card.prize_value == 2
    assert card.attacks[0].cost == ("Fire", "Fire")


def test_lookup_without_a_print_still_finds_the_card():
    pool = load_pool()
    assert pool.lookup("Gardevoir ex").stage is Stage.STAGE2
    assert pool.lookup("gardevoir EX").hp > 0


def test_weakness_and_retreat_come_from_the_card():
    card = load_pool().lookup("Charizard ex", "OBF", "125")
    assert card.weakness == "Grass"
    assert card.retreat == 2


def test_trainer_subtypes():
    pool = load_pool()
    assert pool.lookup("Professor's Research").subtype is Subtype.SUPPORTER
    assert pool.lookup("Ultra Ball").subtype is Subtype.ITEM
    assert pool.lookup("Bravery Charm").subtype is Subtype.TOOL
    assert pool.lookup("Artazon").subtype is Subtype.STADIUM


def test_energy_cards_carry_their_type():
    pool = load_pool()
    fire = pool.lookup("Basic Fire Energy")
    assert fire.category is Category.ENERGY
    assert fire.is_basic_energy
    assert fire.energy_provides == ("Fire",)
    assert pool.lookup("Jet Energy").subtype is Subtype.SPECIAL_ENERGY


def test_mega_evolution_pokemon_are_worth_three_prizes():
    assert load_pool().lookup("Mega Venusaur ex").prize_value == 3


def test_missing_cards_return_none():
    assert load_pool().lookup("Glitchmon ex") is None


def test_prints_lists_every_version():
    prints = load_pool().prints("Charizard ex")
    assert len(prints) > 1
    assert all(p.name == "Charizard ex" for p in prints)


# ------------------------------------------------- gaps in the printed data
def test_an_evolution_print_missing_its_line_borrows_it_from_another_print():
    """The 30th Anniversary Seismitoad ships with no "Evolves from".

    Without this repair the card is unreachable: Palpitoad sits under it and
    the engine has nothing telling it the two go together, so a deck built
    around Seismitoad never plays one.
    """
    pool = load_pool()
    card, exact = pool.lookup_print("Seismitoad", "30C", "84")
    assert exact and card.card_id == "30th-084"
    assert card.evolves_from == "Palpitoad"
    assert all(p.evolves_from == "Palpitoad" for p in pool.prints("Seismitoad"))


def test_every_evolution_in_the_pool_has_something_to_evolve_from():
    pool = load_pool()
    orphans = {
        card.name
        for card in pool.by_print.values()
        if card.category is Category.POKEMON
        and card.stage is not Stage.BASIC
        and not card.evolves_from
        # A card whose every print lacks the field has nothing to borrow.
        and any(p.evolves_from for p in pool.prints(card.name))
    }
    assert not orphans, sorted(orphans)


def test_the_repair_does_not_invent_a_line():
    """A card with no pre-evolution on any print is left exactly as printed."""
    pool = load_pool()
    for card in pool.by_print.values():
        if card.evolves_from:
            assert any(p.evolves_from for p in pool.prints(card.name))


# -------------------------------------------------- basic vs Special Energy
BASIC_ENERGY = [
    "Basic Fire Energy", "Fire Energy", "Basic Psychic Energy", "Water Energy",
]
SPECIAL_ENERGY = [
    "Prism Energy", "Reversal Energy", "Ignition Energy", "Team Rocket's Energy",
    "Telepathic Psychic Energy", "Growing Grass Energy", "Rocky Fighting Energy",
]


def test_basic_energy_is_named_for_its_type_and_nothing_else():
    pool = load_pool()
    for name in BASIC_ENERGY:
        card = pool.lookup(name)
        assert card is not None, name
        assert card.is_basic_energy, name


def test_special_energy_is_not_taken_for_basic():
    """TCGdex marks several Special Energy as energyType "Normal".

    Believing it exempts them from rotation and from the four-copy rule, lets
    a search for "a Basic Energy card" fetch them, and drops their printed
    effects — Reversal Energy passed a Standard-legality check that way.
    """
    pool = load_pool()
    for name in SPECIAL_ENERGY:
        card = pool.lookup(name)
        assert card is not None, name
        assert not card.is_basic_energy, name


def test_a_rotated_special_energy_is_not_legal():
    pool = load_pool()
    from pokedeck.legality import card_is_legal
    reversal = pool.lookup("Reversal Energy")
    assert all(p.regulation == "G" for p in pool.prints("Reversal Energy"))
    assert not card_is_legal(reversal)


def test_special_energy_keeps_the_effects_it_prints():
    pool = load_pool()
    assert [e.op for e in pool.lookup("Telepathic Psychic Energy").effects] == ["search"]
    assert [e.op for e in pool.lookup("Growing Grass Energy").effects] == ["hp_boost"]
