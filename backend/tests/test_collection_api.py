import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from tests.helpers import SEEDS_DIR, fixture_cards

CARDS = fixture_cards()


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


def printing(name: str, set_code: str | None = None) -> dict:
    return next(c for c in CARDS if c["name"] == name and (set_code is None or c["set"] == set_code))


def add(client, card_id: str, **body) -> dict:
    resp = client.post("/api/collection", json={"card_id": card_id, **body})
    assert resp.status_code == 201, resp.text
    return resp.json()


def search(client, **params) -> list[dict]:
    resp = client.get("/api/cards", params={"page_size": 200, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def test_add_merges_identical_entries(client):
    serra = printing("Serra Angel", "fdn")
    first = add(client, serra["id"])
    assert (first["quantity"], first["finish"], first["language"], first["condition"]) == (1, "nonfoil", "en", "NM")
    again = add(client, serra["id"], quantity=2)
    assert again["id"] == first["id"] and again["quantity"] == 3

    foil = add(client, serra["id"], finish="foil")
    assert foil["id"] != first["id"]
    assert client.get("/api/collection/stats").json() == {"copies": 4, "printings": 1, "cards": 1, "proxies": 0}


def test_update_and_remove(client):
    item = add(client, printing("Sol Ring")["id"], quantity=3)
    box = client.post("/api/locations", json={"name": "Pudełko 1"}).json()

    updated = client.patch(f"/api/collection/{item['id']}", json={"condition": "LP", "location_id": box["id"]}).json()
    assert updated["condition"] == "LP" and updated["location"]["name"] == "Pudełko 1"
    assert client.get("/api/locations").json()[0]["card_count"] == 3

    assert client.delete(f"/api/collection/{item['id']}", params={"quantity": 2}).json()["quantity"] == 1
    assert client.delete(f"/api/collection/{item['id']}").json() is None
    assert client.get("/api/collection").json() == []
    assert client.delete(f"/api/collection/{item['id']}").status_code == 404
    assert client.post("/api/collection", json={"card_id": "nope"}).status_code == 404


def test_deleting_location_keeps_cards(client):
    box = client.post("/api/locations", json={"name": "Binder", "kind": "binder"}).json()
    item = add(client, printing("Plains")["id"], location_id=box["id"])
    assert client.delete(f"/api/locations/{box['id']}").status_code == 204
    assert client.get(f"/api/collection?card_id={item['card']['id']}").json()[0]["location"] is None


def test_owned_counts_and_filter(client):
    giada_fdn = printing("Giada, Font of Hope", "fdn")
    add(client, giada_fdn["id"], quantity=2)

    giada = next(c for c in search(client, q="giada") if c["name"] == "Giada, Font of Hope")
    assert giada["owned"] == 2

    owned = [c["name"] for c in search(client, owned="owned")]
    assert owned == ["Giada, Font of Hope"]
    missing = [c["name"] for c in search(client, owned="missing", q="giada")]
    assert missing == ["Errant and Giada", "Luxior, Giada's Gift"]

    # Printing mode: owned means exactly that printing.
    prints = search(client, q="Giada, Font of Hope", unique="prints", owned="owned")
    assert [c["id"] for c in prints] == [giada_fdn["id"]]
    other_prints = search(client, q="Giada, Font of Hope", unique="prints", owned="missing")
    assert giada_fdn["id"] not in {c["id"] for c in other_prints}
    assert all(c["owned"] == 2 and c["owned_printing"] == 0 for c in other_prints)


def import_seed(client, file: str) -> dict:
    report = client.post("/api/import/parse", json={"text": (SEEDS_DIR / file).read_text(encoding="utf-8")}).json()
    meta = report["meta"]
    return client.post("/api/import/commit", json={
        "name": meta["name"], "format": meta["format"], "platform": meta["platform"],
        "entries": [{"card_id": l["card"]["id"], "quantity": l["quantity"], "board": l["board"]} for l in report["lines"]],
    }).json()


def test_deck_to_collection(client):
    deck = import_seed(client, "giada-font-of-hope.txt")
    result = client.post(f"/api/decks/{deck['id']}/collection").json()
    assert result["added"] == 100
    assert result["location"]["name"] == "Giada, Font of Hope" and result["location"]["kind"] == "deck"
    assert client.get(f"/api/decks/{deck['id']}").json()["location_id"] == result["location"]["id"]

    plains = client.get("/api/collection", params={"location_id": result["location"]["id"]}).json()
    assert next(i for i in plains if i["card"]["name"] == "Plains")["quantity"] == 36
    assert all(i["source"] == "import" for i in plains)

    # Second time: refused unless replacing (so cards are never doubled by accident).
    assert client.post(f"/api/decks/{deck['id']}/collection").status_code == 409
    again = client.post(f"/api/decks/{deck['id']}/collection", params={"replace": True}).json()
    assert again["added"] == 100 and again["location"]["card_count"] == 100
    assert client.get("/api/collection/stats").json()["copies"] == 100

    owned = {c["name"] for c in search(client, owned="owned")}
    assert {"Giada, Font of Hope", "Serra Angel", "Plains"} <= owned


def test_delete_deck_keeps_or_removes_its_box(client):
    serra = printing("Serra Angel", "fdn")
    kept = import_seed(client, "giada-font-of-hope.txt")
    box = client.post(f"/api/decks/{kept['id']}/collection").json()["location"]
    assert client.delete(f"/api/decks/{kept['id']}").status_code == 204
    # By default the box and its cards stay in the collection.
    assert client.get("/api/collection/stats").json()["copies"] == 100
    assert box["id"] in {loc["id"] for loc in client.get("/api/locations").json()}

    deck = import_seed(client, "giada-font-of-hope.txt")
    box = client.post(f"/api/decks/{deck['id']}/collection").json()["location"]
    add(client, serra["id"], kind="proxy", location_id=box["id"])
    loose = add(client, serra["id"])
    assert client.delete(f"/api/decks/{deck['id']}", params={"with_cards": True}).status_code == 204
    assert client.get(f"/api/decks/{deck['id']}").status_code == 404
    assert box["id"] not in {loc["id"] for loc in client.get("/api/locations").json()}
    items = client.get("/api/collection").json()
    assert all(i["location"] is None or i["location"]["id"] != box["id"] for i in items)
    assert loose["id"] in {i["id"] for i in items}
    assert client.get("/api/collection/stats").json()["copies"] == 101
    # A deck without a box: nothing else is touched.
    empty = client.post("/api/decks", json={"name": "Empty", "format": "commander", "platform": "paper"}).json()
    assert client.delete(f"/api/decks/{empty['id']}", params={"with_cards": True}).status_code == 204
    assert client.get("/api/collection/stats").json()["copies"] == 101


def test_collection_export(client):
    serra = printing("Serra Angel", "fdn")
    bolt = next(c for c in CARDS if c["name"] == "Lightning Bolt")
    binder = client.post("/api/locations", json={"name": "Binder"}).json()
    add(client, serra["id"], quantity=2)
    add(client, serra["id"], finish="foil", condition="LP", location_id=binder["id"])
    add(client, bolt["id"], quantity=4, language="pl", location_id=binder["id"])

    arena = client.get("/api/collection/export", params={"format": "arena"})
    assert "attachment" not in arena.headers.get("content-disposition", "")
    serra_line = f"3 Serra Angel (FDN) {serra['collector_number']}"  # finishes merged per printing
    bolt_line = f"4 Lightning Bolt ({bolt['set'].upper()}) {bolt['collector_number']}"
    assert arena.text == f"{bolt_line}\n{serra_line}\n"

    only_binder = client.get("/api/collection/export", params={"format": "arena", "location_id": binder["id"]}).text
    assert only_binder == f"{bolt_line}\n1 Serra Angel (FDN) {serra['collector_number']}\n"
    assert client.get("/api/collection/export", params={"format": "arena", "unassigned": True}).text == \
        f"2 Serra Angel (FDN) {serra['collector_number']}\n"
    assert "attachment" in client.get("/api/collection/export", params={"download": True}).headers["content-disposition"]

    csv_resp = client.get("/api/collection/export", params={"format": "csv"})
    assert csv_resp.headers["content-type"].startswith("text/csv")
    rows = [line.split(",") for line in csv_resp.text.strip().split("\n")]
    assert rows[0][:5] == ["Count", "Name", "Edition", "Edition Name", "Collector Number"]
    assert [(r[0], r[1], r[5], r[6], r[7], r[8], r[9]) for r in rows[1:]] == [
        ("4", "Lightning Bolt", "", "NM", "pl", "Binder", bolt["id"]),
        ("2", "Serra Angel", "", "NM", "en", "", serra["id"]),
        ("1", "Serra Angel", "foil", "LP", "en", "Binder", serra["id"]),
    ]


def test_card_usage_and_free_filter(client):
    giada = import_seed(client, "giada-font-of-hope.txt")
    box = client.post(f"/api/decks/{giada['id']}/collection").json()["location"]
    other = client.post("/api/decks", json={"name": "Angels 2", "format": "commander"}).json()
    serra = printing("Serra Angel", "fdn")
    binder = client.post("/api/locations", json={"name": "Binder"}).json()
    add(client, serra["id"], location_id=binder["id"])
    bolt = next(c for c in CARDS if c["name"] == "Lightning Bolt")
    add(client, bolt["id"], quantity=2)

    # Building the second deck: Serra Angel sits in Giada's box and in the binder.
    usage = client.get(f"/api/cards/{serra['id']}/usage", params={"deck": other["id"]}).json()
    assert (usage["in_deck"], usage["owned"], usage["free"]) == (0, 2, 1)
    assert [(loc["name"], loc["deck_id"], loc["quantity"]) for loc in usage["locations"]] == [
        ("Binder", None, 1), (box["name"], giada["id"], 1)]
    assert [(d["name"], d["quantity"]) for d in usage["decks"]] == [("Giada, Font of Hope", 1)]
    # From Giada's own point of view its box counts as free and the deck itself is not "another deck".
    own = client.get(f"/api/cards/{serra['id']}/usage", params={"deck": giada["id"]}).json()
    assert (own["in_deck"], own["free"], own["decks"]) == (1, 2, [])
    assert client.get("/api/cards/nope/usage").status_code == 404

    free = {c["name"] for c in search(client, owned="free", deck=other["id"])}
    assert {"Serra Angel", "Lightning Bolt"} <= free
    assert "Giada, Font of Hope" not in free  # only in Giada's box
    assert "Giada, Font of Hope" in {c["name"] for c in search(client, owned="free", deck=giada["id"])}

    client.post(f"/api/decks/{other['id']}/cards", json={"card_id": serra["id"]})
    plains = printing("Plains")
    client.post(f"/api/decks/{other['id']}/cards", json={"card_id": plains["id"]})
    names = {c["name"] for c in search(client, not_in_deck=other["id"], q="angel")}
    assert "Serra Angel" not in names and names
    assert "Plains" in {c["name"] for c in search(client, not_in_deck=other["id"], q="plains")}


def test_list_into_collection(client):
    """A product that is not a deck: decklist report, then straight into one location."""
    text = """# preferred-sets: fra
Deck
# --- Half deck A ---
7 Plains
1 Serra Angel (J25) 251
# --- Half deck B ---
8 Plains
1 Serra Angel (J25) 251
1 Sol Ring *F*
"""
    report = client.post("/api/import/parse", json={"text": text}).json()
    assert report["counts"]["not_found"] == 0
    box = client.post("/api/locations", json={"name": "Product box", "kind": "box"}).json()
    entries = [{"card_id": l["card"]["id"], "quantity": l["quantity"], "finish": "foil" if l["foil"] else "nonfoil"}
               for l in report["lines"]]
    sol_ring = next(l for l in report["lines"] if l["name"] == "Sol Ring")["card"]
    result = client.post("/api/collection/import/commit", json={"entries": entries, "location_id": box["id"]}).json()
    assert result == {"added": 18, "entries": 5}
    items = client.get("/api/collection", params={"location_id": box["id"]}).json()
    # Identical entries merge: one row per printing / finish.
    assert sorted((i["card"]["name"], i["card"]["set_code"], i["quantity"]) for i in items) == [
        ("Plains", "fra", 15), ("Serra Angel", "j25", 2), ("Sol Ring", sol_ring["set_code"], 1)]
    assert next(i for i in items if i["card"]["name"] == "Sol Ring")["finish"] == "foil"
