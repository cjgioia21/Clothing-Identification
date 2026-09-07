import pytest

from clothing_id.models import Comparable, FiberContent
from clothing_id.valuation import (
    FLAW_FLOOR,
    RARITY_CAP,
    dominant_fiber_multiplier,
    estimate_value,
    size_multiplier,
)

from tests.factories import make_read


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


def test_comparables_pull_the_estimate_toward_the_market(read):
    without = estimate_value(read)
    with_comps = estimate_value(
        read,
        comparables=[
            Comparable(title="Gap tee", price=200, source="eBay"),
            Comparable(title="Gap tee", price=220, source="eBay"),
            Comparable(title="Gap tee", price=180, source="Grailed"),
        ],
    )
    assert with_comps.mid > without.mid
    assert with_comps.confidence >= without.confidence
    assert any(f.name == "market comparables" for f in with_comps.factors)


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
