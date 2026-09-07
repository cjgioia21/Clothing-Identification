"""Web-search fallback for resale comps, used when eBay credentials are absent.

Weaker than the API path - the model reports what it read on the results pages -
so every row must carry a source URL and a price, and anything without them is
dropped rather than guessed at. Results are recorded with source 'web-search'
so a valuation can say how much of its evidence came from here.
"""

from __future__ import annotations

import json
from datetime import date
from typing import List, Optional

from pydantic import BaseModel, Field

from ..history import Observation, parse_date

SYSTEM = """You look up secondhand clothing prices. Search the resale market \
(eBay sold listings, Grailed, Depop, Poshmark, Vestiaire, StockX) for the exact item \
described and report individual listings you actually saw in the results.

Hard rules:
- Report only listings you actually found. Never estimate, average, or invent a price.
- Every row needs the listing URL you read it on and its price in USD.
- Mark `sold` true only when the listing shows a completed sale; an asking price is \
`sold` false.
- Give `sold_on` as the date shown on the listing (YYYY-MM-DD) and leave it null if \
none is shown - do not substitute today's date.
- Skip anything that is a different brand, a different garment type, or a bulk lot.
- Returning an empty list is the correct answer when the market has no comparable \
listings."""


class Listing(BaseModel):
    title: str
    price: float = Field(description="Price in USD, numbers only")
    url: str = Field(description="URL of the listing this price was read from")
    marketplace: str = ""
    sold: bool = False
    sold_on: Optional[str] = Field(default=None, description="YYYY-MM-DD as shown, else null")
    condition: Optional[str] = None
    size: Optional[str] = None


class _Listings(BaseModel):
    listings: List[Listing] = Field(default_factory=list)
    query_used: str = ""


def search_comparables(
    description: dict,
    client=None,
    model: str = "claude-opus-5",
    max_results: int = 12,
) -> List[Observation]:
    """Search the open web for comparable listings and return them as observations."""
    if client is None:
        import anthropic

        client = anthropic.Anthropic()

    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Find up to {max_results} resale listings for this item:\n"
                    f"{json.dumps(description, indent=2, default=str)}"
                ),
            }
        ],
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}],
        output_format=_Listings,
    )
    if getattr(response, "stop_reason", None) == "refusal":
        return []
    parsed = response.parsed_output
    if parsed is None:
        return []

    observations: List[Observation] = []
    for listing in parsed.listings[:max_results]:
        if not listing.url or not listing.price or listing.price <= 0:
            continue  # unusable without a checkable source
        observations.append(
            Observation(
                source="web-search",
                source_id=listing.url,
                kind="sold" if listing.sold else "ask",
                price=float(listing.price),
                observed_on=parse_date(listing.sold_on) or date.today(),
                brand=description.get("brand"),
                category=description.get("category"),
                size=listing.size or description.get("size"),
                condition_grade=(listing.condition or "").lower() or None,
                title=listing.title,
                url=listing.url,
                raw={
                    "marketplace": listing.marketplace,
                    "date_shown": listing.sold_on,
                    "query": parsed.query_used,
                },
            )
        )
    return observations
