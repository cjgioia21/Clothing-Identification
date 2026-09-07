"""Identify clothing from its tag and appearance, and estimate a rough value."""

from .models import (
    Comparable,
    FiberContent,
    GarmentRead,
    Identification,
    Report,
    TagRead,
    ValueEstimate,
    ValueFactor,
    VisualRead,
)
from .pipeline import analyze_blocks, analyze_paths, analyze_uploads
from .valuation import estimate_value

__version__ = "0.1.0"

__all__ = [
    "Comparable",
    "FiberContent",
    "GarmentRead",
    "Identification",
    "Report",
    "TagRead",
    "ValueEstimate",
    "ValueFactor",
    "VisualRead",
    "analyze_blocks",
    "analyze_paths",
    "analyze_uploads",
    "estimate_value",
]
