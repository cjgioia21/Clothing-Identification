"""Data models for tag reading, visual reading, identification and valuation."""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

Category = Literal[
    "t-shirt",
    "shirt",
    "polo",
    "sweatshirt",
    "hoodie",
    "sweater",
    "cardigan",
    "jacket",
    "coat",
    "blazer",
    "suit",
    "vest",
    "jeans",
    "pants",
    "shorts",
    "skirt",
    "dress",
    "jumpsuit",
    "activewear",
    "swimwear",
    "underwear",
    "sleepwear",
    "shoes",
    "boots",
    "sneakers",
    "bag",
    "hat",
    "scarf",
    "belt",
    "gloves",
    "accessory",
    "unknown",
]

ConditionGrade = Literal[
    "deadstock",  # new with tags, unworn
    "excellent",  # worn a few times, no flaws
    "good",  # light wear, minor flaws
    "fair",  # obvious wear, repairable flaws
    "poor",  # damaged, sold for parts or heavy discount
    "unknown",
]

Method = Literal["observed", "blended", "modeled"]

Era = Literal[
    "pre-1970",
    "1970s",
    "1980s",
    "1990s",
    "2000s",
    "2010s",
    "2020s",
    "unknown",
]


class FiberContent(BaseModel):
    fiber: str = Field(description="Fiber name as printed, e.g. cotton, merino wool, cashmere")
    percent: Optional[float] = Field(
        default=None, description="Percentage of the garment, 0-100, null if not printed"
    )


class TagRead(BaseModel):
    """Everything readable from the care/brand tags."""

    brand: Optional[str] = Field(default=None, description="Brand name printed on the tag")
    sub_label: Optional[str] = Field(
        default=None, description="Diffusion line or sub-label, e.g. 'Polo Sport', 'Nike ACG'"
    )
    size: Optional[str] = None
    size_system: Optional[str] = Field(
        default=None, description="US, UK, EU, JP, alpha, numeric or null"
    )
    fiber_content: List[FiberContent] = Field(default_factory=list)
    care_instructions: List[str] = Field(default_factory=list)
    country_of_origin: Optional[str] = None
    rn_number: Optional[str] = Field(default=None, description="US FTC RN number, digits only")
    ca_number: Optional[str] = None
    style_number: Optional[str] = None
    color_name: Optional[str] = None
    union_label: bool = Field(
        default=False, description="True if an ILGWU/union-made label is visible"
    )
    tag_era_hints: List[str] = Field(
        default_factory=list,
        description="Dating clues from the tag itself: logo variant, font, 'Made in USA', "
        "single-line care symbols, copyright year, etc.",
    )
    raw_text: str = Field(default="", description="Verbatim transcription of all tag text")
    legible: bool = Field(default=True, description="False when tags are missing or unreadable")


class VisualRead(BaseModel):
    """Everything inferable from photos of the garment itself."""

    category: Category = "unknown"
    subtype: Optional[str] = Field(
        default=None, description="More specific type, e.g. 'chore coat', 'raglan crewneck'"
    )
    primary_color: Optional[str] = None
    secondary_colors: List[str] = Field(default_factory=list)
    pattern: Optional[str] = Field(default=None, description="solid, striped, plaid, camo, ...")
    silhouette: Optional[str] = Field(default=None, description="boxy, slim, oversized, cropped")
    graphics_text: List[str] = Field(
        default_factory=list, description="Printed/embroidered graphics, team names, tour dates"
    )
    construction_details: List[str] = Field(
        default_factory=list,
        description="single stitch, chain stitch hem, selvedge, talon zipper, "
        "storm flap, taped seams, contrast stitching",
    )
    hardware: List[str] = Field(default_factory=list, description="Zipper/button brand markings")
    condition_grade: ConditionGrade = "unknown"
    flaws: List[str] = Field(default_factory=list, description="stains, holes, pilling, fading")
    estimated_era: Era = "unknown"


class Identification(BaseModel):
    """The model's consolidated read of what the item is."""

    brand: Optional[str] = None
    sub_label: Optional[str] = None
    item_name: str = Field(description="Short human label, e.g. \"Patagonia Synchilla Snap-T\"")
    category: Category = "unknown"
    era: Era = "unknown"
    likely_collaboration: Optional[str] = None
    rarity_signals: List[str] = Field(
        default_factory=list,
        description="Traits that raise collector demand: single stitch, made in USA, "
        "union label, discontinued colorway, band tour print, collab, deadstock",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning: str = ""


class GarmentRead(BaseModel):
    """Full structured output returned by the vision pass."""

    tag: TagRead = Field(default_factory=TagRead)
    visual: VisualRead = Field(default_factory=VisualRead)
    identification: Identification


class ValueFactor(BaseModel):
    name: str
    multiplier: float
    note: str = ""


class Comparable(BaseModel):
    """A real listing the estimate was built from."""

    title: str
    price: Optional[float] = None
    source: Optional[str] = Field(default=None, description="ebay-sold, web-search, import, ...")
    url: Optional[str] = None
    sold: bool = Field(default=False, description="True for a completed sale, False for an ask")
    observed_on: Optional[str] = Field(default=None, description="Date of the sale or listing")
    condition: Optional[str] = None
    size: Optional[str] = None


class MarketEvidence(BaseModel):
    """What the market data behind an estimate actually consisted of."""

    observation_count: int = 0
    sold_count: int = 0
    ask_count: int = 0
    effective_n: float = Field(
        default=0.0, description="Sample size after recency and evidence-quality weighting"
    )
    first_observed: Optional[str] = None
    last_observed: Optional[str] = None
    raw_median: float = 0.0
    dispersion: float = Field(default=0.0, description="(p80 - p20) / mid of the sample")
    annual_trend: Optional[float] = Field(
        default=None, description="Fitted price drift per year, e.g. -0.08 = down 8%/yr"
    )
    condition_ratios_source: str = "priors"
    ask_ratio: float = 0.82
    ask_ratio_source: str = "prior"
    outliers_dropped: int = 0
    sources: Dict[str, int] = Field(default_factory=dict)


class ValueEstimate(BaseModel):
    currency: str = "USD"
    method: Method = Field(
        default="modeled",
        description="observed = priced from real sales; blended = thin data plus the "
        "model; modeled = no market data was available",
    )
    retail_estimate: float = Field(description="Estimated original/new retail price")
    low: float
    mid: float
    high: float
    confidence: float = Field(ge=0.0, le=1.0)
    market_price: Optional[float] = Field(
        default=None, description="Price implied by observed sales alone"
    )
    model_price: Optional[float] = Field(
        default=None, description="Price implied by the heuristic model alone"
    )
    evidence: Optional[MarketEvidence] = None
    factors: List[ValueFactor] = Field(default_factory=list)
    comparables: List[Comparable] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class Verification(BaseModel):
    """Hard checks against outside records, not model judgement."""

    rn_number: Optional[str] = None
    registrant: Optional[str] = Field(
        default=None, description="Company the RN is registered to, per the RN directory"
    )
    brand_matches_rn: Optional[bool] = Field(
        default=None, description="None when the RN could not be checked"
    )
    lookup_url: Optional[str] = Field(
        default=None, description="FTC RN database URL for checking the number by hand"
    )
    notes: List[str] = Field(default_factory=list)


class Report(BaseModel):
    identification: Identification
    tag: TagRead
    visual: VisualRead
    value: ValueEstimate
    verification: Verification = Field(default_factory=Verification)

    def summary(self) -> str:
        v = self.value
        ident = self.identification
        bits = [
            f"{ident.item_name}",
            f"category: {ident.category}",
            f"era: {ident.era}",
            f"condition: {self.visual.condition_grade}",
            f"size: {self.tag.size or 'unknown'}",
            f"estimated resale: ${v.low:,.0f}-${v.high:,.0f} (mid ${v.mid:,.0f} {v.currency})",
            f"basis: {v.method}"
            + (
                f" on {v.evidence.observation_count} listings"
                if v.evidence and v.evidence.observation_count
                else ""
            ),
        ]
        return " | ".join(bits)
