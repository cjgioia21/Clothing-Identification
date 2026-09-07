import io

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from clothing_id import api  # noqa: E402
from tests.factories import make_read  # noqa: E402
from tests.test_pipeline import png_bytes  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr("clothing_id.pipeline.identify_garment", lambda *a, **k: make_read())
    return TestClient(api.app)


def test_index_serves_the_upload_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Clothing ID" in res.text


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_identify_returns_a_report(client):
    files = [("images", ("tag.png", io.BytesIO(png_bytes()), "image/png"))]
    res = client.post("/identify", files=files, data={"notes": "thrifted"})
    assert res.status_code == 200
    body = res.json()
    assert body["identification"]["brand"] == "Gap"
    assert body["value"]["low"] <= body["value"]["mid"] <= body["value"]["high"]


def test_identify_rejects_empty_upload(client):
    files = [("images", ("tag.png", io.BytesIO(b""), "image/png"))]
    assert client.post("/identify", files=files).status_code == 400


def test_identify_rejects_too_many_photos(client):
    files = [
        ("images", (f"p{i}.png", io.BytesIO(png_bytes()), "image/png"))
        for i in range(api.MAX_IMAGES + 1)
    ]
    assert client.post("/identify", files=files).status_code == 400


def test_analysis_failure_becomes_502(monkeypatch):
    monkeypatch.setattr(
        "clothing_id.pipeline.identify_garment",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("model down")),
    )
    files = [("images", ("tag.png", io.BytesIO(png_bytes()), "image/png"))]
    res = TestClient(api.app).post("/identify", files=files)
    assert res.status_code == 502
    assert "model down" in res.json()["detail"]
