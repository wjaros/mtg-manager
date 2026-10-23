import json

import httpx
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.spellbook.client import SpellbookClient

QUINTORIUS = ("Quintorius, History Chaser", "5c40a8d4-6969-4d71-aba5-5c7e4109b7d5")
BOLT = ("Lightning Bolt", "4457ed35-7c10-48c8-9776-456485fdf070")
SOL_RING = ("Sol Ring", "6ad8011d-3471-4369-9d68-b264cc027487")
SERRA = ("Serra Angel", "4b7ac066-e5c7-43e6-9e7e-2739b24a905d")
UNKNOWN = ("Card From The Future", "00000000-0000-0000-0000-000000000000")


def variant(id: str, cards, popularity: int, commander_legal: bool = True) -> dict:
    """A variant shaped like Commander Spellbook's (only the fields the app reads, plus some noise)."""
    return {
        "id": id,
        "uses": [{"card": {"name": name, "oracleId": oracle_id, "typeLine": "?"}, "quantity": 1} for name, oracle_id in cards],
        "requires": [{"template": {"name": "Permanent castable for {C}"}, "quantity": 1}],
        "produces": [{"feature": {"name": "Infinite colorless mana"}, "quantity": 1}],
        "description": "Tap.\nUntap.",
        "easyPrerequisites": "All permanents on the battlefield.",
        "notablePrerequisites": "",
        "manaNeeded": "{2}",
        "popularity": popularity,
        "legalities": {"commander": commander_legal, "standardBrawl": False},
        "prices": {"cardmarket": "1.00"},
    }


class FakeSpellbook:
    def __init__(self, status: int = 200):
        self.bodies: list[dict] = []
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/find-my-combos" and request.method == "POST"
        assert request.headers["User-Agent"].startswith("MTGDeckManager/")
        self.bodies.append(json.loads(request.content))
        if self.status != 200:
            return httpx.Response(self.status)
        return httpx.Response(200, json={"count": None, "next": None, "previous": None, "results": {
            "identity": "WR",
            "included": [variant("1-2", [BOLT, SOL_RING], 10)],
            "almostIncluded": [
                variant("3-4", [SOL_RING, SERRA], 5, commander_legal=False),
                variant("5-6", [QUINTORIUS, UNKNOWN], 50),
            ],
            "almostIncludedByAddingColors": [variant("7", [SERRA], 1)],
        }})


@pytest.fixture
def fake():
    return FakeSpellbook()


@pytest.fixture
def client(card_settings, fake):
    spellbook = SpellbookClient(httpx.Client(transport=httpx.MockTransport(fake)), min_interval=0, sleep=lambda s: None)
    with TestClient(create_app(card_settings, spellbook=spellbook)) as c:
        yield c


def card_id(client, name: str) -> str:
    return client.get("/api/cards", params={"q": f'!"{name}"'}).json()["items"][0]["id"]


def make_deck(client) -> int:
    deck = client.post("/api/decks", json={"name": "Combo test", "format": "commander", "platform": "paper"}).json()
    for name, board in ((QUINTORIUS[0], "commander"), (BOLT[0], "main"), (SOL_RING[0], "main"), (SERRA[0], "maybe")):
        resp = client.post(f"/api/decks/{deck['id']}/cards", json={"card_id": card_id(client, name), "board": board})
        assert resp.status_code == 200, resp.text
    return deck["id"]


def test_combos_in_the_deck_and_one_card_away(client, fake):
    deck_id = make_deck(client)
    client.post("/api/collection", json={"card_id": card_id(client, SERRA[0]), "quantity": 2})
    resp = client.get(f"/api/decks/{deck_id}/combos")
    assert resp.status_code == 200, resp.text
    combos = resp.json()

    # The request: the commander apart, the main deck by name; the maybeboard isn't part of the deck.
    assert fake.bodies == [{
        "commanders": [{"card": QUINTORIUS[0], "quantity": 1}],
        "main": [{"card": BOLT[0], "quantity": 1}, {"card": SOL_RING[0], "quantity": 1}],
    }]

    [included] = combos["included"]
    assert included["url"] == "https://commanderspellbook.com/combo/1-2/"
    assert [(c["name"], c["in_deck"]) for c in included["cards"]] == [(BOLT[0], True), (SOL_RING[0], True)]
    assert included["produces"] == ["Infinite colorless mana"] and included["requires"] == ["Permanent castable for {C}"]
    assert included["prerequisites"] == "All permanents on the battlefield." and included["legal"] is True

    # One card away, most popular first; adding colors isn't offered.
    assert [c["id"] for c in combos["almost"]] == ["5-6", "3-4"]
    unknown = combos["almost"][0]["cards"][1]
    assert (unknown["in_deck"], unknown["card_id"]) == (False, None)
    serra = combos["almost"][1]["cards"][1]
    assert (serra["in_deck"], serra["owned"], serra["card_id"] is not None) == (False, 2, True)
    assert combos["almost"][1]["legal"] is False

    # Same cards again: answered from the cache.
    client.get(f"/api/decks/{deck_id}/combos")
    assert len(fake.bodies) == 1


def test_empty_deck_and_errors(client, fake, card_settings):
    empty = client.post("/api/decks", json={"name": "Empty", "format": "commander", "platform": "paper"}).json()
    assert client.get(f"/api/decks/{empty['id']}/combos").json() == {"included": [], "almost": []}
    assert fake.bodies == []
    assert client.get("/api/decks/999/combos").status_code == 404

    fake.status = 503
    deck_id = make_deck(client)
    resp = client.get(f"/api/decks/{deck_id}/combos", headers={"Accept-Language": "en"})
    assert resp.status_code == 502 and "Commander Spellbook" in resp.json()["detail"]
    assert len(fake.bodies) == 4  # retried
