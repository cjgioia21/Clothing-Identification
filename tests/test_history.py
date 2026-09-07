"""The observation store: real prices in, real prices out."""

from datetime import date, timedelta

import pytest

from clothing_id.history import (
    Observation,
    SalesHistory,
    import_csv,
    observations_from_csv,
    parse_date,
    parse_price,
    size_key,
)
from tests.factories import sold_series


@pytest.fixture
def history():
    store = SalesHistory(":memory:")
    yield store
    store.close()


def test_round_trip(history):
    history.record_many(sold_series([50, 60, 70], brand="Patagonia", category="jacket"))
    rows = history.query(brand="patagonia", category="jacket")
    assert [r.price for r in rows] == [50, 60, 70]
    assert rows[0].kind == "sold"
    assert rows[0].url.startswith("https://")


def test_reimport_does_not_duplicate(history):
    batch = sold_series([50, 60])
    assert history.record_many(batch) == 2
    assert history.record_many(batch) == 0
    assert history.count() == 2


def test_query_filters(history):
    history.record_many(sold_series([10, 20], brand="Gap", size="M"))
    history.record_many(sold_series([30], brand="Gap", size="XL", source="other"))
    assert len(history.query(brand="Gap")) == 3
    assert len(history.query(brand="Gap", size="m")) == 2
    assert len(history.query(brand="Gap", size="large")) == 0
    assert len(history.query(since=date.today() + timedelta(days=1))) == 0


def test_stats_summarize_the_evidence(history):
    history.record_many(sold_series([10, 20], brand="Levi's"))
    history.record_many(sold_series([30], kind="ask", brand="Levi's", source="ebay-active"))
    stats = history.stats()
    assert stats["observations"] == 3
    assert stats["sold"] == 2 and stats["asks"] == 1
    assert stats["by_source"]["ebay-sold"] == 2
    assert "levi s" in stats["top_brands"] or "levis" in stats["top_brands"]


def test_prune_drops_old_rows(history):
    old = Observation("manual", "old", "sold", 25.0, date.today() - timedelta(days=900))
    history.record(old)
    history.record_many(sold_series([10]))
    assert history.prune(older_than_days=365) == 1
    assert history.count() == 1


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-03-04", date(2026, 3, 4)),
        ("2026-03-04T12:30:00.000Z", date(2026, 3, 4)),
        ("03/04/2026", date(2026, 3, 4)),
        ("Mar 4, 2026", date(2026, 3, 4)),
        ("not a date", None),
        ("", None),
    ],
)
def test_date_parsing(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("$1,234.50", 1234.5), ("USD 40.00", 40.0), (40, 40.0), ("", None), ("free", None)],
)
def test_price_parsing(raw, expected):
    assert parse_price(raw) == expected


def test_size_key_collapses_spellings():
    assert size_key("Large") == size_key("L") == "l"
    assert size_key("X-Large") == size_key("XL") == "xl"
    assert size_key(None) == ""


def test_csv_import_reads_a_real_export(tmp_path, history):
    path = tmp_path / "sold.csv"
    path.write_text(
        "Item number,Title,Sold price,Sold date,Brand,Category,Size,Condition\n"
        "1234,Patagonia Snap-T,\"$88.00\",2026-02-14,Patagonia,sweatshirt,M,good\n"
        "1235,Patagonia Baggies,$32.50,02/20/2026,Patagonia,shorts,L,excellent\n"
        "1236,Broken row,,,Patagonia,shorts,L,good\n"
    )
    read, added = import_csv(path, history=history, source="ebay-export")
    assert (read, added) == (2, 2)
    rows = history.query(brand="Patagonia")
    assert {r.price for r in rows} == {88.0, 32.5}
    assert {r.category for r in rows} == {"sweatshirt", "shorts"}
    assert all(r.source == "ebay-export" and r.kind == "sold" for r in rows)


def test_csv_rows_without_price_or_date_are_skipped(tmp_path):
    path = tmp_path / "partial.csv"
    path.write_text("Title,Price,Date\nA,10,2026-01-01\nB,,2026-01-02\nC,15,\n")
    assert len(observations_from_csv(path)) == 1
