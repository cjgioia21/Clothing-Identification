"""Gathers real observations for one garment and files them into history."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional

from ..history import Observation, SalesHistory
from .ebay import EbayClient, EbayError, ebay_from_env
from .search import search_comparables


@dataclass
class MarketResult:
    observations: List[Observation] = field(default_factory=list)
    sources_used: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    stored: int = 0

    @property
    def sold(self) -> List[Observation]:
        return [o for o in self.observations if o.kind == "sold"]


def build_query(read) -> str:
    """A search string a human would type: brand, line, item, era, size.

    Terms are merged word by word, so "Patagonia" + "Patagonia Snap-T Fleece"
    searches for the item once rather than repeating the brand.
    """
    ident, tag, visual = read.identification, read.tag, read.visual
    parts = [
        ident.brand or tag.brand,
        ident.sub_label or tag.sub_label,
        ident.item_name,
        visual.subtype,
        ident.category if ident.category != "unknown" else None,
    ]
    seen: set[str] = set()
    words: List[str] = []
    for part in parts:
        if not part:
            continue
        for word in str(part).split():
            key = word.lower().strip(",.")
            if key and key not in seen:
                seen.add(key)
                words.append(word)
    return " ".join(words)[:120]


class MarketFetcher:
    """Pulls comparables from every source available, newest evidence first.

    eBay sold data is used when a keyset is configured; otherwise (or in
    addition, when `use_search` is set) the model's web search fills in. Every
    observation is written to the history database, so repeated lookups build a
    local record of what things actually sell for.
    """

    def __init__(
        self,
        history: Optional[SalesHistory] = None,
        ebay: Optional[EbayClient] = None,
        client=None,
        model: str = "claude-opus-5",
    ):
        self.history = history if history is not None else SalesHistory()
        self.ebay = ebay if ebay is not None else ebay_from_env()
        self.client = client
        self.model = model

    def fetch(self, read, limit: int = 50, use_search: bool = True) -> MarketResult:
        query = build_query(read)
        result = MarketResult()
        condition = read.visual.condition_grade
        condition = condition if condition != "unknown" else None

        if self.ebay is not None:
            try:
                sold = self.ebay.sold_comps(query, condition_grade=condition, limit=limit)
                result.observations.extend(sold)
                result.sources_used.append(f"ebay-sold ({len(sold)})")
            except EbayError as exc:
                result.errors.append(f"eBay sold search unavailable: {exc}")
            try:
                asks = self.ebay.active_comps(query, condition_grade=condition, limit=limit)
                result.observations.extend(asks)
                result.sources_used.append(f"ebay-active ({len(asks)})")
            except EbayError as exc:
                result.errors.append(f"eBay active search unavailable: {exc}")

        if use_search and not [o for o in result.observations if o.kind == "sold"]:
            try:
                found = search_comparables(
                    {
                        "brand": read.identification.brand or read.tag.brand,
                        "sub_label": read.identification.sub_label,
                        "item": read.identification.item_name,
                        "category": read.identification.category,
                        "era": read.identification.era,
                        "size": read.tag.size,
                        "color": read.visual.primary_color,
                        "condition": read.visual.condition_grade,
                        "rarity_signals": read.identification.rarity_signals,
                        "query": query,
                    },
                    client=self.client,
                    model=self.model,
                )
                result.observations.extend(found)
                result.sources_used.append(f"web-search ({len(found)})")
            except Exception as exc:
                result.errors.append(f"Web search unavailable: {exc}")

        if result.observations:
            result.stored = self.history.record_many(result.observations)
        return result

    def known_history(self, read, days: int = 1460, limit: int = 400) -> List[Observation]:
        """Everything already on file for this brand/category, newest first."""
        brand = read.identification.brand or read.tag.brand
        category = read.identification.category
        if category == "unknown":
            category = read.visual.category
        rows = self.history.query(
            brand=brand,
            category=category if category != "unknown" else None,
            since=date.today() - timedelta(days=days),
            limit=limit,
        )
        if not rows and brand:
            rows = self.history.query(
                brand=brand, since=date.today() - timedelta(days=days), limit=limit
            )
        return rows
