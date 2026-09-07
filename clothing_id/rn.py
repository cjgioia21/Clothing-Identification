"""Check a tag's RN number against the FTC's registered-identification data.

Every US garment sold with a care label carries either a brand name or an RN
(Registered Identification Number) issued by the FTC to the company responsible
for it. Matching the RN on the tag against the registrant on file is the one
piece of hard, checkable identification a garment carries - it catches relabels,
private-label goods and outright fakes that copy a logo but not a number.

The FTC publishes no bulk file and no public API for the RN database, so this
module reads a directory you supply and never invents an entry. Point it at a
two-column CSV (`rn,company`, extra columns ignored):

    export CLOTHING_ID_RN_FILE=~/rn-directory.csv

Without a directory the lookup returns nothing and the report carries the FTC
search URL for the number so a human can check it:
https://rn.ftc.gov/ - "Search the RN Database"
"""

from __future__ import annotations

import csv
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from .brands import normalize_brand

FTC_SEARCH_URL = "https://rn.ftc.gov/rns"

RN_COLUMNS = ("rn", "rn number", "rn_no", "registered identification number", "number")
COMPANY_COLUMNS = ("company", "company name", "registrant", "legal name", "business name", "name")


def normalize_rn(value: Optional[str]) -> str:
    """Digits only: 'RN# 51884', 'rn 51884' and '51884' are the same number."""
    if not value:
        return ""
    digits = re.sub(r"\D", "", str(value))
    return digits.lstrip("0") or digits


def lookup_url(rn: Optional[str]) -> Optional[str]:
    """A link a person can open to check the number themselves."""
    number = normalize_rn(rn)
    return f"{FTC_SEARCH_URL}?rn={number}" if number else None


def _column(header: list[str], candidates: tuple[str, ...]) -> Optional[str]:
    lowered = {name.strip().lower(): name for name in header if name}
    for candidate in candidates:
        if candidate in lowered:
            return lowered[candidate]
    return None


def load_directory(path: os.PathLike | str) -> Dict[str, str]:
    """Load an RN -> registered company map from a CSV you supply."""
    mapping: Dict[str, str] = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        header = reader.fieldnames or []
        rn_col = _column(header, RN_COLUMNS)
        company_col = _column(header, COMPANY_COLUMNS)
        if not rn_col or not company_col:
            raise ValueError(
                f"{path} needs an RN column ({'/'.join(RN_COLUMNS[:3])}) and a company column "
                f"({'/'.join(COMPANY_COLUMNS[:3])}); found: {', '.join(header)}"
            )
        for row in reader:
            number = normalize_rn(row.get(rn_col))
            company = (row.get(company_col) or "").strip()
            if number and company:
                mapping[number] = company
    return mapping


@lru_cache(maxsize=4)
def _cached_directory(path: str, mtime: float) -> Dict[str, str]:
    return load_directory(path)


def directory_from_env() -> Optional[Dict[str, str]]:
    """Load the directory named by CLOTHING_ID_RN_FILE, if it is set and readable."""
    configured = os.environ.get("CLOTHING_ID_RN_FILE")
    if not configured:
        return None
    path = Path(configured).expanduser()
    if not path.is_file():
        return None
    return _cached_directory(str(path), path.stat().st_mtime)


def verify(
    rn: Optional[str],
    brand: Optional[str],
    directory: Optional[Dict[str, str]] = None,
) -> Dict[str, Optional[object]]:
    """Compare the RN on the tag with the registrant on file.

    Returns a dict with the registrant (when known), whether it matches the
    brand the model read, and a URL for checking the number by hand.
    """
    number = normalize_rn(rn)
    result: Dict[str, Optional[object]] = {
        "rn_number": number or None,
        "registrant": None,
        "brand_matches_rn": None,
        "lookup_url": lookup_url(number),
        "notes": [],
    }
    if not number:
        return result

    directory = directory if directory is not None else directory_from_env()
    if not directory:
        result["notes"].append(
            f"RN {number} not checked: no RN directory configured "
            "(set CLOTHING_ID_RN_FILE to verify against the FTC registry)."
        )
        return result

    registrant = directory.get(number)
    if not registrant:
        result["notes"].append(f"RN {number} is not in the configured RN directory.")
        return result

    result["registrant"] = registrant
    if brand:
        brand_key = normalize_brand(brand)
        registrant_key = normalize_brand(registrant)
        matches = bool(brand_key) and (
            brand_key == registrant_key
            or brand_key in registrant_key
            or registrant_key in brand_key
        )
        result["brand_matches_rn"] = matches
        if matches:
            result["notes"].append(f"RN {number} is registered to {registrant} - brand confirmed.")
        else:
            result["notes"].append(
                f"RN {number} is registered to {registrant}, which does not match the brand "
                f"read from the tag ({brand}). Could be a licensee, a relabel, or a fake."
            )
    return result
