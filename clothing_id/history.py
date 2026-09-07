"""Local store of real price observations.

Every price this tool has ever seen - imported from your own sales records or
pulled from a marketplace API - lands here with its source, its URL and the
date it happened. Valuations are computed from these rows, so an estimate can
always be traced back to specific transactions.

    from clothing_id.history import SalesHistory, Observation
    history = SalesHistory()                    # ~/.clothing-id/history.db
    history.record_many(observations)
    rows = history.query(brand="patagonia", category="jacket")
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

from .brands import normalize_brand

SCHEMA_VERSION = 1

DEFAULT_DB = Path(
    os.environ.get("CLOTHING_ID_HOME", Path.home() / ".clothing-id")
) / "history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('sold', 'ask')),
    brand_key     TEXT NOT NULL,
    brand         TEXT,
    category      TEXT,
    subtype       TEXT,
    size          TEXT,
    size_key      TEXT,
    condition_grade TEXT,
    era           TEXT,
    title         TEXT,
    price         REAL NOT NULL,
    currency      TEXT NOT NULL DEFAULT 'USD',
    observed_on   TEXT NOT NULL,
    captured_at   TEXT NOT NULL,
    url           TEXT,
    raw           TEXT,
    UNIQUE (source, source_id)
);
CREATE INDEX IF NOT EXISTS idx_obs_brand_cat ON observations (brand_key, category);
CREATE INDEX IF NOT EXISTS idx_obs_observed ON observations (observed_on);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _today() -> date:
    return datetime.now(timezone.utc).date()


def parse_date(value: object) -> Optional[date]:
    """Accept ISO dates, ISO timestamps (eBay style) and common US formats."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d %b %Y", "%b %d, %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_price(value: object) -> Optional[float]:
    """Pull a number out of '$1,234.50', 'USD 40.00', 40, '40.00'."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = "".join(c for c in str(value) if c.isdigit() or c in ".-")
    cleaned = cleaned.replace("-", "")
    try:
        price = float(cleaned)
    except ValueError:
        return None
    return price if price > 0 else None


def size_key(size: Optional[str]) -> str:
    """Collapse size spellings so 'Large', 'L', 'lg' compare equal."""
    if not size:
        return ""
    text = "".join(c for c in str(size).lower() if c.isalnum())
    aliases = {
        "small": "s", "medium": "m", "large": "l", "lg": "l", "med": "m", "sm": "s",
        "xlarge": "xl", "extralarge": "xl", "xxlarge": "xxl", "xxxl": "3xl",
        "xxxxl": "4xl", "xsmall": "xs", "extrasmall": "xs",
    }
    return aliases.get(text, text)


@dataclass
class Observation:
    """One real price seen at one point in time."""

    source: str  # 'ebay-sold', 'ebay-active', 'web-search', 'manual', ...
    source_id: str  # stable id within that source; dedupes re-imports
    kind: str  # 'sold' (a transaction) or 'ask' (a listing price)
    price: float
    observed_on: date
    brand: Optional[str] = None
    category: Optional[str] = None
    subtype: Optional[str] = None
    size: Optional[str] = None
    condition_grade: Optional[str] = None
    era: Optional[str] = None
    title: str = ""
    currency: str = "USD"
    url: Optional[str] = None
    raw: Dict = field(default_factory=dict)

    @property
    def brand_key(self) -> str:
        return normalize_brand(self.brand)

    @property
    def age_days(self) -> int:
        return max((_today() - self.observed_on).days, 0)

    def to_row(self) -> tuple:
        return (
            self.source,
            self.source_id,
            self.kind,
            self.brand_key,
            self.brand,
            self.category,
            self.subtype,
            self.size,
            size_key(self.size),
            self.condition_grade,
            self.era,
            self.title,
            float(self.price),
            self.currency,
            self.observed_on.isoformat(),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            self.url,
            json.dumps(self.raw, default=str) if self.raw else None,
        )

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Observation":
        return cls(
            source=row["source"],
            source_id=row["source_id"],
            kind=row["kind"],
            price=row["price"],
            observed_on=parse_date(row["observed_on"]) or _today(),
            brand=row["brand"],
            category=row["category"],
            subtype=row["subtype"],
            size=row["size"],
            condition_grade=row["condition_grade"],
            era=row["era"],
            title=row["title"] or "",
            currency=row["currency"],
            url=row["url"],
            raw=json.loads(row["raw"]) if row["raw"] else {},
        )

    def as_dict(self) -> Dict:
        data = asdict(self)
        data["observed_on"] = self.observed_on.isoformat()
        return data


class SalesHistory:
    """SQLite-backed store of observed prices."""

    def __init__(self, path: os.PathLike | str | None = None):
        self.path = Path(path) if path else DEFAULT_DB
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SalesHistory":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- writing -----------------------------------------------------------

    def record_many(self, observations: Iterable[Observation]) -> int:
        """Insert observations, ignoring ones already stored. Returns new rows."""
        rows = [o.to_row() for o in observations if o.price and o.price > 0]
        if not rows:
            return 0
        before = self.count()
        self._conn.executemany(
            """INSERT OR IGNORE INTO observations
               (source, source_id, kind, brand_key, brand, category, subtype, size,
                size_key, condition_grade, era, title, price, currency, observed_on,
                captured_at, url, raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
        self._conn.commit()
        return self.count() - before

    def record(self, observation: Observation) -> int:
        return self.record_many([observation])

    # --- reading -----------------------------------------------------------

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM observations").fetchone()["n"]

    def query(
        self,
        brand: Optional[str] = None,
        category: Optional[str] = None,
        size: Optional[str] = None,
        condition_grade: Optional[str] = None,
        era: Optional[str] = None,
        kind: Optional[str] = None,
        since: Optional[date] = None,
        limit: int = 400,
    ) -> List[Observation]:
        """Fetch observations matching the given constraints (all optional)."""
        clauses: List[str] = []
        params: List[object] = []
        if brand:
            clauses.append("brand_key = ?")
            params.append(normalize_brand(brand))
        if category:
            clauses.append("category = ?")
            params.append(category)
        if size:
            clauses.append("size_key = ?")
            params.append(size_key(size))
        if condition_grade:
            clauses.append("condition_grade = ?")
            params.append(condition_grade)
        if era:
            clauses.append("era = ?")
            params.append(era)
        if kind:
            clauses.append("kind = ?")
            params.append(kind)
        if since:
            clauses.append("observed_on >= ?")
            params.append(since.isoformat())
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM observations {where} ORDER BY observed_on DESC LIMIT ?"
        params.append(limit)
        return [Observation.from_row(r) for r in self._conn.execute(sql, params)]

    def stats(self) -> Dict:
        row = self._conn.execute(
            """SELECT COUNT(*) AS n,
                      MIN(observed_on) AS first_seen,
                      MAX(observed_on) AS last_seen,
                      SUM(kind = 'sold') AS sold,
                      SUM(kind = 'ask') AS asks
               FROM observations"""
        ).fetchone()
        by_source = {
            r["source"]: r["n"]
            for r in self._conn.execute(
                "SELECT source, COUNT(*) AS n FROM observations GROUP BY source ORDER BY n DESC"
            )
        }
        top_brands = {
            r["brand_key"]: r["n"]
            for r in self._conn.execute(
                """SELECT brand_key, COUNT(*) AS n FROM observations
                   WHERE brand_key != '' GROUP BY brand_key ORDER BY n DESC LIMIT 15"""
            )
        }
        return {
            "observations": row["n"],
            "sold": row["sold"] or 0,
            "asks": row["asks"] or 0,
            "first_seen": row["first_seen"],
            "last_seen": row["last_seen"],
            "by_source": by_source,
            "top_brands": top_brands,
            "database": str(self.path),
        }

    def prune(self, older_than_days: int) -> int:
        """Drop observations older than N days. Returns rows removed."""
        cutoff = (_today() - timedelta(days=older_than_days)).isoformat()
        cur = self._conn.execute("DELETE FROM observations WHERE observed_on < ?", (cutoff,))
        self._conn.commit()
        return cur.rowcount


# --- CSV import ------------------------------------------------------------

# Column names accepted for each field, lowercased. Covers eBay sold-listing
# exports, Poshmark/Depop sales reports and hand-kept spreadsheets.
CSV_FIELDS: Dict[str, Sequence[str]] = {
    "price": ("price", "sold price", "sale price", "total", "item price", "sold for", "amount"),
    "observed_on": ("date", "sold date", "sale date", "date sold", "order date", "last sold date"),
    "brand": ("brand", "make", "manufacturer", "label"),
    "category": ("category", "type", "item type", "garment"),
    "size": ("size",),
    "condition_grade": ("condition", "grade", "condition grade"),
    "era": ("era", "decade", "year"),
    "title": ("title", "item title", "name", "description", "listing"),
    "url": ("url", "link", "item url", "listing url"),
    "currency": ("currency",),
    "source_id": ("id", "item id", "item number", "order id", "listing id", "sku"),
    "kind": ("kind", "status"),
}


def _pick(row: Dict[str, str], names: Sequence[str]) -> Optional[str]:
    for name in names:
        for key, value in row.items():
            if key and key.strip().lower() == name and str(value).strip():
                return str(value).strip()
    return None


def observations_from_csv(
    path: os.PathLike | str,
    source: str = "import",
    default_kind: str = "sold",
) -> List[Observation]:
    """Read a sales export into observations, skipping rows without a price or date.

    Column names are matched case-insensitively against common export headers,
    so eBay and Poshmark reports usually import without remapping.
    """
    observations: List[Observation] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            price = parse_price(_pick(row, CSV_FIELDS["price"]))
            observed_on = parse_date(_pick(row, CSV_FIELDS["observed_on"]))
            if price is None or observed_on is None:
                continue
            kind_raw = (_pick(row, CSV_FIELDS["kind"]) or default_kind).lower()
            kind = "sold" if kind_raw.startswith(("sold", "complete", "paid")) else (
                "ask" if kind_raw.startswith(("ask", "active", "listed")) else default_kind
            )
            source_id = _pick(row, CSV_FIELDS["source_id"]) or f"{Path(path).name}:{index}"
            observations.append(
                Observation(
                    source=source,
                    source_id=source_id,
                    kind=kind,
                    price=price,
                    observed_on=observed_on,
                    brand=_pick(row, CSV_FIELDS["brand"]),
                    category=(_pick(row, CSV_FIELDS["category"]) or "").lower() or None,
                    size=_pick(row, CSV_FIELDS["size"]),
                    condition_grade=(_pick(row, CSV_FIELDS["condition_grade"]) or "").lower()
                    or None,
                    era=_pick(row, CSV_FIELDS["era"]),
                    title=_pick(row, CSV_FIELDS["title"]) or "",
                    currency=_pick(row, CSV_FIELDS["currency"]) or "USD",
                    url=_pick(row, CSV_FIELDS["url"]),
                    raw=dict(row),
                )
            )
    return observations


def import_csv(
    path: os.PathLike | str,
    history: Optional[SalesHistory] = None,
    source: str = "import",
    default_kind: str = "sold",
) -> tuple[int, int]:
    """Import a CSV of real sales. Returns (rows read, rows newly stored)."""
    observations = observations_from_csv(path, source=source, default_kind=default_kind)
    store = history or SalesHistory()
    try:
        added = store.record_many(observations)
    finally:
        if history is None:
            store.close()
    return len(observations), added
