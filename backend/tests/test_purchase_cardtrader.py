import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.cardtrader import offers as ct_offers
from tests.test_purchase import BOLT, SERRA, SOL_RING, SWORDS, offer, oracle_ids
from tests.test_wants import make_deck

TOKEN = "good-token"


class FakeMarketplace:
    """CardTrader: expansions, blueprints by Scryfall id, the cheapest offers per blueprint, the cart."""

    def __init__(self, prices: dict[str, list[tuple[int, int, bool]]]):
        # card name -> offers (price in cents, quantity, sells via CardTrader Zero)
        self.prices = prices
        self.printings: dict[int, str] = {}  # blueprint id -> card name
        self.cart: list[dict] = []
        self.calls: list[str] = []
        self.sold_out: set[int] = set()

    def setup(self, client: TestClient) -> None:
        """Blueprints for every printing of the priced cards in the fixture."""
        self.expansions: dict[str, int] = {}
        self.blueprints: dict[int, list[dict]] = {}
        for name in self.prices:
            for printing in client.get(f"/api/cards/{_card(client, name)}/printings").json():
                expansion = self.expansions.setdefault(printing["set_code"], len(self.expansions) + 1)
                blueprint = 1000 + len(self.printings)
                self.printings[blueprint] = name
                self.blueprints.setdefault(expansion, []).append({"id": blueprint, "scryfall_id": printing["id"]})

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        path = request.url.path.removeprefix("/api/v2")
        self.calls.append(path)
        if path == "/info":
            return httpx.Response(200, json={"id": 1, "name": "MTGDM"})
        if path == "/expansions":
            return httpx.Response(200, json=[{"id": i, "game_id": 1, "code": c, "name": c}
                                             for c, i in self.expansions.items()] + [{"id": 999, "game_id": 5, "code": "x"}])
        if path == "/blueprints/export":
            return httpx.Response(200, json=self.blueprints.get(int(request.url.params["expansion_id"]), []))
        if path == "/marketplace/products":
            blueprint = int(request.url.params["blueprint_id"])
            name = self.printings[blueprint]
            # Every printing has the card's offers; only the first printing found sells, to keep sums simple.
            if blueprint != min(b for b, n in self.printings.items() if n == name):
                return httpx.Response(200, json={str(blueprint): []})
            products = [
                {"id": blueprint * 10 + i, "blueprint_id": blueprint, "quantity": qty,
                 "price": {"cents": cents, "currency": "EUR"}, "properties_hash": {"mtg_language": "en"},
                 "user": {"username": f"seller{i}", "can_sell_via_hub": zero}, "graded": False, "on_vacation": False,
                 "bundle_size": 1}
                for i, (cents, qty, zero) in enumerate(self.prices[name])
            ]
            return httpx.Response(200, json={str(blueprint): products})
        if path == "/cart/add":
            body = json.loads(request.content)
            if body["product_id"] in self.sold_out:
                return httpx.Response(422, json={"error_code": "unprocessable", "extra": {"message": "Sold out"}})
            self.cart.append(body)
            return httpx.Response(200, json={"id": 1})
        return httpx.Response(404, json={"error_code": "not_found"})


def _card(client, name: str) -> str:
    return client.get("/api/cards", params={"q": f'!"{name}"'}).json()["items"][0]["id"]


@pytest.fixture
def market():
    ct_offers.clear_cache()
    return FakeMarketplace({
        BOLT: [(50, 1, True), (20, 1, False)],   # the cheaper one isn't via CardTrader Zero
        SOL_RING: [(100, 1, True)],
        SERRA: [(30, 2, True)],
        # Swords to Plowshares: not on CardTrader
    })


@pytest.fixture
def client(card_settings, market):
    http = httpx.Client(transport=httpx.MockTransport(market))
    with TestClient(create_app(card_settings, cardtrader=http)) as c:
        market.setup(c)
        c.put("/api/cardtrader/token", json={"token": TOKEN})
        yield c


def fetch(client, deck: int) -> dict:
    assert client.post(f"/api/decks/{deck}/cardtrader/quotes").status_code == 200
    for _ in range(200):
        job = client.get(f"/api/decks/{deck}/cardtrader/quotes").json()
        if not job["running"]:
            return job
        time.sleep(0.02)
    raise AssertionError("quotes did not finish")


def test_compare_with_cardtrader_zero(client, market):
    deck = make_deck(client, "Giada", [(BOLT, 1), (SOL_RING, 1), (SERRA, 1), (SWORDS, 1)])
    ids = oracle_ids(client, deck)
    client.put("/api/purchase-settings", json={
        "free_delivery_threshold": 10, "default_shipping_cost": 9, "cardtrader_shipping": 18,
        "cardtrader_shipping_currency": "USD",
    })
    assert client.get(f"/api/decks/{deck}/basket/compare").json()["cardtrader"] is None  # not fetched yet

    job = fetch(client, deck)
    assert job["error"] is None and job["result"]["cards"] == 4 and job["result"]["found"] == 3
    compare = client.get(f"/api/decks/{deck}/basket/compare").json()
    assert compare["rate_missing"] == ["EUR", "USD"] and compare["cardtrader"] is None

    client.put("/api/purchase-settings", json={
        "free_delivery_threshold": 10, "default_shipping_cost": 9, "cardtrader_shipping": 18,
        "cardtrader_shipping_currency": "USD", "rates": {"EUR": 4.0, "USD": 4.0},
    })
    # Seller A: Bolt 4 + Swords 7 = 11 (free delivery); Sol Ring 5 at B (below: 9 shipping).
    offer(client, deck, ids[BOLT], "A", 4.0, chosen=True)
    offer(client, deck, ids[SWORDS], "A", 7.0, chosen=True)
    offer(client, deck, ids[SOL_RING], "B", 5.0, chosen=True)
    compare = client.get(f"/api/decks/{deck}/basket/compare").json()
    prices = {c["name"]: c["price"] for c in compare["cardtrader_cards"]}
    assert prices == {BOLT: 2.0, SOL_RING: 4.0, SERRA: 1.2}  # € × 4, the cheapest Zero offer
    assert compare["not_on_cardtrader"] == [SWORDS]
    assert compare["sellers"] == {"cards": 16.0, "shipping": 9.0, "shipping_unknown": 0, "parcels": 2,
                                  "total": 25.0, "complete": False}
    assert compare["cardtrader"] == {"cards": 7.2, "shipping": 72.0, "shipping_unknown": 0, "parcels": 1,
                                     "total": 79.2, "complete": False}
    # Mixed: Serra (no offer chosen) and Sol Ring (B is below its threshold anyway) go to CardTrader;
    # Bolt is cheaper there too, but moving it would drop A below free delivery.
    assert sorted(compare["to_cardtrader"]) == sorted([ids[SERRA], ids[SOL_RING]])
    assert compare["mixed"] == {"cards": 16.2, "shipping": 72.0, "shipping_unknown": 0, "parcels": 2,
                                "total": 88.2, "complete": True}

    # Into the cart: the copies needed of the stored offers, via CardTrader Zero; a sold-out one is reported.
    market.sold_out.add(min(b for b, n in market.printings.items() if n == SOL_RING) * 10)
    cart = client.post(f"/api/decks/{deck}/cardtrader/cart", json={"oracle_ids": compare["to_cardtrader"]}).json()
    assert cart == {"added": 1, "failed": [SOL_RING]}
    assert [(c["quantity"], c["via_cardtrader_zero"]) for c in market.cart] == [(1, True)]
    assert "/cart/purchase" not in market.calls


def test_quotes_need_a_token(card_settings):
    with TestClient(create_app(card_settings, cardtrader=httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(500))))) as client:
        deck = make_deck(client, "Burn", [(BOLT, 1)])
        assert client.post(f"/api/decks/{deck}/cardtrader/quotes").status_code == 400
        assert client.post(f"/api/decks/{deck}/cardtrader/cart", json={"oracle_ids": ["x"]}).status_code == 400
        assert client.get(f"/api/decks/{deck}/cardtrader/quotes").json()["running"] is False
