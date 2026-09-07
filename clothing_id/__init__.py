"""Identify clothing from its tag and appearance, and estimate a rough value."""

from .history import Observation, SalesHistory, import_csv
from .market import MarketFetcher
from .models import (
    Comparable,
    FiberContent,
    GarmentRead,
    Identification,
    MarketEvidence,
    Report,
    TagRead,
    Verification,
    ValueEstimate,
    ValueFactor,
    VisualRead,
)
from .pipeline import analyze_blocks, analyze_paths, analyze_uploads
from .rn import verify as verify_rn
from .pricing import MarketBasis, price_from_observations
from .valuation import estimate_value, model_estimate

__version__ = "0.1.0"

__all__ = [
    "Comparable",
    "FiberContent",
    "MarketBasis",
    "MarketEvidence",
    "MarketFetcher",
    "Observation",
    "SalesHistory",
    "GarmentRead",
    "Identification",
    "Report",
    "TagRead",
    "ValueEstimate",
    "ValueFactor",
    "Verification",
    "VisualRead",
    "analyze_blocks",
    "analyze_paths",
    "analyze_uploads",
    "estimate_value",
    "import_csv",
    "model_estimate",
    "price_from_observations",
    "verify_rn",
]
