"""eBay Buy APIs - the primary source of true transaction data.

Two endpoints are used:

* Marketplace Insights (`/buy/marketplace_insights/v1_beta/item_sales/search`)
  returns what items actually SOLD for over the last 90 days. This is a Limited
  Release API - your keyset must be granted access.
* Browse (`/buy/browse/v1/item_summary/search`) returns current asking prices,
  available to any production keyset. Asks are weaker evidence than sales and
  are recorded as `kind='ask'`.

Credentials come from the environment:

    EBAY_CLIENT_ID       # App ID (Client ID) of a production keyset
    EBAY_CLIENT_SECRET   # Cert ID (Client Secret)
    EBAY_MARKETPLACE_ID  # optional, defaults to EBAY_US

Docs: https://developer.ebay.com/api-docs/buy/marketplace-insights/resources/item_sales/methods/search
      https://developer.ebay.com/api-docs/buy/browse/resources/item_summary/methods/search
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Dict, List, Optional

from ..history import Observation, parse_date, parse_price

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
BROWSE_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
INSIGHTS_URL = "https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search"

SCOPE_BROWSE = "https://api.ebay.com/oauth/api_scope"
SCOPE_INSIGHTS = "https://api.ebay.com/oauth/api_scope/buy.marketplace.insights"

# eBay US: Clothing, Shoes & Accessories.
CLOTHING_CATEGORY_ID = "11450"

# eBay condition ids -> our grades. eBay's used clothing bucket is a single
# 'Pre-owned' id, which we treat as 'good' rather than pretending to know more.
CONDITION_IDS: Dict[str, str] = {
    "1000": "deadstock",  # New with tags
    "1500": "deadstock",  # New without tags / New other
    "1750": "excellent",  # New with defects
    "2000": "excellent",  # Certified refurbished
    "2750": "excellent",  # Seller refurbished
    "3000": "good",  # Pre-owned
    "4000": "fair",  # Very good (media grading, rare on apparel)
    "5000": "fair",  # Good
    "6000": "fair",  # Acceptable
    "7000": "poor",  # For parts or not working
}

CONDITION_FILTERS: Dict[str, str] = {
    "deadstock": "NEW|NEW_OTHER",
    "excellent": "USED_EXCELLENT|NEW_OTHER",
    "good": "USED_VERY_GOOD|USED_GOOD",
    "fair": "USED_ACCEPTABLE",
    "poor": "FOR_PARTS_OR_NOT_WORKING",
}


class EbayError(RuntimeError):
    pass


def _post_form(url: str, data: Dict[str, str], headers: Dict[str, str], timeout: int) -> Dict:
    body = urllib.parse.urlencode(data).encode()
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        raise EbayError(f"{exc.code} from {url}: {exc.read().decode()[:300]}") from exc
    except urllib.error.URLError as exc:
        raise EbayError(f"could not reach {url}: {exc.reason}") from exc


def _get_json(url: str, params: Dict[str, str], headers: Dict[str, str], timeout: int) -> Dict:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(full, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()[:300]
        raise EbayError(f"{exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise EbayError(f"could not reach {url}: {exc.reason}") from exc


class EbayClient:
    """Thin client over the two Buy endpoints, with token caching."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        marketplace_id: str = "EBAY_US",
        timeout: int = 20,
    ):
        if not client_id or not client_secret:
            raise EbayError("eBay client id and secret are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.marketplace_id = marketplace_id
        self.timeout = timeout
        self._tokens: Dict[str, tuple[str, float]] = {}

    # --- auth --------------------------------------------------------------

    def _token(self, scope: str) -> str:
        cached = self._tokens.get(scope)
        if cached and cached[1] > time.time() + 60:
            return cached[0]
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        payload = _post_form(
            TOKEN_URL,
            {"grant_type": "client_credentials", "scope": scope},
            {
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            self.timeout,
        )
        token = payload.get("access_token")
        if not token:
            raise EbayError(f"no access token in eBay response: {payload}")
        self._tokens[scope] = (token, time.time() + float(payload.get("expires_in", 7200)))
        return token

    def _headers(self, scope: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token(scope)}",
            "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
            "Accept": "application/json",
        }

    # --- searches ----------------------------------------------------------

    def sold_comps(
        self,
        query: str,
        condition_grade: Optional[str] = None,
        days: int = 90,
        limit: int = 50,
        category_id: str = CLOTHING_CATEGORY_ID,
    ) -> List[Observation]:
        """Completed sales from the last `days` (max 90, per eBay's window)."""
        start = (date.today() - timedelta(days=min(days, 90))).isoformat()
        filters = [f"lastSoldDate:[{start}T00:00:00Z..]"]
        if condition_grade in CONDITION_FILTERS:
            filters.append(f"conditions:{{{CONDITION_FILTERS[condition_grade]}}}")
        params = {
            "q": query,
            "category_ids": category_id,
            "filter": ",".join(filters),
            "limit": str(min(limit, 200)),
        }
        payload = _get_json(INSIGHTS_URL, params, self._headers(SCOPE_INSIGHTS), self.timeout)
        return [
            obs
            for obs in (self._sale_to_observation(item) for item in payload.get("itemSales", []))
            if obs is not None
        ]

    def active_comps(
        self,
        query: str,
        condition_grade: Optional[str] = None,
        limit: int = 50,
        category_id: str = CLOTHING_CATEGORY_ID,
    ) -> List[Observation]:
        """Current asking prices. Weaker evidence than sales - stored as 'ask'."""
        filters = ["buyingOptions:{FIXED_PRICE|AUCTION}"]
        if condition_grade in CONDITION_FILTERS:
            filters.append(f"conditions:{{{CONDITION_FILTERS[condition_grade]}}}")
        params = {
            "q": query,
            "category_ids": category_id,
            "filter": ",".join(filters),
            "limit": str(min(limit, 200)),
        }
        payload = _get_json(BROWSE_URL, params, self._headers(SCOPE_BROWSE), self.timeout)
        return [
            obs
            for obs in (
                self._summary_to_observation(item) for item in payload.get("itemSummaries", [])
            )
            if obs is not None
        ]

    # --- mapping -----------------------------------------------------------

    @staticmethod
    def _sale_to_observation(item: Dict) -> Optional[Observation]:
        price = parse_price((item.get("lastSoldPrice") or {}).get("value"))
        sold_on = parse_date(item.get("lastSoldDate"))
        if price is None or sold_on is None:
            return None
        return Observation(
            source="ebay-sold",
            source_id=str(item.get("itemId") or item.get("legacyItemId") or item.get("title")),
            kind="sold",
            price=price,
            currency=(item.get("lastSoldPrice") or {}).get("currency", "USD"),
            observed_on=sold_on,
            title=item.get("title", ""),
            url=item.get("itemWebUrl"),
            condition_grade=CONDITION_IDS.get(str(item.get("conditionId", "")), None),
            raw={"condition": item.get("condition"), "categories": item.get("categories")},
        )

    @staticmethod
    def _summary_to_observation(item: Dict) -> Optional[Observation]:
        price = parse_price((item.get("price") or {}).get("value"))
        if price is None:
            return None
        listed_on = parse_date(item.get("itemCreationDate")) or date.today()
        return Observation(
            source="ebay-active",
            source_id=str(item.get("itemId") or item.get("title")),
            kind="ask",
            price=price,
            currency=(item.get("price") or {}).get("currency", "USD"),
            observed_on=listed_on,
            title=item.get("title", ""),
            url=item.get("itemWebUrl"),
            condition_grade=CONDITION_IDS.get(str(item.get("conditionId", "")), None),
            raw={"condition": item.get("condition")},
        )


def ebay_from_env() -> Optional[EbayClient]:
    """Build a client from EBAY_CLIENT_ID / EBAY_CLIENT_SECRET, or return None."""
    client_id = os.environ.get("EBAY_CLIENT_ID")
    client_secret = os.environ.get("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    return EbayClient(
        client_id,
        client_secret,
        marketplace_id=os.environ.get("EBAY_MARKETPLACE_ID", "EBAY_US"),
    )
