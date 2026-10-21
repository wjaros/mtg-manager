
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect
from tests.helpers import fixture_cards

CARDS = fixture_cards()


def card_id(name: str, set_code: str | None = None) -> str:
    return next(c["id"] for c in CARDS if c["name"] == name and (set_code is None or c["set"] == set_code))


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


def new_deck(client, **kwargs) -> dict:
    resp = client.post("/api/decks", json={"name": "Giada angels", "format": "brawl", "platform": "arena", **kwargs})
    assert resp.status_code == 201, resp.text
    return resp.json()


def entries(deck: dict) -> dict[tuple[str, str], int]:
    return {(c["card"]["name"], c["board"]): c["quantity"] for c in deck["cards"]}


def test_create_list_update_delete(client):
    deck = new_deck(client)
    assert deck["counts"]["total"] == 0 and deck["cards"] == []
    assert [d["name"] for d in client.get("/api/decks").json()] == ["Giada angels"]

    updated = client.patch(f"/api/decks/{deck['id']}", json={"name": "  Angels  ", "format": "standardbrawl"}).json()
    assert (updated["name"], updated["format"], updated["platform"]) == ("Angels", "standardbrawl", "arena")

    assert client.patch(f"/api/decks/{deck['id']}", json={"format": "modern"}).status_code == 422
    assert client.delete(f"/api/decks/{deck['id']}").status_code == 204
    assert client.get(f"/api/decks/{deck['id']}").status_code == 404
    assert client.delete(f"/api/decks/{deck['id']}").status_code == 404


def test_add_and_remove_cards(client):
    deck_id = new_deck(client)["id"]
    plains = card_id("Plains")
    client.post(f"/api/decks/{deck_id}/cards", json={"card_id": plains, "quantity": 10})
    deck = client.post(f"/api/decks/{deck_id}/cards", json={"card_id": plains, "quantity": 5}).json()
    assert entries(deck) == {("Plains", "main"): 15}

    deck = client.delete(f"/api/decks/{deck_id}/cards/{plains}", params={"quantity": 4}).json()
    assert entries(deck) == {("Plains", "main"): 11}
    deck = client.delete(f"/api/decks/{deck_id}/cards/{plains}").json()
    assert entries(deck) == {}

    assert client.post(f"/api/decks/{deck_id}/cards", json={"card_id": "nope"}).status_code == 404
    assert client.delete(f"/api/decks/{deck_id}/cards/{plains}").status_code == 404
    assert client.post("/api/decks/999/cards", json={"card_id": plains}).status_code == 404


def test_commander_sets_identity_and_counts(client):
    deck_id = new_deck(client)["id"]
    giada = card_id("Giada, Font of Hope", "fdn")
    client.post(f"/api/decks/{deck_id}/cards", json={"card_id": giada, "board": "commander"})
    deck = client.post(f"/api/decks/{deck_id}/cards", json={"card_id": card_id("Serra Angel")}).json()

    assert deck["commander_card_id"] == giada
    assert deck["commander_name"] == "Giada, Font of Hope"
    assert deck["color_identity"] == ["W"]
    assert deck["counts"] == {"main": 1, "commander": 1, "companion": 0, "sideboard": 0, "maybe": 0, "total": 2}

    summary = client.get("/api/decks").json()[0]
    assert summary["commander_name"] == "Giada, Font of Hope" and summary["counts"]["total"] == 2

    assert deck["cover_card_id"] == giada
    deck = client.delete(f"/api/decks/{deck_id}/cards/{giada}", params={"board": "commander"}).json()
    # Without a commander: the main deck's colours and one of its cards as the cover.
    assert deck["commander_card_id"] is None and deck["color_identity"] == ["W"]
    assert deck["cover_card_id"] == card_id("Serra Angel")


def test_cover_without_commander(client):
    deck_id = new_deck(client, name="Orzhov", format="freeform", platform="paper")["id"]
    assert client.get(f"/api/decks/{deck_id}").json()["cover_card_id"] is None
    for name in ("Plains", "Angel of the Ruins", "Blind Hunter"):
        deck = client.post(f"/api/decks/{deck_id}/cards", json={"card_id": card_id(name)}).json()
    # The costliest creature, as there is no legendary one.
    assert deck["cover_card_id"] == card_id("Angel of the Ruins")
    assert deck["color_identity"] == ["W", "B"]

    deck = client.post(f"/api/decks/{deck_id}/cards", json={"card_id": card_id("Barbara Wright")}).json()
    assert deck["cover_card_id"] == card_id("Barbara Wright")  # a legendary creature beats a bigger one
    assert client.get("/api/decks").json()[0]["cover_card_id"] == card_id("Barbara Wright")


def test_partner_commanders_union_identity(client):
    deck_id = new_deck(client, format="commander", platform="paper")["id"]
    client.post(f"/api/decks/{deck_id}/cards", json={"card_id": card_id("The Fourth Doctor"), "board": "commander"})
    deck = client.post(
        f"/api/decks/{deck_id}/cards", json={"card_id": card_id("Sarah Jane Smith"), "board": "commander"}
    ).json()
    assert deck["commander_name"] == "The Fourth Doctor & Sarah Jane Smith"
    assert deck["partner_card_id"] == card_id("Sarah Jane Smith")
    assert deck["color_identity"] == ["W", "U", "G"]


def test_move_between_boards_and_swap_printing(client):
    deck_id = new_deck(client)["id"]
    serra_ids = [c["id"] for c in CARDS if c["name"] == "Serra Angel"]
    client.post(f"/api/decks/{deck_id}/cards", json={"card_id": serra_ids[0], "quantity": 2})

    deck = client.patch(f"/api/decks/{deck_id}/cards/{serra_ids[0]}", json={"new_board": "maybe"}).json()
    assert entries(deck) == {("Serra Angel", "maybe"): 2}

    deck = client.patch(
        f"/api/decks/{deck_id}/cards/{serra_ids[0]}", json={"board": "maybe", "new_card_id": serra_ids[1]}
    ).json()
    assert [(c["card"]["id"], c["quantity"]) for c in deck["cards"]] == [(serra_ids[1], 2)]

    deck = client.patch(
        f"/api/decks/{deck_id}/cards/{serra_ids[1]}", json={"board": "maybe", "quantity": 1, "new_board": "main"}
    ).json()
    assert entries(deck) == {("Serra Angel", "main"): 1}
    assert client.patch(f"/api/decks/{deck_id}/cards/{serra_ids[0]}", json={}).status_code == 404


def test_replace_cards_merges_duplicates(client):
    deck_id = new_deck(client)["id"]
    plains, giada = card_id("Plains"), card_id("Giada, Font of Hope")
    deck = client.put(f"/api/decks/{deck_id}/cards", json=[
        {"card_id": giada, "board": "commander"},
        {"card_id": plains, "quantity": 20},
        {"card_id": plains, "quantity": 16},
    ]).json()
    assert entries(deck) == {("Giada, Font of Hope", "commander"): 1, ("Plains", "main"): 36}
    assert deck["commander_card_id"] == giada

    assert client.put(f"/api/decks/{deck_id}/cards", json=[{"card_id": "nope"}]).status_code == 404
    # Failed replace leaves the deck untouched.
    assert entries(client.get(f"/api/decks/{deck_id}").json())[("Plains", "main")] == 36


def test_deleting_deck_removes_its_cards(client, tmp_path):
    deck_id = new_deck(client)["id"]
    client.post(f"/api/decks/{deck_id}/cards", json={"card_id": card_id("Plains")})
    client.delete(f"/api/decks/{deck_id}")
    conn = connect(tmp_path / "data" / "db.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM deck_cards").fetchone()[0] == 0
    conn.close()


def test_card_category(client):
    deck_id = new_deck(client)["id"]
    sol = card_id("Sol Ring")
    client.post(f"/api/decks/{deck_id}/cards", json={"card_id": sol})
    deck = client.patch(f"/api/decks/{deck_id}/cards/{sol}", json={"category": " Rampa "}).json()
    assert deck["cards"][0]["category"] == "Rampa"
    # Moving the card keeps its category; an empty string clears it.
    deck = client.patch(f"/api/decks/{deck_id}/cards/{sol}", json={"new_board": "maybe"}).json()
    assert (deck["cards"][0]["board"], deck["cards"][0]["category"]) == ("maybe", "Rampa")
    deck = client.patch(f"/api/decks/{deck_id}/cards/{sol}", json={"board": "maybe", "category": ""}).json()
    assert deck["cards"][0]["category"] is None
