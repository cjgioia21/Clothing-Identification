"""Vision pass: read the tags and the garment, then say what the item is."""

from __future__ import annotations

import json
from typing import List, Optional, Sequence

from pydantic import BaseModel, Field

from .models import Comparable, GarmentRead

DEFAULT_MODEL = "claude-opus-5"
MAX_TOKENS = 16000

SYSTEM_PROMPT = """You are a vintage and secondhand clothing authenticator working a \
sorting table. You are given photos of one garment: some show the brand and care tags, \
others show the garment itself.

Work in this order:

1. TAGS. Transcribe every legible word, number and symbol from the tags verbatim into \
`tag.raw_text` - brand, size, fiber content, care, country of origin, RN/CA numbers, \
style and color codes. Never invent text you cannot read; leave fields null instead. \
Note dating clues in `tag.tag_era_hints`: logo variant, font, tag material, the presence \
of a union label, "Made in USA", care-symbol style, copyright year, single vs. multiple tags.

2. GARMENT. Describe what you can see: category, subtype, colors, pattern, silhouette, \
graphics and printed text, construction details (single stitch, chain stitch hem, \
selvedge, taped seams, storm flap), hardware markings (YKK, Talon, Scovill, RiRi), and \
condition. Grade condition honestly against `deadstock/excellent/good/fair/poor` and list \
every flaw you can actually see - stains, holes, pilling, fading, cracked prints, \
missing hardware. If the photos do not show enough to grade, use "unknown".

3. IDENTIFY. Combine both into a single call: brand, sub-label, a short item name a \
reseller would list it under, category, era, and the rarity signals that would matter to \
a buyer (single stitch, made in USA, union label, tour print, collaboration, \
discontinued colorway, deadstock). Set `confidence` to your honest probability that the \
brand and item are right: 0.9+ only when the tag is legible and unambiguous, below 0.4 \
when you are largely guessing from silhouette.

Rules: report only what the images support, prefer null over a guess, and keep \
`reasoning` to a few sentences naming the specific evidence you used."""

COMPS_SYSTEM = """You price secondhand clothing. Search current and recently sold \
listings for the specific item described, on the resale market (eBay sold, Grailed, \
Depop, Poshmark, Vestiaire, StockX). Return up to 8 comparable listings with their \
asking or sold price in USD. Only include listings for the same brand and the same kind \
of garment; skip anything whose price you cannot read. Prefer sold prices over asks."""


class _Comparables(BaseModel):
    comparables: List[Comparable] = Field(default_factory=list)
    search_notes: str = ""


def _client(client=None):
    if client is not None:
        return client
    import anthropic

    return anthropic.Anthropic()


def _guard(response) -> None:
    if getattr(response, "stop_reason", None) == "refusal":
        details = getattr(response, "stop_details", None)
        reason = getattr(details, "explanation", "") if details else ""
        raise RuntimeError(f"The model declined to analyze these images. {reason}".strip())


def identify_garment(
    image_blocks: Sequence[dict],
    client=None,
    model: str = DEFAULT_MODEL,
    notes: Optional[str] = None,
) -> GarmentRead:
    """Run the vision pass over garment photos and return a structured read."""
    if not image_blocks:
        raise ValueError("At least one photo is required.")

    content: List[dict] = list(image_blocks)
    prompt = (
        f"{len(image_blocks)} photo(s) of one garment. Read the tags, describe the item, "
        "and identify it."
    )
    if notes:
        prompt += f"\n\nSeller notes (treat as unverified): {notes}"
    content.append({"type": "text", "text": prompt})

    response = _client(client).messages.parse(
        model=model,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": content}],
        output_format=GarmentRead,
    )
    _guard(response)
    parsed = response.parsed_output
    if parsed is None:
        raise RuntimeError("The model returned no structured output.")
    return parsed


def find_comparables(
    read: GarmentRead,
    client=None,
    model: str = DEFAULT_MODEL,
    max_results: int = 8,
) -> List[Comparable]:
    """Look up live resale comps with the server-side web search tool.

    Returns an empty list if the search finds nothing usable - callers should
    treat comps as an optional anchor, not a requirement.
    """
    ident = read.identification
    query = {
        "brand": ident.brand,
        "sub_label": ident.sub_label,
        "item": ident.item_name,
        "category": ident.category,
        "era": ident.era,
        "size": read.tag.size,
        "color": read.visual.primary_color,
        "condition": read.visual.condition_grade,
        "rarity_signals": ident.rarity_signals,
    }

    response = _client(client).messages.parse(
        model=model,
        max_tokens=MAX_TOKENS,
        system=COMPS_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    "Find resale comparables for this item and report up to "
                    f"{max_results} with prices:\n{json.dumps(query, indent=2)}"
                ),
            }
        ],
        tools=[
            {
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": 5,
            }
        ],
        output_format=_Comparables,
    )
    _guard(response)
    parsed = response.parsed_output
    if parsed is None:
        return []
    return [c for c in parsed.comparables if c.price and c.price > 0][:max_results]
