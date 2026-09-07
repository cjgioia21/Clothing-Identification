"""The observation-based pricing engine."""

from datetime import date, timedelta

import pytest

from clothing_id.history import Observation
from clothing_id.pricing import (
    ASK_TO_SOLD_PRIOR,
    confidence_from_basis,
    fit_annual_trend,
    measure_ask_ratio,
    measure_condition_ratios,
    price_from_observations,
)
from tests.factories import sold_series


def test_price_is_the_weighted_median_of_real_sales():
    basis = price_from_observations(sold_series([100, 105, 95, 110, 90, 100]), "good")
    assert basis is not None
    assert 90 <= basis.mid <= 110
    assert basis.low <= basis.mid <= basis.high
    assert basis.sold_count == 6 and basis.ask_count == 0
    assert basis.sources == {"ebay-sold": 6}


def test_too_few_observations_returns_nothing():
    assert price_from_observations(sold_series([100, 105]), "good") is None
    assert price_from_observations([], "good") is None


def test_recent_sales_outweigh_old_ones():
    today = date.today()
    old = [
        Observation("ebay-sold", f"old{i}", "sold", 300.0, today - timedelta(days=700),
                    condition_grade="good")
        for i in range(6)
    ]
    new = [
        Observation("ebay-sold", f"new{i}", "sold", 100.0, today - timedelta(days=5),
                    condition_grade="good")
        for i in range(6)
    ]
    basis = price_from_observations(old + new, "good")
    assert basis.mid < 160  # the fresh sales dominate


def test_condition_adjustment_moves_prices_onto_the_target_grade():
    sales = sold_series([100] * 6, condition_grade="deadstock")
    priced_as_deadstock = price_from_observations(sales, "deadstock").mid
    priced_as_fair = price_from_observations(sales, "fair").mid
    assert priced_as_fair < priced_as_deadstock


def test_condition_ratios_are_measured_when_the_sample_supports_it():
    sample = sold_series([100] * 6, condition_grade="excellent") + sold_series(
        [50] * 6, condition_grade="good", source="ebay-sold-b"
    )
    ratios, source = measure_condition_ratios(sample)
    assert source.startswith("measured")
    assert ratios["good"] == pytest.approx(0.5, rel=0.01)

    thin = sold_series([100, 90], condition_grade="excellent")
    _, thin_source = measure_condition_ratios(thin)
    assert thin_source == "priors"


def test_ask_ratio_is_measured_when_both_sides_are_present():
    sample = sold_series([80] * 6) + sold_series([100] * 6, kind="ask", source="ebay-active")
    ratio, source = measure_ask_ratio(sample)
    assert ratio == pytest.approx(0.8, rel=0.02)
    assert source.startswith("measured")

    ratio, source = measure_ask_ratio(sold_series([80] * 6))
    assert ratio == ASK_TO_SOLD_PRIOR and source == "prior"


def test_trend_is_fitted_only_with_enough_history():
    today = date.today()
    rising = [
        Observation("ebay-sold", f"r{i}", "sold", 100 * (1.10 ** (i / 12)),
                    today - timedelta(days=30 * (24 - i)), condition_grade="good")
        for i in range(24)
    ]
    trend = fit_annual_trend(rising, today=today)
    assert trend is not None and trend > 0.05

    assert fit_annual_trend(sold_series([100, 110, 120]), today=today) is None
    assert fit_annual_trend(sold_series([100] * 20, spacing_days=1), today=today) is None


def test_old_sales_are_carried_forward_by_the_trend():
    today = date.today()
    # Prices doubling over four years, sampled monthly.
    series = [
        Observation("ebay-sold", f"t{i}", "sold", 100 * (2 ** ((48 - i) / 48)),
                    today - timedelta(days=30 * i), condition_grade="good")
        for i in range(48)
    ]
    basis = price_from_observations(series, "good")
    assert basis.annual_trend is not None and basis.annual_trend > 0
    # Adjusted to today's money, the sample should sit near the newest prices.
    assert basis.mid > 150


def test_outliers_are_dropped():
    basis = price_from_observations(sold_series([100, 98, 102, 101, 99, 100, 40000]), "good")
    assert basis.outliers_dropped == 1
    assert basis.mid < 200
    assert any("outlier" in n for n in basis.notes)


def test_ask_only_samples_are_discounted_and_flagged():
    basis = price_from_observations(sold_series([100] * 6, kind="ask"), "good")
    assert basis.mid < 100
    assert basis.sold_count == 0
    assert any("No completed sales" in n for n in basis.notes)


def test_confidence_rewards_sales_and_punishes_spread():
    tight = price_from_observations(sold_series([100, 101, 99, 100, 102, 98]), "good")
    wide = price_from_observations(sold_series([20, 300, 60, 250, 40, 180]), "good")
    assert confidence_from_basis(tight) > confidence_from_basis(wide)

    asks = price_from_observations(sold_series([100] * 6, kind="ask"), "good")
    assert confidence_from_basis(asks) < confidence_from_basis(tight)


def test_matching_size_is_weighted_above_a_different_one():
    sample = sold_series([200] * 6, size="M") + sold_series([100] * 6, size="XXL", source="b")
    in_size = price_from_observations(sample, "good", target_size="M").mid
    off_size = price_from_observations(sample, "good", target_size="XXL").mid
    assert in_size > off_size
