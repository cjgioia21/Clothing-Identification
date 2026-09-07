"""Market sources: eBay mapping, search hygiene, and the fetch/store loop."""

import json
from datetime import date, timedelta

import pytest

from clothing_id.history import SalesHistory
from clothing_id.market.ebay import CONDITION_IDS, EbayClient, EbayError, ebay_from_env
from clothing_id.market.fetch import MarketFetcher, build_query
from clothing_id.market.search import search_comparables
from tests.factories import make_read, sold_series


# --- eBay ------------------------------------------------------------------


def test_sold_response_maps_to_observations():
    payload = {
        "itemSales": [
            {
                "itemId": "v1|123|0",
                "title": "Patagonia Snap-T Fleece M",
                "itemWebUrl": "https://www.ebay.com/itm/123",
                "conditionId": "3000",
                "condition": "Pre-owned",
                "lastSoldDate": "2026-08-14T18:22:11.000Z",
                "lastSoldPrice": {"value": "88.50", "currency": "USD"},
            },
            {"itemId": "no-price", "title": "missing price"},
        ]
    }
    observations = [
        obs
        for obs in (EbayClient._sale_to_observation(i) for i in payload["itemSales"])
        if obs is not None
    ]
    assert len(observations) == 1
    obs = observations[0]
    assert (obs.price, obs.currency, obs.kind) == (88.5, "USD", "sold")
    assert obs.observed_on == date(2026, 8, 14)
    assert obs.condition_grade == "good"
    assert obs.url == "https://www.ebay.com/itm/123"
    assert obs.source == "ebay-sold"


def test_active_response_maps_to_asks():
    obs = EbayClient._summary_to_observation(
        {
            "itemId": "v1|999|0",
            "title": "Carhartt Detroit Jacket",
            "price": {"value": "140.00", "currency": "USD"},
            "itemWebUrl": "https://www.ebay.com/itm/999",
            "conditionId": "1000",
        }
    )
    assert obs.kind == "ask" and obs.price == 140.0
    assert obs.condition_grade == "deadstock"
    assert obs.source == "ebay-active"


def test_condition_ids_cover_ebays_apparel_buckets():
    assert CONDITION_IDS["1000"] == "deadstock"
    assert CONDITION_IDS["3000"] == "good"
    assert CONDITION_IDS["7000"] == "poor"


def test_client_requires_credentials():
    with pytest.raises(EbayError):
        EbayClient("", "")


def test_env_client_is_optional(monkeypatch):
    monkeypatch.delenv("EBAY_CLIENT_ID", raising=False)
    monkeypatch.delenv("EBAY_CLIENT_SECRET", raising=False)
    assert ebay_from_env() is None
    monkeypatch.setenv("EBAY_CLIENT_ID", "id")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    assert isinstance(ebay_from_env(), EbayClient)


def test_sold_search_builds_the_documented_request(monkeypatch):
    captured = {}

    def fake_get(url, params, headers, timeout):
        captured.update(url=url, params=params, headers=headers)
        return {"itemSales": []}

    monkeypatch.setattr("clothing_id.market.ebay._get_json", fake_get)
    client = EbayClient("id", "secret")
    monkeypatch.setattr(client, "_token", lambda scope: "tok")

    client.sold_comps("patagonia snap-t", condition_grade="good", days=90, limit=25)
    assert captured["url"].endswith("/buy/marketplace_insights/v1_beta/item_sales/search")
    assert captured["params"]["q"] == "patagonia snap-t"
    assert captured["params"]["category_ids"] == "11450"
    assert "lastSoldDate:[" in captured["params"]["filter"]
    assert "conditions:{USED_VERY_GOOD|USED_GOOD}" in captured["params"]["filter"]
    assert captured["headers"]["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"


# --- web search ------------------------------------------------------------


class SearchStub:
    def __init__(self, listings):
        self.listings = listings
        self.calls = []
        self.messages = self

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        model = kwargs["output_format"]
        return type(
            "R",
            (),
            {
                "parsed_output": model(listings=self.listings, query_used="q"),
                "stop_reason": "end_turn",
                "stop_details": None,
            },
        )()


def test_search_keeps_only_listings_with_a_price_and_url():
    stub = SearchStub(
        [
            {
                "title": "Patagonia Snap-T",
                "price": 88.0,
                "url": "https://www.ebay.com/itm/1",
                "sold": True,
                "sold_on": "2026-07-04",
                "marketplace": "eBay",
            },
            {"title": "no url", "price": 50.0, "url": "", "sold": True},
            {"title": "no price", "price": 0, "url": "https://grailed.com/x"},
        ]
    )
    observations = search_comparables({"brand": "Patagonia", "category": "sweatshirt"}, client=stub)
    assert len(observations) == 1
    obs = observations[0]
    assert obs.kind == "sold" and obs.observed_on == date(2026, 7, 4)
    assert obs.source == "web-search" and obs.source_id == obs.url


def test_search_prompt_forbids_invented_prices():
    stub = SearchStub([])
    search_comparables({"brand": "Gap"}, client=stub)
    system = stub.calls[0]["system"]
    assert "Never estimate, average, or invent a price" in system
    assert stub.calls[0]["tools"][0]["type"] == "web_search_20260209"


def test_search_returns_nothing_on_refusal():
    class Refuser(SearchStub):
        def parse(self, **kwargs):
            return type("R", (), {"parsed_output": None, "stop_reason": "refusal", "stop_details": None})()

    assert search_comparables({"brand": "Gap"}, client=Refuser([])) == []


# --- fetcher ---------------------------------------------------------------


class FakeEbay:
    def __init__(self, sold=None, asks=None, error=None):
        self.sold = sold or []
        self.asks = asks or []
        self.error = error

    def sold_comps(self, *a, **k):
        if self.error:
            raise EbayError(self.error)
        return self.sold

    def active_comps(self, *a, **k):
        return self.asks


@pytest.fixture
def history():
    store = SalesHistory(":memory:")
    yield store
    store.close()


def test_query_reads_like_a_human_search():
    read = make_read()
    read.identification.brand = "Patagonia"
    read.identification.item_name = "Patagonia Snap-T Fleece"
    read.visual.subtype = "fleece pullover"
    query = build_query(read)
    assert "Patagonia" in query and "Snap-T" in query
    assert query.count("Patagonia") == 1  # no duplicated terms


def test_fetch_stores_everything_it_finds(history):
    fetcher = MarketFetcher(history=history, ebay=FakeEbay(sold=sold_series([90, 95, 100])))
    result = fetcher.fetch(make_read(), use_search=False)
    assert len(result.observations) == 3
    assert result.stored == 3
    assert history.count() == 3
    assert any(s.startswith("ebay-sold") for s in result.sources_used)


def test_fetch_records_source_errors_without_failing(history):
    fetcher = MarketFetcher(history=history, ebay=FakeEbay(error="403 Forbidden"))
    result = fetcher.fetch(make_read(), use_search=False)
    assert result.observations == []
    assert any("403" in e for e in result.errors)


def test_known_history_finds_previous_records(history):
    history.record_many(sold_series([40, 45], brand="Gap", category="t-shirt"))
    fetcher = MarketFetcher(history=history, ebay=None)
    rows = fetcher.known_history(make_read())
    assert len(rows) == 2


def test_known_history_ignores_stale_rows(history):
    old = sold_series([40], brand="Gap", category="t-shirt")
    old[0].observed_on = date.today() - timedelta(days=3000)
    history.record_many(old)
    fetcher = MarketFetcher(history=history, ebay=None)
    assert fetcher.known_history(make_read(), days=365) == []
