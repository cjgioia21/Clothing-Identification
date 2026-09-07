"""Sample reads used by the tests."""

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
