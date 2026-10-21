import csv
import io

import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect
from tests.helpers import SEEDS_DIR

PRECON = (SEEDS_DIR / "quintorius-lorehold-spirit.txt").read_text(encoding="utf-8")
# An upgrade of the precon: swap a few cards, one more Plains.
REMOVED = ["Anger", "Millikin", "Squee, Goblin Nabob"]
ADDED = ["Lightning Bolt", "Serra Angel", "Seal Away"]


def upgrade_text() -> str:
    lines = []
    for line in PRECON.splitlines():
        if any(line == f"1 {name}" for name in REMOVED):
            continue
        if line == "11 Plains":
            line = "12 Plains"
        if line == "6 Mountain":
            line = "5 Mountain"
        lines.append(line)
    lines += [f"1 {name}" for name in ADDED]
    return "\n".join(lines).replace("# name: Quintorius – Lorehold Spirit (precon)", "# name: Quintorius upgrade")


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


def import_deck(client, text: str) -> int:
    report = client.post("/api/import/parse", json={"text": text}).json()
    assert report["counts"]["not_found"] == 0, [l["name"] for l in report["lines"] if not l["card"]]
    meta = report["meta"]
    return client.post("/api/import/commit", json={
        "name": meta["name"], "format": meta["format"] or "commander", "platform": "paper",
        "entries": [{"card_id": l["card"]["id"], "quantity": l["quantity"], "board": l["board"]} for l in report["lines"]],
    }).json()["id"]


def missing(client, deck_id: int, **params) -> dict:
    resp = client.get(f"/api/decks/{deck_id}/missing", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_upgrade_shows_only_new_cards(client):
    precon = import_deck(client, PRECON)
    assert client.post(f"/api/decks/{precon}/collection").status_code == 200
    upgrade = import_deck(client, upgrade_text())

    report = missing(client, upgrade)
    got = {e["name"]: e["missing"] for e in report["entries"]}
    assert got == {**{name: 1 for name in ADDED}, "Plains": 1}
    assert report["missing_copies"] == 4 and report["missing_cards"] == 4
    plains = next(e for e in report["entries"] if e["name"] == "Plains")
    assert (plains["needed"], plains["owned"], plains["available"]) == (12, 11, 11)
    assert report["total_eur"] >= 0 and report["prices_as_of"]

    assert missing(client, precon)["entries"] == []


def test_excluding_other_decks_boxes(client):
    precon = import_deck(client, PRECON)
    client.post(f"/api/decks/{precon}/collection")
    upgrade = import_deck(client, upgrade_text())

    # Every owned copy sits in the precon's box, so the upgrade would need its own set of cards.
    report = missing(client, upgrade, exclude_other_decks=True)
    assert report["exclude_other_decks"] is True
    assert report["missing_copies"] == 100
    plains = next(e for e in report["entries"] if e["name"] == "Plains")
    assert (plains["owned"], plains["available"], plains["missing"]) == (11, 0, 12)

    # The precon's own box still counts for the precon.
    assert missing(client, precon, exclude_other_decks=True)["entries"] == []


def test_loose_copies_count_for_every_deck(client):
    precon = import_deck(client, PRECON)
    bolt = client.get("/api/cards", params={"q": "lightning bolt"}).json()["items"][0]
    client.post("/api/collection", json={"card_id": bolt["id"]})  # no location
    client.post(f"/api/decks/{precon}/collection")
    upgrade = import_deck(client, upgrade_text())

    names = {e["name"] for e in missing(client, upgrade, exclude_other_decks=True)["entries"]}
    assert "Lightning Bolt" not in names


def test_exports(client):
    precon = import_deck(client, PRECON)
    client.post(f"/api/decks/{precon}/collection")
    upgrade = import_deck(client, upgrade_text())

    cardmarket = client.get(f"/api/decks/{upgrade}/missing/export", params={"format": "cardmarket"}).text
    assert sorted(cardmarket.splitlines()) == sorted(["1 Lightning Bolt", "1 Plains", "1 Seal Away", "1 Serra Angel"])

    text = client.get(f"/api/decks/{upgrade}/missing/export", params={"format": "text"}).text
    assert all(line.count("(") == 1 for line in text.splitlines())

    resp = client.get(f"/api/decks/{upgrade}/missing/export", params={"format": "csv"})
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert {r["name"] for r in rows} == {"Lightning Bolt", "Plains", "Seal Away", "Serra Angel"}
    assert all(r["quantity"] == "1" and r["set_code"] and r["scryfall_id"] for r in rows)


def test_unknown_deck(client):
    assert client.get("/api/decks/999/missing").status_code == 404
    assert client.get("/api/decks/999/missing/export").status_code == 404


def test_collection_item_filters(client):
    precon = import_deck(client, PRECON)
    box = client.post(f"/api/decks/{precon}/collection").json()["location"]
    bolt = client.get("/api/cards", params={"q": "lightning bolt"}).json()["items"][0]
    client.post("/api/collection", json={"card_id": bolt["id"]})

    loose = client.get("/api/collection", params={"unassigned": True}).json()
    assert [i["card"]["name"] for i in loose] == ["Lightning Bolt"]
    in_box = client.get("/api/collection", params={"location_id": box["id"]}).json()
    assert sum(i["quantity"] for i in in_box) == 100
    plains = client.get("/api/collection", params={"q": "plai"}).json()
    assert {i["card"]["name"] for i in plains} == {"Plains", "Mistveil Plains"}


def test_holdings_per_card(client):
    """Deck view markers: missing (not owned) and elsewhere (owned, not in this deck's box)."""
    precon = import_deck(client, PRECON)
    upgrade = import_deck(client, upgrade_text())

    def holdings(deck_id):
        resp = client.get(f"/api/decks/{deck_id}/holdings")
        assert resp.status_code == 200, resp.text
        return resp.json()

    # Nothing owned, no box: every card is missing, in_box unknown.
    before = holdings(precon)
    assert sum(h["needed"] for h in before) == 100
    assert all(h["missing"] == h["needed"] and h["owned"] == 0 and h["in_box"] is None for h in before)

    client.post(f"/api/decks/{precon}/collection")  # "I own this deck": all cards into its box
    assert all(h["missing"] == 0 and h["in_box"] == h["needed"] for h in holdings(precon))

    # The upgrade has no box: shared cards are owned (in the precon's box), the new ones are missing.
    up = holdings(upgrade)
    missing = {h["oracle_id"] for h in up if h["missing"]}
    deck = client.get(f"/api/decks/{upgrade}").json()
    names = {c["card"]["oracle_id"]: c["card"]["name"] for c in deck["cards"]}
    assert {names[o] for o in missing} == set(ADDED) | {"Plains"}  # 12 Plains in the upgrade, 11 owned
    assert all(h["in_box"] is None for h in up)
    assert all(h["state"] == "missing" for h in up if h["missing"])
    # Without a box of its own, the shared cards have to come out of the precon's box.
    shared = [h for h in up if not h["missing"]]
    assert shared and all(h["state"] == "other_deck" and h["other_decks"] == ["Quintorius – Lorehold Spirit (precon)"]
                          for h in shared)
    # A loose copy covers a card: no need to raid the precon.
    sol_ring = next(c for c in deck["cards"] if c["card"]["name"] == "Sol Ring")["card"]
    client.post("/api/collection", json={"card_id": sol_ring["id"]})
    assert next(h for h in holdings(upgrade) if h["oracle_id"] == sol_ring["oracle_id"])["state"] is None

    # With a box of its own, the shared cards are owned but elsewhere (in the precon's box).
    box = client.post("/api/locations", json={"name": "Upgrade box", "kind": "deck"}).json()
    conn = connect(client.app.state.settings.db_path)
    with conn:
        conn.execute("UPDATE decks SET location_id = ? WHERE id = ?", (box["id"], upgrade))
    conn.close()
    by_oracle = {h["oracle_id"]: h for h in holdings(upgrade) if not h["missing"]}
    assert all(h["in_box"] == 0 for h in by_oracle.values())
    assert by_oracle[sol_ring["oracle_id"]]["state"] == "elsewhere"  # the loose copy
    assert {h["state"] for o, h in by_oracle.items() if o != sol_ring["oracle_id"]} == {"other_deck"}
    assert client.get("/api/decks/999/holdings").status_code == 404
