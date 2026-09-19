import json

from pokedeck.cards import Category, Stage, Subtype
from pokedeck.decklist import parse
from pokedeck.knowledge import load_builtin, load_overrides, resolve


def test_builtin_database_loads():
    cards = load_builtin()
    assert cards["charizard ex"].stage is Stage.STAGE2
    assert cards["professor's research"].draw_value == 7


def test_known_cards_keep_their_printed_behaviour(charizard_kb):
    research = charizard_kb.get("Professor's Research")
    assert research.is_supporter
    assert [e.op for e in research.effects] == ["discard_hand", "draw"]


def test_unknown_cards_are_reported_and_stubbed():
    deck = parse("Pokémon: 2\n2 Glitchmon XYZ 1\n\nTrainer: 2\n2 Mysterious Gadget XYZ 2")
    resolution = resolve(deck)
    assert sorted(resolution.unknown) == ["Glitchmon", "Mysterious Gadget"]
    assert resolution.get("Glitchmon").is_basic_pokemon
    assert resolution.get("Mysterious Gadget").subtype is Subtype.ITEM
    assert resolution.get("Mysterious Gadget").effects == ()


def test_basic_energy_is_recognised_without_a_database_entry():
    deck = parse("Energy: 4\n4 Basic Lightning Energy SVE 4")
    resolution = resolve(deck)
    assert resolution.unknown == []
    assert resolution.get("Basic Lightning Energy").is_basic_energy


def test_special_energy_is_not_basic_energy():
    resolution = resolve(parse("Energy: 2\n2 Jet Energy PAL 190"))
    assert resolution.get("Jet Energy").subtype is Subtype.SPECIAL_ENERGY


def test_overrides_fill_in_missing_cards(tmp_path):
    path = tmp_path / "cards.json"
    path.write_text(json.dumps({"cards": [
        {"name": "Glitchmon", "category": "pokemon", "stage": "basic",
         "ability_name": "Bounce", "ability": [{"op": "draw", "n": 2}]}
    ]}), encoding="utf-8")
    deck = parse("Pokémon: 2\n2 Glitchmon XYZ 1")
    resolution = resolve(deck, load_overrides(str(path)))
    assert resolution.unknown == []
    assert resolution.get("Glitchmon").ability[0].n == 2


def test_overrides_can_correct_a_bundled_card(tmp_path):
    path = tmp_path / "cards.json"
    path.write_text(json.dumps([
        {"name": "Iono", "category": "trainer", "subtype": "supporter",
         "effects": [{"op": "draw", "n": 2}]}
    ]), encoding="utf-8")
    deck = parse("Trainer: 2\n2 Iono PAL 185")
    resolution = resolve(deck, load_overrides(str(path)))
    assert resolution.get("Iono").draw_value == 2


def test_skipped_evolution_stages_are_still_known():
    deck = parse("Pokémon: 4\n2 Charmander PAF 7\n2 Charizard ex OBF 125")
    resolution = resolve(deck)
    assert "Charmeleon" not in resolution.cards
    assert resolution.info("Charmeleon").stage is Stage.STAGE1
    assert resolution.info("Charmeleon").evolves_from == "Charmander"
    assert resolution.info(None) is None


def test_decklist_categories_do_not_override_the_database():
    deck = parse("Trainer: 2\n2 Comfey LOR 79")
    assert resolve(deck).get("Comfey").category is Category.POKEMON


def test_a_print_we_do_not_have_is_reported_as_a_substitution():
    deck = parse("Trainer: 2\n2 Ultra Ball PLF 122")
    resolution = resolve(deck)
    assert resolution.get("Ultra Ball").known
    assert any("Ultra Ball PLF 122" in swap for swap in resolution.substituted)


def test_the_exact_print_named_is_used_when_we_have_it():
    deck = parse("Trainer: 2\n2 Ultra Ball SVI 196")
    resolution = resolve(deck)
    assert resolution.substituted == []
    assert resolution.get("Ultra Ball").card_id == "sv01-196"
