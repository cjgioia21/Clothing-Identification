import pytest

from clothing_id.models import FiberContent
from clothing_id.valuation import (
    FLAW_FLOOR,
    RARITY_CAP,
    dominant_fiber_multiplier,
    estimate_value,
    size_multiplier,
)

from tests.factories import make_read, sold_series


def test_range_is_ordered_and_positive(read):
    value = estimate_value(read)
    assert 0 < value.low < value.mid < value.high
    assert value.retail_estimate > 0
    assert 0 < value.confidence <= 0.95


def test_condition_moves_the_number_the_right_way(read):
    grades = ["deadstock", "excellent", "good", "fair", "poor"]
    mids = []
    for grade in grades:
        read.visual.condition_grade = grade
        mids.append(estimate_value(read).mid)
    assert mids == sorted(mids, reverse=True)


def test_luxury_beats_fast_fashion_for_the_same_garment():
    cheap = make_read()
    cheap.tag.brand = cheap.identification.brand = "Shein"
    lux = make_read()
    lux.tag.brand = lux.identification.brand = "Gucci"
    assert estimate_value(lux).mid > 10 * estimate_value(cheap).mid


def test_vintage_premium_only_applies_to_collectible_brands():
    collectible = make_read()
    collectible.tag.brand = collectible.identification.brand = "Nike"
    ordinary = make_read()
    ordinary.tag.brand = ordinary.identification.brand = "Chaps"

    def ratio(read):
        read.identification.era = "2010s"
        modern = estimate_value(read).mid
        read.identification.era = "1980s"
        return estimate_value(read).mid / modern

    assert ratio(collectible) > 1.5
    assert ratio(ordinary) <= 1.0


def test_rarity_signals_stack_but_are_capped():
    read = make_read()
    read.tag.brand = read.identification.brand = "Nike"
    plain = estimate_value(read).mid
    read.identification.rarity_signals = [
        "single stitch",
        "made in usa",
        "union label",
        "band tour print",
        "collaboration",
        "limited edition",
        "rare",
    ]
    loaded = estimate_value(read).mid
    assert plain < loaded <= plain * RARITY_CAP + 0.01


def test_flaws_reduce_value_with_a_floor(read):
    baseline = estimate_value(read).mid
    read.visual.flaws = ["small hole at hem", "underarm stains", "moth damage", "pit stain"]
    damaged = estimate_value(read).mid
    assert damaged < baseline
    assert damaged >= baseline * FLAW_FLOOR - 0.01  # cents lost to rounding


def test_observed_sales_replace_the_model(read):
    without = estimate_value(read)
    assert without.method == "modeled"

    with_data = estimate_value(read, observations=sold_series([200, 220, 180, 205, 195, 210]))
    assert with_data.method == "observed"
    assert with_data.mid > without.mid
    assert with_data.market_price and with_data.model_price
    assert with_data.evidence.sold_count == 6
    assert any(f.name == "observed market" for f in with_data.factors)


def test_thin_data_is_blended_not_trusted_outright(read):
    model_only = estimate_value(read).mid
    blended = estimate_value(read, observations=sold_series([400, 420, 380]))
    assert blended.method == "blended"
    assert model_only < blended.mid < 400
    assert any("Thin market data" in n for n in blended.notes)


def test_a_single_listing_is_not_enough_to_price_from(read):
    value = estimate_value(read, observations=sold_series([500]))
    assert value.method == "modeled"
    assert value.comparables and value.comparables[0].price == 500
    assert any("too few to price" in n for n in value.notes)


def test_band_comes_from_the_sample_not_a_fudge_factor(read):
    tight = estimate_value(read, observations=sold_series([100, 102, 98, 101, 99, 100]))
    wide = estimate_value(read, observations=sold_series([40, 260, 90, 180, 60, 220]))
    assert tight.method == wide.method == "observed"
    assert (tight.high - tight.low) < (wide.high - wide.low)


def test_asking_prices_are_discounted_to_sold_terms(read):
    sold = estimate_value(read, observations=sold_series([100] * 6))
    asks = estimate_value(read, observations=sold_series([100] * 6, kind="ask"))
    assert asks.mid < sold.mid
    assert asks.evidence.ask_count == 6
    assert any("asking prices" in n for n in asks.notes)


def test_lower_confidence_widens_the_band(read):
    read.identification.confidence = 0.9
    tight = estimate_value(read)
    read.identification.confidence = 0.2
    loose = estimate_value(read)
    assert (loose.high - loose.low) / loose.mid > (tight.high - tight.low) / tight.mid


def test_unreadable_tag_lowers_confidence_and_notes_it(read):
    read.tag.legible = False
    value = estimate_value(read)
    assert value.confidence < read.identification.confidence
    assert any("Tag unreadable" in n for n in value.notes)


@pytest.mark.parametrize(
    "fibers,expected",
    [
        ([FiberContent(fiber="100% cashmere", percent=100)], 2.30),
        ([FiberContent(fiber="cotton", percent=50), FiberContent(fiber="polyester", percent=50)], 0.925),
        ([FiberContent(fiber="merino wool", percent=None)], 1.45),
        ([], 1.0),
    ],
)
def test_fiber_blending(fibers, expected):
    mult, _ = dominant_fiber_multiplier(fibers)
    assert mult == pytest.approx(expected, rel=1e-3)


@pytest.mark.parametrize(
    "size,expected", [("M", 1.05), ("XXL", 0.85), ("Large", 1.05), ("32", 1.03), (None, 1.0)]
)
def test_size_demand(size, expected):
    assert size_multiplier(size) == pytest.approx(expected)


def test_every_factor_is_reported(read):
    read.visual.construction_details = ["single stitch", "Gore-Tex shell"]
    value = estimate_value(read)
    names = {f.name for f in value.factors}
    assert {"category baseline", "condition", "resale recovery"} <= names
    assert all(f.multiplier > 0 for f in value.factors)
