"""Sample reads used by the tests."""

from datetime import date, timedelta
from typing import List

from clothing_id.history import Observation
from clothing_id.models import (
    FiberContent,
    GarmentRead,
    Identification,
    TagRead,
    VisualRead,
)


def make_read(**overrides) -> GarmentRead:
    """A plain mid-tier garment read, tweakable per test."""
    tag = TagRead(
        brand="Gap",
        size="M",
        fiber_content=[FiberContent(fiber="cotton", percent=100)],
        country_of_origin="Vietnam",
        raw_text="GAP / M / 100% COTTON / MADE IN VIETNAM",
    )
    visual = VisualRead(
        category="t-shirt",
        primary_color="navy",
        condition_grade="good",
        estimated_era="2010s",
    )
    ident = Identification(
        brand="Gap",
        item_name="Gap pocket tee",
        category="t-shirt",
        era="2010s",
        confidence=0.8,
    )
    read = GarmentRead(tag=tag, visual=visual, identification=ident)
    for field, value in overrides.items():
        setattr(read, field, value)
    return read


def sold_series(
    prices: List[float],
    kind: str = "sold",
    brand: str = "Gap",
    category: str = "t-shirt",
    condition_grade: str = "good",
    size: str = "M",
    spacing_days: int = 10,
    source: str = "ebay-sold",
) -> List[Observation]:
    """Real-looking observations: one price per listing, spaced back through time."""
    today = date.today()
    return [
        Observation(
            source=source,
            source_id=f"{source}-{index}-{price}",
            kind=kind,
            price=float(price),
            observed_on=today - timedelta(days=spacing_days * index),
            brand=brand,
            category=category,
            size=size,
            condition_grade=condition_grade,
            title=f"{brand} {category}",
            url=f"https://example.com/item/{index}",
        )
        for index, price in enumerate(prices)
    ]
