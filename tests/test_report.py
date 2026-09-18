from pokedeck.engine import Config
from pokedeck.report import composition, pct, render_check, render_odds_table, render_sim
from pokedeck.decklist import parse, validate
from pokedeck.knowledge import resolve
from pokedeck.simulate import run


def test_composition_counts_each_role(charizard_deck, charizard_kb):
    counts = composition(charizard_deck, charizard_kb)
    assert counts["pokemon"] == 13
    assert counts["basics"] == 7
    assert counts["evolutions"] == 6
    assert counts["draw supporters"] == 8  # Research, Iono, Arven — not Boss's Orders
    assert counts["ball/search items"] == 11
    assert counts["basic energy"] == 13
    assert counts["pokemon"] + counts["trainers"] + counts["energy"] == 60


def test_pct_formats_a_probability():
    assert pct(0.5).strip() == "50.0%"
    assert pct(1.0).strip() == "100.0%"


def test_render_check_lists_unknown_cards():
    deck = parse("Pokémon: 60\n60 Glitchmon XYZ 1")
    resolution = resolve(deck)
    out = render_check(deck, resolution, validate(deck))
    assert "Glitchmon" in out
    assert "does not know" in out


def test_render_sim_includes_every_goal(charizard_deck, charizard_kb):
    config = Config(turns=2, goals=(("Charizard ex",), ("play:Charizard ex",)))
    report = run(charizard_deck, charizard_kb, config, games=50, seed=1)
    out = render_sim(report)
    assert "play:Charizard ex" in out
    assert "confidence" in out


def test_render_odds_table_has_a_row_per_card(charizard_deck):
    out = render_odds_table(charizard_deck, ["Charmander", "Iono"], turns=2)
    assert "Charmander" in out and "Iono" in out
    assert out.count("%") >= 8
