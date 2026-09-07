"""Rough resale valuation from an identified garment.

The estimate is deterministic and auditable: every multiplier that moves the
number is recorded as a ValueFactor so the output can explain itself.

    retail   = category baseline x brand tier x fabric x construction
    resale   = retail x tier recovery x condition x era x rarity x size x demand
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from .brands import Tier, lookup_tier
from .models import (
    Comparable,
    ConditionGrade,
    Era,
    FiberContent,
    GarmentRead,
    ValueEstimate,
    ValueFactor,
)

# Baseline new-retail price in USD for a mainstream-tier item of each category.
CATEGORY_BASELINE: Dict[str, float] = {
    "t-shirt": 25,
    "shirt": 55,
    "polo": 45,
    "sweatshirt": 55,
    "hoodie": 65,
    "sweater": 80,
    "cardigan": 90,
    "jacket": 130,
    "coat": 200,
    "blazer": 160,
    "suit": 350,
    "vest": 80,
    "jeans": 70,
    "pants": 70,
    "shorts": 45,
    "skirt": 60,
    "dress": 100,
    "jumpsuit": 110,
    "activewear": 60,
    "swimwear": 45,
    "underwear": 20,
    "sleepwear": 40,
    "shoes": 110,
    "boots": 160,
    "sneakers": 100,
    "bag": 90,
    "hat": 30,
    "scarf": 40,
    "belt": 40,
    "gloves": 35,
    "accessory": 35,
    "unknown": 60,
}

# Dominant-fiber influence on new retail.
FIBER_MULTIPLIERS: Dict[str, float] = {
    "cashmere": 2.30,
    "vicuna": 6.00,
    "alpaca": 1.60,
    "merino": 1.45,
    "wool": 1.30,
    "mohair": 1.45,
    "silk": 1.55,
    "leather": 2.10,
    "suede": 2.00,
    "shearling": 3.00,
    "down": 1.70,
    "linen": 1.20,
    "hemp": 1.10,
    "tencel": 1.05,
    "lyocell": 1.05,
    "modal": 1.00,
    "cotton": 1.00,
    "denim": 1.05,
    "corduroy": 1.05,
    "fleece": 1.00,
    "rayon": 0.90,
    "viscose": 0.90,
    "nylon": 0.95,
    "polyester": 0.85,
    "acrylic": 0.75,
    "spandex": 1.00,
    "elastane": 1.00,
    "polyamide": 0.95,
}

# Construction/technical details visible on the garment or its tag.
CONSTRUCTION_MULTIPLIERS: Dict[str, float] = {
    "gore-tex": 1.35,
    "gore tex": 1.35,
    "goretex": 1.35,
    "taped seams": 1.10,
    "selvedge": 1.30,
    "chain stitch": 1.05,
    "hand stitched": 1.25,
    "canvas construction": 1.20,
    "full canvas": 1.20,
    "half canvas": 1.10,
    "ykk excella": 1.05,
    "riri": 1.10,
    "goodyear welt": 1.25,
    "blake stitch": 1.10,
    "primaloft": 1.10,
    "polartec": 1.10,
    "cordura": 1.05,
}

CONDITION_MULTIPLIERS: Dict[str, float] = {
    "deadstock": 1.35,
    "excellent": 1.00,
    "good": 0.72,
    "fair": 0.42,
    "poor": 0.18,
    "unknown": 0.70,
}

# Age premium, applied only to collectible tiers; ordinary brands just get old.
ERA_MULTIPLIERS_COLLECTIBLE: Dict[str, float] = {
    "pre-1970": 2.20,
    "1970s": 1.90,
    "1980s": 1.65,
    "1990s": 1.45,
    "2000s": 1.15,
    "2010s": 1.00,
    "2020s": 1.00,
    "unknown": 1.00,
}

# For non-collectible brands age is wear, not provenance: value only decays.
ERA_MULTIPLIERS_ORDINARY: Dict[str, float] = {
    "pre-1970": 0.80,
    "1970s": 0.80,
    "1980s": 0.82,
    "1990s": 0.85,
    "2000s": 0.88,
    "2010s": 0.95,
    "2020s": 1.00,
    "unknown": 0.95,
}

# Collector signals; each contributes once, and the stack is capped.
RARITY_MULTIPLIERS: Dict[str, float] = {
    "single stitch": 1.25,
    "made in usa": 1.15,
    "made in england": 1.12,
    "made in italy": 1.10,
    "made in japan": 1.15,
    "union label": 1.20,
    "union made": 1.20,
    "talon zipper": 1.15,
    "scovill zipper": 1.10,
    "deadstock": 1.10,
    "collaboration": 1.60,
    "collab": 1.60,
    "band tour": 1.70,
    "tour print": 1.70,
    "all over print": 1.20,
    "big logo": 1.15,
    "sun faded": 1.05,
    "discontinued colorway": 1.20,
    "runway": 1.40,
    "limited edition": 1.35,
    "sample": 1.30,
    "rare": 1.20,
    "boxy fit": 1.10,
    "embroidered": 1.05,
    "distressed": 0.95,
}
RARITY_CAP = 2.60

# Menswear/womenswear sizing demand. Mid sizes clear fastest.
SIZE_MULTIPLIERS: Dict[str, float] = {
    "xxs": 0.80,
    "xs": 0.88,
    "s": 1.00,
    "m": 1.05,
    "l": 1.05,
    "xl": 0.95,
    "xxl": 0.85,
    "3xl": 0.75,
    "4xl": 0.70,
}

FLAW_PENALTIES: Dict[str, float] = {
    "hole": 0.75,
    "holes": 0.75,
    "stain": 0.80,
    "stains": 0.80,
    "moth": 0.70,
    "pilling": 0.92,
    "fading": 0.95,
    "fade": 0.95,
    "missing button": 0.92,
    "broken zipper": 0.80,
    "repair": 0.88,
    "yellowing": 0.85,
    "shrunk": 0.85,
    "cracked print": 0.90,
    "pit stain": 0.75,
}
FLAW_FLOOR = 0.45


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("_", " ").split())


def _match_multiplier(phrases: Iterable[str], table: Dict[str, float]) -> Dict[str, float]:
    """Return {matched key: multiplier} for every table entry found in phrases."""
    found: Dict[str, float] = {}
    haystack = " | ".join(_norm(p) for p in phrases if p)
    for key, mult in table.items():
        if key in haystack:
            found.setdefault(key, mult)
    return found


def dominant_fiber_multiplier(fibers: List[FiberContent]) -> tuple[float, str]:
    """Weight fiber multipliers by declared percentage; fall back to the best match."""
    if not fibers:
        return 1.0, ""

    weighted: List[tuple[float, float, str]] = []
    for fc in fibers:
        name = _norm(fc.fiber)
        mult = None
        matched = ""
        for key, value in FIBER_MULTIPLIERS.items():
            if key in name:
                # Prefer the most specific (longest) fiber keyword.
                if mult is None or len(key) > len(matched):
                    mult, matched = value, key
        if mult is None:
            continue
        weighted.append((fc.percent if fc.percent is not None else 0.0, mult, matched))

    if not weighted:
        return 1.0, ""

    total_pct = sum(pct for pct, _, _ in weighted)
    if total_pct <= 0:
        best = max(weighted, key=lambda item: item[1])
        return best[1], best[2]

    blended = sum(pct * mult for pct, mult, _ in weighted) / total_pct
    label = max(weighted, key=lambda item: item[0])[2]
    return blended, label


def size_multiplier(size: Optional[str]) -> float:
    if not size:
        return 1.0
    key = _norm(size).replace(" ", "")
    key = {"xxxl": "3xl", "xxxxl": "4xl", "small": "s", "medium": "m", "large": "l"}.get(key, key)
    if key in SIZE_MULTIPLIERS:
        return SIZE_MULTIPLIERS[key]
    # Numeric sizing: waist/dress numbers in the middle of the run sell best.
    digits = "".join(c for c in key if c.isdigit())
    if digits:
        n = int(digits)
        if 28 <= n <= 36 or 4 <= n <= 10:
            return 1.03
        if n >= 42 or n <= 2:
            return 0.85
    return 1.0


def _era_multiplier(era: Era, tier: Tier) -> float:
    table = ERA_MULTIPLIERS_COLLECTIBLE if tier.collectible else ERA_MULTIPLIERS_ORDINARY
    return table.get(era, 1.0)


def _condition_multiplier(grade: ConditionGrade) -> float:
    return CONDITION_MULTIPLIERS.get(grade, CONDITION_MULTIPLIERS["unknown"])


def _spread(confidence: float) -> tuple[float, float]:
    """Low/high band around the midpoint. Less confidence, wider band."""
    confidence = min(max(confidence, 0.0), 1.0)
    low = 0.72 - 0.22 * (1 - confidence)
    high = 1.35 + 0.65 * (1 - confidence)
    return low, high


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def estimate_value(
    read: GarmentRead,
    comparables: Optional[List[Comparable]] = None,
    currency: str = "USD",
) -> ValueEstimate:
    """Price a garment from its structured read, optionally anchored to comps."""
    tag, visual, ident = read.tag, read.visual, read.identification
    factors: List[ValueFactor] = []
    notes: List[str] = []

    tier = lookup_tier(ident.brand or tag.brand, ident.sub_label or tag.sub_label)
    category = ident.category if ident.category != "unknown" else visual.category
    baseline = CATEGORY_BASELINE.get(category, CATEGORY_BASELINE["unknown"])

    factors.append(
        ValueFactor(name="category baseline", multiplier=baseline, note=f"{category} @ mainstream retail")
    )
    factors.append(
        ValueFactor(
            name=f"brand tier: {tier.name}",
            multiplier=tier.retail_multiplier,
            note=(ident.brand or tag.brand or "brand not identified"),
        )
    )

    fiber_mult, fiber_label = dominant_fiber_multiplier(tag.fiber_content)
    if fiber_mult != 1.0:
        factors.append(
            ValueFactor(name="fabric", multiplier=round(fiber_mult, 3), note=fiber_label or "blend")
        )

    construction_hits = _match_multiplier(
        list(visual.construction_details) + list(visual.hardware) + [tag.raw_text],
        CONSTRUCTION_MULTIPLIERS,
    )
    construction_mult = 1.0
    for key, mult in construction_hits.items():
        construction_mult *= mult
        factors.append(ValueFactor(name="construction", multiplier=mult, note=key))
    construction_mult = min(construction_mult, 1.8)

    retail = baseline * tier.retail_multiplier * fiber_mult * construction_mult

    # --- resale side -------------------------------------------------------
    condition_mult = _condition_multiplier(visual.condition_grade)
    factors.append(
        ValueFactor(
            name="condition", multiplier=condition_mult, note=visual.condition_grade
        )
    )

    era = ident.era if ident.era != "unknown" else visual.estimated_era
    era_mult = _era_multiplier(era, tier)
    if era_mult != 1.0:
        factors.append(
            ValueFactor(
                name="era",
                multiplier=era_mult,
                note=f"{era}{' (collectible brand)' if tier.collectible else ''}",
            )
        )

    rarity_sources = list(ident.rarity_signals) + list(visual.construction_details) + [
        tag.country_of_origin or "",
        " ".join(tag.tag_era_hints),
        " ".join(visual.graphics_text),
        ident.likely_collaboration or "",
    ]
    if tag.union_label:
        rarity_sources.append("union label")
    rarity_hits = _match_multiplier(rarity_sources, RARITY_MULTIPLIERS)
    rarity_mult = 1.0
    for key, mult in rarity_hits.items():
        rarity_mult *= mult
    rarity_mult = min(rarity_mult, RARITY_CAP)
    if rarity_mult != 1.0:
        factors.append(
            ValueFactor(
                name="rarity signals",
                multiplier=round(rarity_mult, 3),
                note=", ".join(sorted(rarity_hits)) or "",
            )
        )

    flaw_hits = _match_multiplier(visual.flaws, FLAW_PENALTIES)
    flaw_mult = 1.0
    for mult in flaw_hits.values():
        flaw_mult *= mult
    flaw_mult = max(flaw_mult, FLAW_FLOOR)
    if flaw_mult != 1.0:
        factors.append(
            ValueFactor(
                name="flaws", multiplier=round(flaw_mult, 3), note=", ".join(sorted(flaw_hits))
            )
        )

    size_mult = size_multiplier(tag.size)
    if size_mult != 1.0:
        factors.append(ValueFactor(name="size demand", multiplier=size_mult, note=tag.size or ""))

    factors.append(
        ValueFactor(
            name="resale recovery", multiplier=tier.resale_factor, note=f"{tier.name} tier"
        )
    )

    mid = retail * tier.resale_factor * condition_mult * era_mult * rarity_mult * flaw_mult * size_mult

    confidence = ident.confidence
    if not tag.legible:
        confidence *= 0.75
        notes.append("Tag unreadable or missing - brand inferred from the garment alone.")
    if tier.name == "unknown":
        confidence *= 0.8
        notes.append("Brand not in the tier table; priced at the mainstream baseline.")
    if visual.condition_grade == "unknown":
        confidence *= 0.85
        notes.append("Condition not assessable from the photos; assumed light wear.")
    confidence = min(max(confidence, 0.05), 0.95)

    comparables = comparables or []
    priced_comps = [c.price for c in comparables if c.price and c.price > 0]
    if priced_comps:
        comp_median = _median(priced_comps)
        blended = 0.45 * mid + 0.55 * comp_median
        factors.append(
            ValueFactor(
                name="market comparables",
                multiplier=round(blended / mid, 3) if mid else 1.0,
                note=f"{len(priced_comps)} listings, median ${comp_median:,.0f}",
            )
        )
        mid = blended
        confidence = min(0.95, confidence + 0.1)

    low_f, high_f = _spread(confidence)
    mid = max(mid, 1.0)

    return ValueEstimate(
        currency=currency,
        retail_estimate=round(retail, 2),
        low=round(max(mid * low_f, 0.5), 2),
        mid=round(mid, 2),
        high=round(mid * high_f, 2),
        confidence=round(confidence, 2),
        factors=factors,
        comparables=comparables,
        notes=notes,
    )
