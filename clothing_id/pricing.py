"""Price a garment from observed transactions rather than from opinion.

Given a set of real observations (what comparable pieces actually sold for, and
what comparable pieces are currently listed at), this module:

1. adjusts every observation onto the target's condition grade, using ratios
   measured from the data itself when the sample supports it and documented
   priors when it does not;
2. discounts asking prices to sold-price terms, again using the measured
   sold/ask ratio when it can be computed;
3. carries older sales forward to today's money using a price trend fitted to
   the observations, when there is enough history to fit one;
4. weights what remains by recency and evidence quality, and reports the
   weighted median with a real 20th-80th percentile band.

Nothing here invents a number: with no observations it returns None and the
caller falls back to the heuristic model, clearly labelled as such.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .history import Observation

# Fallback condition ratios, used only when the observations cannot supply them.
# Expressed relative to an 'excellent' piece of the same item.
CONDITION_PRIORS: Dict[str, float] = {
    "deadstock": 1.35,
    "excellent": 1.00,
    "good": 0.72,
    "fair": 0.42,
    "poor": 0.18,
    "unknown": 0.80,
}

ASK_TO_SOLD_PRIOR = 0.82  # sellers ask above what pieces clear for
RECENCY_HALF_LIFE_DAYS = 180.0
MIN_OBS_FOR_LEARNED_CONDITION = 6  # per grade, before trusting a measured ratio
MIN_OBS_FOR_TREND = 12
MIN_TREND_SPAN_DAYS = 180
MAX_ANNUAL_TREND = 0.60  # clamp fitted drift to +/-60%/yr; beyond that it is noise
OUTLIER_LOG_SIGMA = 3.0  # in robust (MAD-scaled) sigmas
OUTLIER_FLAT_RATIO = 4.0  # when every price is identical, 4x off is still an outlier


@dataclass
class MarketBasis:
    """The evidence behind an observation-based price."""

    mid: float
    low: float
    high: float
    currency: str = "USD"
    observation_count: int = 0
    sold_count: int = 0
    ask_count: int = 0
    effective_n: float = 0.0
    first_observed: Optional[date] = None
    last_observed: Optional[date] = None
    raw_median: float = 0.0
    dispersion: float = 0.0  # (p80 - p20) / mid
    annual_trend: Optional[float] = None  # fitted drift, e.g. -0.08 = -8%/yr
    condition_ratios: Dict[str, float] = field(default_factory=dict)
    condition_ratios_source: str = "priors"
    ask_ratio: float = ASK_TO_SOLD_PRIOR
    ask_ratio_source: str = "prior"
    sources: Dict[str, int] = field(default_factory=dict)
    outliers_dropped: int = 0
    notes: List[str] = field(default_factory=list)

    @property
    def date_range(self) -> str:
        if not self.first_observed or not self.last_observed:
            return ""
        if self.first_observed == self.last_observed:
            return self.first_observed.isoformat()
        return f"{self.first_observed.isoformat()} to {self.last_observed.isoformat()}"


def _weighted_quantile(pairs: Sequence[Tuple[float, float]], q: float) -> float:
    """Quantile of (value, weight) pairs. Pairs need not be sorted."""
    ordered = sorted(pairs)
    total = sum(w for _, w in ordered)
    if total <= 0:
        return ordered[len(ordered) // 2][0]
    target = q * total
    seen = 0.0
    for value, weight in ordered:
        seen += weight
        if seen >= target:
            return value
    return ordered[-1][0]


def measure_condition_ratios(observations: Iterable[Observation]) -> Tuple[Dict[str, float], str]:
    """Derive condition ratios from the data when each grade has enough sales.

    Returns (ratios relative to 'excellent', source label).
    """
    buckets: Dict[str, List[float]] = {}
    for obs in observations:
        grade = (obs.condition_grade or "").lower()
        if grade in CONDITION_PRIORS and grade != "unknown":
            buckets.setdefault(grade, []).append(obs.price)

    usable = {g: v for g, v in buckets.items() if len(v) >= MIN_OBS_FOR_LEARNED_CONDITION}
    if "excellent" not in usable or len(usable) < 2:
        return dict(CONDITION_PRIORS), "priors"

    def median(values: List[float]) -> float:
        values = sorted(values)
        mid = len(values) // 2
        return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2

    anchor = median(usable["excellent"])
    ratios = dict(CONDITION_PRIORS)
    learned = []
    for grade, values in usable.items():
        ratio = median(values) / anchor if anchor else 1.0
        if 0.05 <= ratio <= 3.0:
            ratios[grade] = ratio
            learned.append(grade)
    label = f"measured from {len(learned)} grades in this sample" if learned else "priors"
    return ratios, label


def measure_ask_ratio(observations: Iterable[Observation]) -> Tuple[float, str]:
    """Sold-to-ask ratio measured from the sample, or the documented prior."""
    sold = [o.price for o in observations if o.kind == "sold"]
    asks = [o.price for o in observations if o.kind == "ask"]
    if len(sold) >= 5 and len(asks) >= 5:
        ratio = (sum(sold) / len(sold)) / (sum(asks) / len(asks))
        if 0.3 <= ratio <= 1.2:
            return ratio, f"measured ({len(sold)} sales vs {len(asks)} asks)"
    return ASK_TO_SOLD_PRIOR, "prior"


def fit_annual_trend(observations: Sequence[Observation], today: Optional[date] = None) -> Optional[float]:
    """Least-squares slope of log(price) against age in years.

    Returns the annual drift (0.12 = prices rising 12%/yr) or None when the
    sample is too small or too short a span to say anything.
    """
    today = today or date.today()
    points = [
        ((today - o.observed_on).days / 365.25, math.log(o.price))
        for o in observations
        if o.price > 0
    ]
    if len(points) < MIN_OBS_FOR_TREND:
        return None
    span_days = (max(p[0] for p in points) - min(p[0] for p in points)) * 365.25
    if span_days < MIN_TREND_SPAN_DAYS:
        return None

    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    denom = sum((x - mean_x) ** 2 for x, _ in points)
    if denom <= 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denom
    # slope is d(log price)/d(age); prices rise over time when older is cheaper.
    annual = math.exp(-slope) - 1
    return max(-MAX_ANNUAL_TREND, min(MAX_ANNUAL_TREND, annual))


def _drop_outliers(
    values: Sequence[Tuple[Observation, float]]
) -> Tuple[List[Tuple[Observation, float]], int]:
    """Trim log-space outliers (mislabelled lots, wrong-item matches).

    Uses the median absolute deviation rather than the standard deviation: one
    $40,000 listing in a sample of $100 tees would inflate a standard deviation
    enough to hide itself.
    """
    if len(values) < 6:
        return list(values), 0
    logs = sorted(math.log(v) for _, v in values if v > 0)
    if not logs:
        return list(values), 0
    center = logs[len(logs) // 2]
    deviations = sorted(abs(x - center) for x in logs)
    mad = deviations[len(deviations) // 2]
    if mad > 0:
        limit = OUTLIER_LOG_SIGMA * 1.4826 * mad
    else:
        limit = math.log(OUTLIER_FLAT_RATIO)  # identical prices: only gross outliers go
    kept = [(o, v) for o, v in values if v > 0 and abs(math.log(v) - center) <= limit]
    if len(kept) < 3:  # never trim the sample away
        return list(values), 0
    return kept, len(values) - len(kept)


def price_from_observations(
    observations: Sequence[Observation],
    target_condition: str = "unknown",
    target_size: Optional[str] = None,
    today: Optional[date] = None,
    min_observations: int = 3,
) -> Optional[MarketBasis]:
    """Turn real observations into a price for the target garment.

    Returns None when there is not enough evidence to price from data alone.
    """
    today = today or date.today()
    usable = [o for o in observations if o.price and o.price > 0]
    if len(usable) < min_observations:
        return None

    condition_ratios, ratio_source = measure_condition_ratios(usable)
    ask_ratio, ask_source = measure_ask_ratio(usable)
    trend = fit_annual_trend(usable, today=today)
    target_factor = condition_ratios.get(target_condition, condition_ratios["unknown"])

    adjusted: List[Tuple[Observation, float]] = []
    for obs in usable:
        price = obs.price

        # 1. condition -> the target's grade
        grade = (obs.condition_grade or "unknown").lower()
        obs_factor = condition_ratios.get(grade, condition_ratios["unknown"])
        if obs_factor > 0:
            price *= target_factor / obs_factor

        # 2. asking price -> sold terms
        if obs.kind == "ask":
            price *= ask_ratio

        # 3. old money -> today's money
        if trend is not None:
            years = (today - obs.observed_on).days / 365.25
            price *= (1 + trend) ** years

        if price > 0:
            adjusted.append((obs, price))

    adjusted, dropped = _drop_outliers(adjusted)
    if len(adjusted) < min_observations:
        return None

    pairs: List[Tuple[float, float]] = []
    for obs, price in adjusted:
        recency = 0.5 ** ((today - obs.observed_on).days / RECENCY_HALF_LIFE_DAYS)
        quality = 1.0 if obs.kind == "sold" else 0.45
        specificity = 1.0
        if target_size and obs.size:
            from .history import size_key

            specificity = 1.25 if size_key(obs.size) == size_key(target_size) else 0.8
        pairs.append((price, max(recency * quality * specificity, 1e-6)))

    mid = _weighted_quantile(pairs, 0.5)
    low = _weighted_quantile(pairs, 0.20)
    high = _weighted_quantile(pairs, 0.80)
    raw_prices = sorted(p for p, _ in pairs)
    raw_median = raw_prices[len(raw_prices) // 2]

    sold = [o for o, _ in adjusted if o.kind == "sold"]
    sources: Dict[str, int] = {}
    for obs, _ in adjusted:
        sources[obs.source] = sources.get(obs.source, 0) + 1

    notes: List[str] = []
    if not sold:
        notes.append(
            "No completed sales in the sample - priced from asking prices "
            f"discounted by {ask_ratio:.2f} ({ask_source})."
        )
    if trend is None:
        notes.append("Not enough price history to fit a trend; sales used as-is.")
    if dropped:
        notes.append(f"Dropped {dropped} outlier listing(s) far outside the rest of the sample.")

    return MarketBasis(
        mid=round(mid, 2),
        low=round(min(low, mid), 2),
        high=round(max(high, mid), 2),
        currency=adjusted[0][0].currency or "USD",
        observation_count=len(adjusted),
        sold_count=len(sold),
        ask_count=len(adjusted) - len(sold),
        effective_n=round(sum(w for _, w in pairs), 2),
        first_observed=min(o.observed_on for o, _ in adjusted),
        last_observed=max(o.observed_on for o, _ in adjusted),
        raw_median=round(raw_median, 2),
        dispersion=round((high - low) / mid, 3) if mid else 0.0,
        annual_trend=round(trend, 4) if trend is not None else None,
        condition_ratios={k: round(v, 3) for k, v in condition_ratios.items()},
        condition_ratios_source=ratio_source,
        ask_ratio=round(ask_ratio, 3),
        ask_ratio_source=ask_source,
        sources=sources,
        outliers_dropped=dropped,
        notes=notes,
    )


def confidence_from_basis(basis: MarketBasis) -> float:
    """Confidence earned by the evidence: more sales, tighter spread, fresher."""
    n_term = 1 - math.exp(-basis.effective_n / 6.0)
    spread_term = 1 / (1 + max(basis.dispersion, 0.0))
    sold_share = basis.sold_count / basis.observation_count if basis.observation_count else 0
    quality = 0.6 + 0.4 * sold_share
    freshness = 1.0
    if basis.last_observed:
        age = (date.today() - basis.last_observed).days
        freshness = 0.5 ** (age / 730.0)  # two-year half life on staleness
    return round(min(max(n_term * spread_term * quality * freshness, 0.05), 0.95), 2)
