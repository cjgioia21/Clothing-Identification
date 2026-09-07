"""End-to-end: photos in, identification + value estimate out."""

from __future__ import annotations

import os
from typing import Iterable, List, Optional, Sequence

from .identify import DEFAULT_MODEL, find_comparables, identify_garment
from .images import load_images, prepare_bytes
from .models import Comparable, GarmentRead, Report
from .valuation import estimate_value


def analyze_blocks(
    image_blocks: Sequence[dict],
    client=None,
    model: str = DEFAULT_MODEL,
    notes: Optional[str] = None,
    market_check: bool = False,
    currency: str = "USD",
) -> Report:
    """Identify and price a garment from prepared image blocks."""
    read: GarmentRead = identify_garment(image_blocks, client=client, model=model, notes=notes)

    comps: List[Comparable] = []
    if market_check:
        try:
            comps = find_comparables(read, client=client, model=model)
        except Exception as exc:  # a failed search must not sink the estimate
            comps = []
            market_error = f"Market lookup failed: {exc}"
        else:
            market_error = None
    else:
        market_error = None

    value = estimate_value(read, comparables=comps, currency=currency)
    if market_error:
        value.notes.append(market_error)
    elif market_check and not comps:
        value.notes.append("No usable resale comparables found; estimate is model-based only.")

    return Report(
        identification=read.identification,
        tag=read.tag,
        visual=read.visual,
        value=value,
    )


def analyze_paths(
    paths: Iterable[os.PathLike | str],
    client=None,
    model: str = DEFAULT_MODEL,
    notes: Optional[str] = None,
    market_check: bool = False,
    currency: str = "USD",
) -> Report:
    """Identify and price a garment from image file paths."""
    return analyze_blocks(
        load_images(paths),
        client=client,
        model=model,
        notes=notes,
        market_check=market_check,
        currency=currency,
    )


def analyze_uploads(
    files: Sequence[tuple[bytes, str]],
    client=None,
    model: str = DEFAULT_MODEL,
    notes: Optional[str] = None,
    market_check: bool = False,
    currency: str = "USD",
) -> Report:
    """Identify and price a garment from in-memory uploads of (bytes, media_type)."""
    blocks = [prepare_bytes(data, media_type) for data, media_type in files]
    return analyze_blocks(
        blocks,
        client=client,
        model=model,
        notes=notes,
        market_check=market_check,
        currency=currency,
    )
