"""End-to-end: photos in, identification and a data-backed value estimate out.

Pricing evidence is gathered in two passes before anything is estimated:

1. **History** - every comparable sale already recorded in the local database
   (your own past sales, imported marketplace exports, anything a previous run
   fetched). This works offline and is the tool's long memory.
2. **Live market** - eBay sold and active listings when a keyset is configured,
   otherwise a cited web search. Everything fetched is written back into the
   history database, so the evidence base grows with use.
"""

from __future__ import annotations

import os
from typing import Iterable, List, Optional, Sequence

from .history import Observation, SalesHistory
from .identify import DEFAULT_MODEL, identify_garment
from .images import load_images, prepare_bytes
from .market import MarketFetcher
from .models import GarmentRead, Report, Verification
from .rn import verify
from .valuation import estimate_value


def _dedupe(observations: Iterable[Observation]) -> List[Observation]:
    seen = set()
    unique: List[Observation] = []
    for obs in observations:
        key = (obs.source, obs.source_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(obs)
    return unique


def gather_observations(
    read: GarmentRead,
    fetcher: MarketFetcher,
    market: bool = True,
) -> tuple[List[Observation], List[str], List[str]]:
    """Collect stored history plus, optionally, fresh market data.

    Returns (observations, sources used, problems worth reporting).
    """
    sources: List[str] = []
    problems: List[str] = []

    stored = fetcher.known_history(read)
    if stored:
        sources.append(f"history ({len(stored)})")

    fetched: List[Observation] = []
    if market:
        result = fetcher.fetch(read)
        fetched = result.observations
        sources.extend(result.sources_used)
        problems.extend(result.errors)
        if result.stored:
            sources.append(f"{result.stored} new record(s) saved to history")

    return _dedupe(list(fetched) + list(stored)), sources, problems


def analyze_blocks(
    image_blocks: Sequence[dict],
    client=None,
    model: str = DEFAULT_MODEL,
    notes: Optional[str] = None,
    market: bool = True,
    history: Optional[SalesHistory] = None,
    fetcher: Optional[MarketFetcher] = None,
    currency: str = "USD",
) -> Report:
    """Identify and price a garment from prepared image blocks."""
    read: GarmentRead = identify_garment(image_blocks, client=client, model=model, notes=notes)

    fetcher = fetcher or MarketFetcher(history=history, client=client, model=model)
    observations, sources, problems = gather_observations(read, fetcher, market=market)

    value = estimate_value(read, observations=observations, currency=currency)
    if sources:
        value.notes.append("Evidence: " + "; ".join(sources) + ".")
    value.notes.extend(problems)

    checked = verify(read.tag.rn_number, read.identification.brand or read.tag.brand)
    verification = Verification(
        rn_number=checked["rn_number"],
        registrant=checked["registrant"],
        brand_matches_rn=checked["brand_matches_rn"],
        lookup_url=checked["lookup_url"],
        notes=list(checked["notes"]),
    )
    if verification.brand_matches_rn is False:
        value.confidence = round(value.confidence * 0.8, 2)

    return Report(
        identification=read.identification,
        tag=read.tag,
        visual=read.visual,
        value=value,
        verification=verification,
    )


def analyze_paths(
    paths: Iterable[os.PathLike | str],
    client=None,
    model: str = DEFAULT_MODEL,
    notes: Optional[str] = None,
    market: bool = True,
    history: Optional[SalesHistory] = None,
    fetcher: Optional[MarketFetcher] = None,
    currency: str = "USD",
) -> Report:
    """Identify and price a garment from image file paths."""
    return analyze_blocks(
        load_images(paths),
        client=client,
        model=model,
        notes=notes,
        market=market,
        history=history,
        fetcher=fetcher,
        currency=currency,
    )


def analyze_uploads(
    files: Sequence[tuple[bytes, str]],
    client=None,
    model: str = DEFAULT_MODEL,
    notes: Optional[str] = None,
    market: bool = True,
    history: Optional[SalesHistory] = None,
    fetcher: Optional[MarketFetcher] = None,
    currency: str = "USD",
) -> Report:
    """Identify and price a garment from in-memory uploads of (bytes, media_type)."""
    blocks = [prepare_bytes(data, media_type) for data, media_type in files]
    return analyze_blocks(
        blocks,
        client=client,
        model=model,
        notes=notes,
        market=market,
        history=history,
        fetcher=fetcher,
        currency=currency,
    )
