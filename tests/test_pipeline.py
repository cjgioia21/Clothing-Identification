"""Pipeline tests with a stubbed Anthropic client - no network, no API key."""

import base64
import io
import json

import pytest

from clothing_id import cli
from clothing_id.images import ImageError, load_images, prepare_bytes
from clothing_id.history import SalesHistory
from clothing_id.market import MarketFetcher
from clothing_id.models import GarmentRead
from clothing_id.pipeline import analyze_blocks, analyze_paths, analyze_uploads
from tests.factories import make_read, sold_series


class StubResponse:
    def __init__(self, parsed, stop_reason="end_turn", stop_details=None):
        self.parsed_output = parsed
        self.stop_reason = stop_reason
        self.stop_details = stop_details


class StubMessages:
    """Returns the garment read first, then any web-search listings."""

    def __init__(self, read, listings=None, fail_search=False):
        self.read = read
        self.listings = listings or []
        self.fail_search = fail_search
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["output_format"] is GarmentRead:
            return StubResponse(self.read)
        if self.fail_search:
            raise RuntimeError("search unavailable")
        model = kwargs["output_format"]
        return StubResponse(model(listings=self.listings, query_used="q"))


class StubClient:
    def __init__(self, *args, **kwargs):
        self.messages = StubMessages(*args, **kwargs)


def png_bytes(size=(40, 40)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, (90, 110, 130)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def blocks():
    return [prepare_bytes(png_bytes(), "image/png")]


@pytest.fixture
def history():
    store = SalesHistory(":memory:")
    yield store
    store.close()


def offline_fetcher(history):
    """A fetcher with no live sources - stored history only."""
    return MarketFetcher(history=history, ebay=None)


def test_analyze_returns_identification_and_value(blocks, history):
    client = StubClient(make_read())
    report = analyze_blocks(blocks, client=client, market=False, fetcher=offline_fetcher(history))
    assert report.identification.item_name == "Gap pocket tee"
    assert report.value.mid > 0
    assert report.value.method == "modeled"
    assert len(client.messages.calls) == 1  # no market call when offline


def test_stored_history_prices_the_item_without_any_network(blocks, history):
    history.record_many(sold_series([40, 44, 38, 42, 45, 41], brand="Gap", category="t-shirt"))
    client = StubClient(make_read())
    report = analyze_blocks(blocks, client=client, market=False, fetcher=offline_fetcher(history))
    assert report.value.method == "observed"
    assert 35 <= report.value.mid <= 48
    assert report.value.evidence.observation_count == 6
    assert len(client.messages.calls) == 1  # identification only
    assert any("history (6)" in n for n in report.value.notes)


def test_web_search_listings_become_evidence_and_are_stored(blocks, history):
    listings = [
        {
            "title": f"Gap pocket tee {i}",
            "price": 40 + i,
            "url": f"https://www.ebay.com/itm/{i}",
            "sold": True,
            "sold_on": "2026-08-01",
            "marketplace": "eBay",
        }
        for i in range(6)
    ]
    client = StubClient(make_read(), listings=listings)
    report = analyze_blocks(
        blocks, client=client, fetcher=MarketFetcher(history=history, ebay=None, client=client)
    )
    assert len(client.messages.calls) == 2  # identify, then search
    assert report.value.method == "observed"
    assert report.value.evidence.sources == {"web-search": 6}
    assert history.count() == 6  # evidence kept for next time
    assert all(c.url for c in report.value.comparables)


def test_failed_market_lookup_does_not_sink_the_estimate(blocks, history):
    client = StubClient(make_read(), fail_search=True)
    report = analyze_blocks(
        blocks, client=client, fetcher=MarketFetcher(history=history, ebay=None, client=client)
    )
    assert report.value.mid > 0
    assert report.value.method == "modeled"
    assert any("Web search unavailable" in n for n in report.value.notes)


def test_seller_notes_reach_the_prompt(blocks, history):
    client = StubClient(make_read())
    analyze_blocks(
        blocks, client=client, market=False, fetcher=offline_fetcher(history),
        notes="thrifted, tiny hole",
    )
    text = client.messages.calls[0]["messages"][0]["content"][-1]["text"]
    assert "thrifted, tiny hole" in text
    assert "unverified" in text


def test_images_are_encoded_as_base64_blocks(blocks):
    block = blocks[0]
    assert block["type"] == "image"
    assert block["source"]["media_type"] in {"image/png", "image/jpeg"}
    base64.standard_b64decode(block["source"]["data"])  # valid base64


def test_large_images_are_downscaled():
    block = prepare_bytes(png_bytes((3000, 2200)), "image/png")
    from PIL import Image

    img = Image.open(io.BytesIO(base64.standard_b64decode(block["source"]["data"])))
    assert max(img.size) <= 1568
    assert block["source"]["media_type"] == "image/jpeg"


def test_uploads_path(history):
    client = StubClient(make_read())
    report = analyze_uploads(
        [(png_bytes(), "image/png")], client=client, market=False,
        fetcher=offline_fetcher(history),
    )
    assert report.value.currency == "USD"


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(ImageError):
        load_images([tmp_path / "nope.jpg"])


def test_unsupported_extension(tmp_path):
    path = tmp_path / "tag.bmp"
    path.write_bytes(b"nope")
    with pytest.raises(ImageError):
        load_images([path])


def test_analyze_paths_reads_from_disk(tmp_path, history):
    path = tmp_path / "tag.png"
    path.write_bytes(png_bytes())
    report = analyze_paths(
        [path], client=StubClient(make_read()), market=False, fetcher=offline_fetcher(history)
    )
    assert report.tag.brand == "Gap"


def test_cli_renders_a_report(history):
    history.record_many(sold_series([40, 44, 38, 42, 45, 41], brand="Gap", category="t-shirt"))
    report = analyze_blocks(
        [prepare_bytes(png_bytes(), "image/png")],
        client=StubClient(make_read()),
        market=False,
        fetcher=offline_fetcher(history),
    )
    text = cli.render(report)
    assert "Gap pocket tee" in text
    assert "resale range" in text
    assert "How it was priced" in text
    assert "Evidence" in text and "listings used" in text
    assert "priced from observed sales" in text


def test_cli_json_output(monkeypatch, capsys, tmp_path):
    path = tmp_path / "tag.png"
    path.write_bytes(png_bytes())
    monkeypatch.setattr("clothing_id.pipeline.identify_garment", lambda *a, **k: make_read())
    db = tmp_path / "history.db"
    assert cli.main([str(path), "--json", "--offline", "--db", str(db)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["value"]["mid"] > 0
    assert payload["value"]["method"] == "modeled"
    assert payload["identification"]["brand"] == "Gap"


def test_cli_import_and_stats(tmp_path, capsys):
    csv_path = tmp_path / "sold.csv"
    csv_path.write_text(
        "Item number,Title,Sold price,Sold date,Brand,Category,Size,Condition\n"
        "1,Gap tee,$18.00,2026-05-01,Gap,t-shirt,M,good\n"
        "2,Gap tee,$22.00,2026-06-01,Gap,t-shirt,L,good\n"
    )
    db = tmp_path / "history.db"
    assert cli.main(["import", str(csv_path), "--db", str(db)]) == 0
    assert "stored 2 new" in capsys.readouterr().out

    assert cli.main(["stats", "--db", str(db), "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["observations"] == 2 and stats["sold"] == 2


def test_cli_import_missing_file(tmp_path, capsys):
    assert cli.main(["import", str(tmp_path / "nope.csv"), "--db", str(tmp_path / "h.db")]) == 1
    assert "no such file" in capsys.readouterr().err


def test_cli_reports_errors(capsys, tmp_path):
    assert cli.main(["/nonexistent/photo.jpg", "--offline", "--db", str(tmp_path / "h.db")]) == 1
    assert "error:" in capsys.readouterr().err


def test_rn_mismatch_lowers_confidence_and_is_reported(blocks, history, tmp_path, monkeypatch):
    directory = tmp_path / "rn.csv"
    directory.write_text("rn,company\n51884,Patagonia Inc.\n")
    monkeypatch.setenv("CLOTHING_ID_RN_FILE", str(directory))

    read = make_read()
    read.tag.rn_number = "RN 51884"  # a Patagonia number on a tag read as Gap
    report = analyze_blocks(
        blocks, client=StubClient(read), market=False, fetcher=offline_fetcher(history)
    )
    assert report.verification.registrant == "Patagonia Inc."
    assert report.verification.brand_matches_rn is False
    assert any("does not match" in n for n in report.verification.notes)

    matching = make_read()
    matching.tag.rn_number = "51884"
    matching.tag.brand = matching.identification.brand = "Patagonia"
    confirmed = analyze_blocks(
        blocks, client=StubClient(matching), market=False, fetcher=offline_fetcher(history)
    )
    assert confirmed.verification.brand_matches_rn is True
    assert confirmed.value.confidence > report.value.confidence


def test_rn_without_a_directory_yields_a_link_not_a_verdict(blocks, history, monkeypatch):
    monkeypatch.delenv("CLOTHING_ID_RN_FILE", raising=False)
    read = make_read()
    read.tag.rn_number = "51884"
    report = analyze_blocks(
        blocks, client=StubClient(read), market=False, fetcher=offline_fetcher(history)
    )
    assert report.verification.brand_matches_rn is None
    assert report.verification.lookup_url.endswith("51884")
    assert "verify RN at" in cli.render(report)
