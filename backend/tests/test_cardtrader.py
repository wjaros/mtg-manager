import json

import httpx
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.cardtrader.client import CardTraderClient, CardTraderError
from tests.helpers import fixture_cards

CARDS = {c["name"]: c for c in fixture_cards()}
TOKEN = "good-token"
UNKNOWN = "Lightning Bolt"  # a card the fake CardTrader doesn't recognize


class FakeCardTrader:
    """CardTrader's API: the token, wishlists made from MTGA text (unknown lines left out silently)."""

    def __init__(self):
        self.wishlists: dict[int, dict] = {}
        self.texts: list[str] = []
        self.fail_with: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"error_code": "unauthorized", "errors": [],
                                             "extra": {"message": "You are not authorized to access this page"}})
        if self.fail_with:
            return httpx.Response(self.fail_with, json={"error_code": "oops", "extra": {"message": "Server trouble"}})
        path = request.url.path.removeprefix("/api/v2")
        if path == "/info":
            return httpx.Response(200, json={"id": 3, "name": "MTGDM", "shared_secret": "x"})
        if path == "/wishlists" and request.method == "POST":
            deck = json.loads(request.content)["deck"]
            assert deck["game_id"] == 1 and deck["public"] is False
            self.texts.append(deck["deck_items_from_text_deck"])
            items = []
            for line in deck["deck_items_from_text_deck"].splitlines():
                quantity, name = line.split(" ", 1)
                if name != UNKNOWN:
                    items.append({"quantity": int(quantity), "meta_name": name, "expansion_code": None})
            wishlist_id = len(self.wishlists) + 1
            self.wishlists[wishlist_id] = {"id": wishlist_id, "name": deck["name"], "game_id": 1, "items": items}
            return httpx.Response(200, json={k: v for k, v in self.wishlists[wishlist_id].items() if k != "items"})
        if path.startswith("/wishlists/"):
            return httpx.Response(200, json=self.wishlists[int(path.rsplit("/", 1)[1])])
        return httpx.Response(404, json={"errors": {"request": ["Not Found"]}})


@pytest.fixture
def cardtrader():
    return FakeCardTrader()


@pytest.fixture
def client(card_settings, cardtrader):
    http = httpx.Client(transport=httpx.MockTransport(cardtrader))
    with TestClient(create_app(card_settings, cardtrader=http)) as c:
        yield c


def connect(client):
    assert client.put("/api/cardtrader/token", json={"token": f"  {TOKEN} "}).json() == {
        "connected": True, "app_name": "MTGDM"}


def test_token(client):
    assert client.get("/api/cardtrader").json() == {"connected": False, "app_name": None}
    resp = client.put("/api/cardtrader/token", json={"token": "wrong"}, headers={"Accept-Language": "en"})
    assert resp.status_code == 400 and "didn't accept the token" in resp.json()["detail"]
    assert client.get("/api/cardtrader").json()["connected"] is False

    connect(client)
    assert TOKEN not in json.dumps(client.get("/api/backup/export").json())  # never in a backup
    assert client.delete("/api/cardtrader/token").status_code == 204
    assert client.get("/api/cardtrader").json()["connected"] is False


def test_shopping_list_as_a_wishlist(client, cardtrader):
    body = {"source": "wants"}
    resp = client.post("/api/cardtrader/wishlists", json=body, headers={"Accept-Language": "en"})
    assert resp.status_code == 400 and "token" in resp.json()["detail"]
    connect(client)
    assert client.post("/api/cardtrader/wishlists", json=body).status_code == 400  # nothing to buy

    for name, quantity in (("Sol Ring", 2), (UNKNOWN, 1), ("Delver of Secrets // Insectile Aberration", 1),
                           ("Fire // Ice", 3)):
        client.post("/api/wants", json={"card_id": CARDS[name]["id"], "quantity": quantity})
    result = client.post("/api/cardtrader/wishlists", json=body, headers={"Accept-Language": "pl"}).json()
    assert result["name"].startswith("Lista zakupów ")
    assert (result["cards"], result["copies"]) == (4, 7)
    assert result["not_found"] == [UNKNOWN]  # left out by CardTrader: reported, not lost
    # MTGA names: a split card in full, other multi-face cards by their front face.
    assert sorted(cardtrader.texts[0].splitlines()) == [
        "1 Delver of Secrets", "1 Lightning Bolt", "2 Sol Ring", "3 Fire // Ice"]


def test_deck_missing_cards_as_a_wishlist(client, cardtrader):
    connect(client)
    deck = client.post("/api/decks", json={"name": "Izzet", "format": "freeform", "platform": "paper"}).json()
    for name, quantity in (("Fire // Ice", 2), ("Sol Ring", 1)):
        client.post(f"/api/decks/{deck['id']}/cards", json={"card_id": CARDS[name]["id"], "quantity": quantity})
    client.post("/api/collection", json={"card_id": CARDS["Sol Ring"]["id"]})  # owned: not missing

    result = client.post("/api/cardtrader/wishlists", json={"source": "deck", "deck_id": deck["id"]},
                         headers={"Accept-Language": "en"}).json()
    assert result["name"] == "Izzet – missing" and result["not_found"] == []
    assert cardtrader.texts[-1] == "2 Fire // Ice"
    assert client.post("/api/cardtrader/wishlists", json={"source": "deck", "deck_id": 999}).status_code == 404
    assert client.post("/api/cardtrader/wishlists", json={"source": "deck"}).status_code == 422


def test_cardtrader_errors_are_reported(client, cardtrader):
    connect(client)
    client.post("/api/wants", json={"card_id": CARDS["Sol Ring"]["id"]})
    cardtrader.fail_with = 500
    resp = client.post("/api/cardtrader/wishlists", json={"source": "wants"}, headers={"Accept-Language": "en"})
    assert resp.status_code == 502 and resp.json()["detail"] == "CardTrader returned an error: Server trouble"


def test_too_many_requests_is_retried():
    responses = iter([httpx.Response(429, json={"error": "Too many requests: max 200 requests per 10 seconds"}),
                      httpx.Response(200, json={"id": 3, "name": "MTGDM"})])
    pauses = []
    client = CardTraderClient(TOKEN, httpx.Client(transport=httpx.MockTransport(lambda r: next(responses))),
                              sleep=pauses.append)
    assert client.info()["name"] == "MTGDM" and pauses == [2.0]
    with pytest.raises(CardTraderError) as exc:
        CardTraderClient("x", httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(429, json={"error": "Too many requests"}))), sleep=lambda s: None).info()
    assert exc.value.status == 429 and exc.value.message == "Too many requests"
