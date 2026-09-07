"""Pipeline tests with a stubbed Anthropic client - no network, no API key."""

import base64
import io
import json

import pytest

from clothing_id import cli
from clothing_id.images import ImageError, load_images, prepare_bytes
from clothing_id.models import Comparable, GarmentRead
from clothing_id.pipeline import analyze_blocks, analyze_paths, analyze_uploads
from tests.factories import make_read


class StubResponse:
    def __init__(self, parsed, stop_reason="end_turn", stop_details=None):
        self.parsed_output = parsed
        self.stop_reason = stop_reason
        self.stop_details = stop_details


class StubMessages:
    """Returns the garment read first, then the comparables payload."""

    def __init__(self, read, comps=None, fail_comps=False):
        self.read = read
        self.comps = comps or []
        self.fail_comps = fail_comps
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["output_format"] is GarmentRead:
            return StubResponse(self.read)
        if self.fail_comps:
            raise RuntimeError("search unavailable")
        model = kwargs["output_format"]
        return StubResponse(model(comparables=self.comps))


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


def test_analyze_returns_identification_and_value(blocks):
    client = StubClient(make_read())
    report = analyze_blocks(blocks, client=client)
    assert report.identification.item_name == "Gap pocket tee"
    assert report.value.mid > 0
    assert len(client.messages.calls) == 1  # no market call unless asked


def test_market_check_uses_comps(blocks):
    comps = [Comparable(title="Gap tee", price=40, source="eBay")]
    client = StubClient(make_read(), comps=comps)
    report = analyze_blocks(blocks, client=client, market_check=True)
    assert len(client.messages.calls) == 2
    assert report.value.comparables[0].price == 40
    assert any(f.name == "market comparables" for f in report.value.factors)


def test_failed_market_lookup_does_not_sink_the_estimate(blocks):
    client = StubClient(make_read(), fail_comps=True)
    report = analyze_blocks(blocks, client=client, market_check=True)
    assert report.value.mid > 0
    assert any("Market lookup failed" in n for n in report.value.notes)


def test_seller_notes_reach_the_prompt(blocks):
    client = StubClient(make_read())
    analyze_blocks(blocks, client=client, notes="thrifted, tiny hole")
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


def test_uploads_path(monkeypatch):
    client = StubClient(make_read())
    report = analyze_uploads([(png_bytes(), "image/png")], client=client)
    assert report.value.currency == "USD"


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(ImageError):
        load_images([tmp_path / "nope.jpg"])


def test_unsupported_extension(tmp_path):
    path = tmp_path / "tag.bmp"
    path.write_bytes(b"nope")
    with pytest.raises(ImageError):
        load_images([path])


def test_analyze_paths_reads_from_disk(tmp_path):
    path = tmp_path / "tag.png"
    path.write_bytes(png_bytes())
    report = analyze_paths([path], client=StubClient(make_read()))
    assert report.tag.brand == "Gap"


def test_cli_renders_a_report():
    report = analyze_blocks(
        [prepare_bytes(png_bytes(), "image/png")], client=StubClient(make_read())
    )
    text = cli.render(report)
    assert "Gap pocket tee" in text
    assert "resale range" in text
    assert "How it was priced" in text


def test_cli_json_output(monkeypatch, capsys, tmp_path):
    path = tmp_path / "tag.png"
    path.write_bytes(png_bytes())
    monkeypatch.setattr(
        "clothing_id.pipeline.identify_garment", lambda *a, **k: make_read()
    )
    assert cli.main([str(path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["value"]["mid"] > 0
    assert payload["identification"]["brand"] == "Gap"


def test_cli_reports_errors(capsys):
    assert cli.main(["/nonexistent/photo.jpg"]) == 1
    assert "error:" in capsys.readouterr().err
