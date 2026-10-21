import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect, migrate
from tests.helpers import fixture_cards

CARDS = fixture_cards()


def printings(name: str) -> list[str]:
    return [c["id"] for c in CARDS if c["name"] == name]


BOLT, BOLT_2 = printings("Lightning Bolt")[:2]
SERRA = printings("Serra Angel")[0]
PLAINS = printings("Plains")[0]


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


def new_deck(client) -> int:
    return client.post("/api/decks", json={"name": "Test", "format": "freeform", "platform": "paper"}).json()["id"]


def add(client, deck_id: int, card_id: str, quantity: int = 1, board: str = "main") -> dict:
    return client.post(f"/api/decks/{deck_id}/cards", json={"card_id": card_id, "quantity": quantity, "board": board}).json()


def changes(deck: dict) -> dict[tuple[str, str], tuple[int, int, bool]]:
    return {(c["name"], c["board"]): (c["before"], c["after"], c["printing_changed"]) for c in deck["changes"]["cards"]}


def test_new_deck_is_all_unsaved_until_saved(client):
    deck_id = new_deck(client)
    deck = add(client, deck_id, BOLT, 4)
    assert deck["changes"]["base_number"] is None
    assert changes(deck) == {("Lightning Bolt", "main"): (0, 4, False)}
    assert deck["unsaved_changes"] == 1

    v1 = client.post(f"/api/decks/{deck_id}/versions", json={"note": " pierwsza "})
    assert v1.status_code == 201
    assert {k: v1.json()[k] for k in ("number", "note", "total", "added", "removed")} == {
        "number": 1, "note": "pierwsza", "total": 4, "added": 4, "removed": 0}
    deck = client.get(f"/api/decks/{deck_id}").json()
    assert deck["changes"]["base_number"] == 1 and changes(deck) == {} and deck["unsaved_changes"] == 0
    # Nothing to save twice.
    assert client.post(f"/api/decks/{deck_id}/versions", json={}).status_code == 409


def test_changes_since_last_version(client):
    deck_id = new_deck(client)
    add(client, deck_id, BOLT, 4)
    add(client, deck_id, SERRA, 2)
    client.post(f"/api/decks/{deck_id}/versions", json={})

    client.delete(f"/api/decks/{deck_id}/cards/{SERRA}", params={"board": "main"})  # removed
    client.delete(f"/api/decks/{deck_id}/cards/{BOLT}", params={"board": "main", "quantity": 1})  # fewer
    add(client, deck_id, PLAINS, 10)  # added
    add(client, deck_id, SERRA, 1, "sideboard")  # moved to another board = new entry there
    deck = client.patch(f"/api/decks/{deck_id}", json={"format": "commander"}).json()
    assert changes(deck) == {
        ("Lightning Bolt", "main"): (4, 3, False),
        ("Plains", "main"): (0, 10, False),
        ("Serra Angel", "main"): (2, 0, False),
        ("Serra Angel", "sideboard"): (0, 1, False),
    }
    removed = next(c for c in deck["changes"]["cards"] if c["after"] == 0)
    assert removed["card"]["id"] == SERRA  # removed cards keep their card data for display
    assert deck["changes"]["format_before"] == "freeform" and deck["changes"]["platform_before"] is None
    assert deck["unsaved_changes"] == 5
    assert client.get("/api/decks").json()[0]["unsaved_changes"] == 5


def test_printing_swap_is_not_a_removal(client):
    deck_id = new_deck(client)
    add(client, deck_id, BOLT, 4)
    client.post(f"/api/decks/{deck_id}/versions", json={})
    deck = client.patch(f"/api/decks/{deck_id}/cards/{BOLT}", json={"board": "main", "new_card_id": BOLT_2}).json()
    assert changes(deck) == {("Lightning Bolt", "main"): (4, 4, True)}
    # Swapping back: nothing changed.
    deck = client.patch(f"/api/decks/{deck_id}/cards/{BOLT_2}", json={"board": "main", "new_card_id": BOLT}).json()
    assert changes(deck) == {}


def test_history_and_restore(client):
    deck_id = new_deck(client)
    add(client, deck_id, BOLT, 4)
    v1 = client.post(f"/api/decks/{deck_id}/versions", json={"note": "v1"}).json()
    client.delete(f"/api/decks/{deck_id}/cards/{BOLT}", params={"board": "main"})
    add(client, deck_id, SERRA, 3)
    v2 = client.post(f"/api/decks/{deck_id}/versions", json={"note": "v2"}).json()
    assert (v2["number"], v2["added"], v2["removed"], v2["total"]) == (2, 3, 4, 3)

    history = client.get(f"/api/decks/{deck_id}/versions").json()
    assert [v["note"] for v in history] == ["v2", "v1"]

    detail = client.get(f"/api/decks/{deck_id}/versions/{v1['id']}").json()
    assert [(c["card"]["id"], c["quantity"]) for c in detail["cards"]] == [(BOLT, 4)]
    assert [(c["name"], c["before"], c["after"]) for c in detail["changes"]] == [("Lightning Bolt", 0, 4)]
    to_current = client.get(f"/api/decks/{deck_id}/versions/{v1['id']}", params={"compare": "current"}).json()
    assert sorted((c["name"], c["before"], c["after"]) for c in to_current["changes"]) == [
        ("Lightning Bolt", 4, 0), ("Serra Angel", 0, 3)]

    restored = client.post(f"/api/decks/{deck_id}/versions/{v1['id']}/restore").json()
    assert [(c["card"]["id"], c["quantity"]) for c in restored["cards"]] == [(BOLT, 4)]
    # Restoring is a change on top of v2 until saved as v3.
    assert restored["changes"]["base_number"] == 2 and restored["unsaved_changes"] == 2
    assert client.post(f"/api/decks/{deck_id}/versions", json={"note": "back"}).json()["number"] == 3

    assert client.get(f"/api/decks/{deck_id}/versions/999").status_code == 404
    other = new_deck(client)
    assert client.get(f"/api/decks/{other}/versions/{v1['id']}").status_code == 404
    assert client.get("/api/decks/999/versions").status_code == 404


def test_import_saves_first_version(client):
    deck = client.post("/api/import/commit", json={
        "name": "Imported", "entries": [{"card_id": BOLT, "quantity": 4}],
    }).json()
    assert deck["changes"]["base_number"] == 1 and deck["unsaved_changes"] == 0
    assert client.get(f"/api/decks/{deck['id']}/versions").json()[0]["note"] == "Import"


def test_migration_snapshots_existing_decks(tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    migrate(conn, until=3)
    conn.execute("INSERT INTO cards(id, name) VALUES ('c1', 'X')")
    conn.execute("INSERT INTO decks(id, name) VALUES (1, 'Old')")
    conn.execute("INSERT INTO deck_cards(deck_id, card_id, quantity) VALUES (1, 'c1', 3)")
    conn.commit()
    migrate(conn)
    row = conn.execute("SELECT number, note, cards FROM deck_versions WHERE deck_id = 1").fetchone()
    assert (row[0], row[1]) == (1, "Stan początkowy")
    assert '"quantity":3' in row[2]
