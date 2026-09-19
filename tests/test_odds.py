from math import isclose

from pokedeck.odds import at_least, cards_seen, copies_for, exactly, mulligan_rate, prized


def test_four_of_in_opening_seven():
    assert isclose(at_least(4, 7), 0.3995, abs_tol=5e-4)


def test_one_of_in_opening_seven():
    assert isclose(at_least(1, 7), 7 / 60)


def test_certainties_and_impossibilities():
    assert at_least(60, 7) == 1.0
    assert at_least(0, 7) == 0.0
    assert at_least(4, 0) == 0.0
    assert at_least(4, 7, wanted=0) == 1.0
    assert at_least(1, 7, wanted=2) == 0.0


def test_more_copies_never_hurt():
    odds = [at_least(n, 7) for n in range(0, 10)]
    assert odds == sorted(odds)


def test_more_draws_never_hurt():
    odds = [at_least(4, n) for n in range(1, 20)]
    assert odds == sorted(odds)


def test_exactly_sums_to_one():
    total = sum(exactly(4, 7, hits=k) for k in range(0, 5))
    assert isclose(total, 1.0)


def test_at_least_matches_exactly():
    assert isclose(at_least(3, 7, wanted=2), exactly(3, 7, hits=2) + exactly(3, 7, hits=3))


def test_mulligan_rate_falls_as_basics_rise():
    rates = [mulligan_rate(n) for n in range(4, 20)]
    assert rates == sorted(rates, reverse=True)
    assert isclose(mulligan_rate(12), 0.1906, abs_tol=5e-4)


def test_prized_odds_for_a_four_of():
    assert isclose(prized(4), 0.3515, abs_tol=5e-4)
    assert isclose(prized(1), 0.1)


def test_cards_seen_counts_one_draw_per_turn():
    assert cards_seen(0) == 7
    assert cards_seen(3) == 10
    assert cards_seen(2, extra_draw=7) == 16


def test_copies_for_finds_the_smallest_line_that_works():
    copies = copies_for(0.9, 7)
    assert at_least(copies, 7) >= 0.9
    assert at_least(copies - 1, 7) < 0.9
