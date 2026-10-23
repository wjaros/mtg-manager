import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app

BOLT = "Lightning Bolt"
SOL_RING = "Sol Ring"
SERRA = "Serra Angel"


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


def card_id(client, name: str) -> str:
    return client.get("/api/cards", params={"q": f'!"{name}"'}).json()["items"][0]["id"]


def make_deck(client, name: str, cards: list[tuple[str, int]]) -> int:
    deck = client.post("/api/decks", json={"name": name, "format": "freeform", "platform": "paper"}).json()
    for card, quantity in cards:
        for _ in range(quantity):
            client.post(f"/api/decks/{deck['id']}/cards", json={"card_id": card_id(client, card)})
    return deck["id"]


def wanted(wants: dict) -> dict[str, int]:
    return {e["name"]: e["quantity"] for e in wants["entries"]}


def test_by_hand_and_from_decks(client):
    # By hand: any printing, the same card twice adds up.
    client.post("/api/wants", json={"card_id": card_id(client, BOLT)})
    wants = client.post("/api/wants", json={"card_id": card_id(client, BOLT), "quantity": 2}).json()
    assert wanted(wants) == {BOLT: 3}
    assert wants["entries"][0]["sources"] == [{"deck_id": None, "deck_name": None, "quantity": 3}]
    assert client.post("/api/wants", json={"card_id": "nope"}).status_code == 404

    # A deck's missing cards: one owned Sol Ring covers one of the two.
    client.post("/api/collection", json={"card_id": card_id(client, SOL_RING), "quantity": 1})
    deck = make_deck(client, "Burn", [(BOLT, 1), (SOL_RING, 2)])
    result = client.post(f"/api/decks/{deck}/wants").json()
    assert result["added"] == 2
    assert wanted(result["wants"]) == {BOLT: 4, SOL_RING: 1}
    bolt = next(e for e in result["wants"]["entries"] if e["name"] == BOLT)
    assert [(s["deck_name"], s["quantity"]) for s in bolt["sources"]] == [(None, 3), ("Burn", 1)]

    # Added again: the deck's part is replaced, not doubled.
    assert wanted(client.post(f"/api/decks/{deck}/wants").json()["wants"]) == {BOLT: 4, SOL_RING: 1}

    # Fewer: hand-added copies go first; then off the list altogether.
    assert wanted(client.post(f"/api/wants/{bolt['oracle_id']}/reduce", params={"quantity": 3}).json()) == {
        BOLT: 1, SOL_RING: 1}
    assert wanted(client.delete(f"/api/wants/{bolt['oracle_id']}").json()) == {SOL_RING: 1}

    # Deleting the deck takes its wants along.
    client.delete(f"/api/decks/{deck}")
    assert client.get("/api/wants").json()["entries"] == []
    assert client.post("/api/decks/999/wants").status_code == 404


def test_bought_copies_leave_the_list(client):
    serra = card_id(client, SERRA)
    client.post("/api/wants", json={"card_id": serra, "quantity": 2})
    # A proxy isn't bought; a real copy is.
    client.post("/api/collection", json={"card_id": serra, "kind": "proxy"})
    assert wanted(client.get("/api/wants").json()) == {SERRA: 2}
    client.post("/api/collection", json={"card_id": serra})
    wants = client.get("/api/wants").json()
    assert wanted(wants) == {SERRA: 1} and wants["entries"][0]["wanted"] == 2
    client.post("/api/collection", json={"card_id": serra})
    assert client.get("/api/wants").json()["entries"] == []

    # Wanted again later: the copies bought before don't count.
    assert wanted(client.post("/api/wants", json={"card_id": serra}).json()) == {SERRA: 1}


def test_exports(client):
    client.post("/api/wants", json={"card_id": card_id(client, SERRA), "quantity": 2})
    deck = make_deck(client, "Burn", [(BOLT, 1)])
    client.post(f"/api/decks/{deck}/wants")
    assert client.get("/api/wants/export").text == f"1 {BOLT}\n2 {SERRA}\n"
    csv = client.get("/api/wants/export", params={"format": "csv"})
    assert csv.headers["content-type"].startswith("text/csv")
    lines = csv.text.splitlines()
    assert lines[0] == "quantity,name,decks,price_eur,price_usd,scryfall_id" and lines[1].startswith(f"1,{BOLT},Burn,")

    assert wanted(client.delete("/api/wants").json()) == {}


def test_backup_keeps_what_is_still_to_buy(client):
    serra = card_id(client, SERRA)
    client.post("/api/wants", json={"card_id": serra, "quantity": 3})
    client.post("/api/collection", json={"card_id": serra})  # one bought
    deck = make_deck(client, "Burn", [(BOLT, 2)])
    client.post(f"/api/decks/{deck}/wants")
    backup = client.get("/api/backup/export").json()
    assert [(w["name"], w["quantity"]) for w in backup["wants"]] == [(SERRA, 2)]
    assert [(w["name"], w["quantity"]) for w in backup["decks"][0]["wants"]] == [(BOLT, 2)]

    resp = client.post("/api/backup/import", params={"replace": True}, json=backup)
    assert resp.status_code == 200, resp.text
    wants = client.get("/api/wants").json()
    assert wanted(wants) == {SERRA: 2, BOLT: 2}
    bolt = next(e for e in wants["entries"] if e["name"] == BOLT)
    assert [s["deck_name"] for s in bolt["sources"]] == ["Burn"]
