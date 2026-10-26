"""CardTrader's API (https://www.cardtrader.com/en/docs/api/full/reference) with the user's own token
(from their CardTrader profile settings): 200 requests per 10 s; errors as JSON with a message."""

import time
from collections.abc import Callable
from typing import Any

import httpx

from mtgdm import APP_NAME, __version__

API_BASE = "https://api.cardtrader.com/api/v2"
MAGIC = 1  # CardTrader's game id
MAX_RETRIES = 3
RETRY_PAUSE = 2.0  # seconds, times the attempt, after "too many requests"
MARKETPLACE_INTERVAL = 0.11  # marketplace products: 10 requests per second


class CardTraderError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(f"CardTrader {status}: {message}")
        self.status = status
        self.message = message


def new_http() -> httpx.Client:
    """The shared HTTP client; the token goes with each request, not with the client."""
    return httpx.Client(timeout=httpx.Timeout(30.0), headers={
        "User-Agent": f"{APP_NAME}/{__version__}", "Accept": "application/json",
    })


class CardTraderClient:
    def __init__(self, token: str, http: httpx.Client, *, sleep: Callable[[float], None] = time.sleep):
        self._http = http
        self._auth = {"Authorization": f"Bearer {token}"}
        self._sleep = sleep
        self._clock = time.monotonic
        self._last_marketplace = 0.0

    def info(self) -> dict[str, Any]:
        """The app the token belongs to (tests the token)."""
        return self._request("GET", "/info")

    def create_wishlist(self, name: str, text_deck: str, public: bool = False) -> dict[str, Any]:
        """A wishlist from a list in MTGA format; CardTrader leaves out lines matching no card."""
        return self._request("POST", "/wishlists", json={"deck": {
            "game_id": MAGIC, "name": name, "public": public, "deck_items_from_text_deck": text_deck,
        }})

    def create_wishlist_items(self, name: str, items: list[dict[str, Any]], public: bool = False) -> dict[str, Any]:
        """A wishlist from items: CardTrader's name of the card (`meta_name`), quantity, language, ..."""
        return self._request("POST", "/wishlists", json={"deck": {
            "game_id": MAGIC, "name": name, "public": public, "deck_items_attributes": items,
        }})

    def wishlist(self, wishlist_id: int) -> dict[str, Any]:
        return self._request("GET", f"/wishlists/{wishlist_id}")

    def delete_wishlist(self, wishlist_id: int) -> None:
        self._request("DELETE", f"/wishlists/{wishlist_id}")

    def expansions(self) -> list[dict[str, Any]]:
        """Every expansion of every game: {id, game_id, code, name}."""
        return self._request("GET", "/expansions")

    def blueprints(self, expansion_id: int) -> list[dict[str, Any]]:
        """An expansion's sellable printings, each with its `scryfall_id`."""
        return self._request("GET", "/blueprints/export", params={"expansion_id": expansion_id})

    def marketplace_products(self, blueprint_id: int, language: str | None = None) -> list[dict[str, Any]]:
        """The cheapest 25 offers of a printing (10 requests per second at most)."""
        wait = self._last_marketplace + MARKETPLACE_INTERVAL - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_marketplace = self._clock()
        params: dict[str, Any] = {"blueprint_id": blueprint_id}
        if language:
            params["language"] = language
        found = self._request("GET", "/marketplace/products", params=params) or {}
        return found.get(str(blueprint_id)) or []

    def add_to_cart(self, product_id: int, quantity: int, via_zero: bool = True) -> dict[str, Any]:
        """Into the user's cart on CardTrader (never bought from here: the purchase is theirs to make)."""
        return self._request("POST", "/cart/add", json={
            "product_id": product_id, "quantity": quantity, "via_cardtrader_zero": via_zero,
        })

    def _request(self, method: str, path: str, json: Any = None, params: dict[str, Any] | None = None) -> Any:
        for attempt in range(MAX_RETRIES + 1):
            resp = self._http.request(method, API_BASE + path, json=json, params=params, headers=self._auth)
            if resp.status_code == 429 and attempt < MAX_RETRIES:
                self._sleep(RETRY_PAUSE * (attempt + 1))
                continue
            if resp.is_error:
                raise CardTraderError(resp.status_code, _message(resp))
            return resp.json() if resp.content else None
        raise AssertionError("unreachable")


def _message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200] or resp.reason_phrase
    if isinstance(body, dict):
        extra = body.get("extra") if isinstance(body.get("extra"), dict) else {}
        return str(extra.get("message") or body.get("error") or body.get("error_code") or resp.reason_phrase)
    return resp.reason_phrase
