import time

import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from tests.test_missing import ADDED, PRECON, import_deck, upgrade_text


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


def card(client, name: str) -> dict:
    return client.get("/api/cards", params={"q": f'!"{name}"'}).json()["items"][0]


def holdings(client, deck_id: int) -> dict[str, dict]:
    names = {c["card"]["oracle_id"]: c["card"]["name"] for c in client.get(f"/api/decks/{deck_id}").json()["cards"]}
    return {names[h["oracle_id"]]: h for h in client.get(f"/api/decks/{deck_id}/holdings").json()}


def print_text(client, items: list[dict], deck_id: int | None = None) -> dict:
    """A text-proxy print (no images to download); returns the finished job's status."""
    job = client.post("/api/print/jobs", json={"items": items, "style": "text", "deck_id": deck_id,
                                               "title": "Test"}).json()
    for _ in range(200):
        status = client.get(f"/api/print/jobs/{job['id']}").json()
        if status["stage"] in ("done", "error"):
            return status
        time.sleep(0.05)
    raise AssertionError("print job did not finish")


@pytest.fixture
def decks(client):
    """The precon owned in its box, and an upgrade needing ADDED (not owned) + the precon's cards."""
    precon = import_deck(client, PRECON)
    assert client.post(f"/api/decks/{precon}/collection").status_code == 200
    upgrade = import_deck(client, upgrade_text())
    return precon, upgrade


def test_print_from_deck_marks_proxies_in_its_box(client, decks):
    _, upgrade = decks
    missing = [c for c in client.get(f"/api/decks/{upgrade}/proxy-candidates").json() if c["reason"] == "missing"]
    assert {c["name"] for c in missing} == set(ADDED)
    token = "008f776f-c7ce-47ed-bc04-2ab9f9bcd8ae"  # a Clue token: not a deck card, never marked
    status = print_text(client, [{"card_id": c["card_id"], "qty": 2} for c in missing] + [{"card_id": token, "qty": 1}],
                        deck_id=upgrade)
    job_id = status["print_job_id"]
    assert status["stage"] == "done" and job_id

    entry = client.get(f"/api/print/history/{job_id}").json()
    assert entry["deck_id"] == upgrade and entry["card_count"] == 2 * len(missing) + 1 and entry["page_count"] == 1
    # Only what the deck lacks: one copy of each (two were printed), no token.
    preview = client.post(f"/api/print/history/{job_id}/mark-proxies", json={"dry_run": True}).json()
    assert preview["count"] == len(ADDED) and preview["location"] is None  # the deck has no box yet
    result = client.post(f"/api/print/history/{job_id}/mark-proxies", json={}).json()
    assert result["count"] == len(ADDED)
    box = result["location"]["id"]
    assert client.get(f"/api/decks/{upgrade}").json()["location_id"] == box  # the box was created

    proxies = client.get("/api/collection", params={"kind": "proxy"}).json()
    assert {p["card"]["name"] for p in proxies} == set(ADDED)
    assert all(p["location"]["id"] == box and p["print_job_id"] == job_id and p["printed_at"] for p in proxies)
    assert client.get(f"/api/print/history/{job_id}").json()["marked_at"]
    # Marking again adds nothing: the proxies already cover the deck.
    assert client.post(f"/api/print/history/{job_id}/mark-proxies", json={}).json()["count"] == 0
    assert client.get("/api/print/history").json()[0]["proxies"] == len(ADDED)


def test_coverage(client, decks):
    precon, upgrade = decks
    bolt = card(client, "Lightning Bolt")  # one of ADDED
    assert client.post(f"/api/decks/{upgrade}/proxies", json={"card_id": bolt["id"]}).status_code == 201

    h = holdings(client, upgrade)
    assert (h["Lightning Bolt"]["state"], h["Lightning Bolt"]["proxy"], h["Lightning Bolt"]["real"]) == ("proxy", 1, 0)
    assert h["Serra Angel"]["state"] == "missing" and h["Serra Angel"]["uncovered"] == 1
    assert h["Arcane Signet"]["state"] == "other_deck"  # the only copy is in the precon's box
    # Totals per deck: real + proxy + uncovered = deck size.
    totals = [sum(x[k] for x in h.values()) for k in ("real", "proxy", "uncovered")]
    deck = client.get(f"/api/decks/{upgrade}").json()
    size = sum(c["quantity"] for c in deck["cards"] if c["board"] in ("main", "commander", "companion", "sideboard"))
    assert sum(totals) == size and totals[1] == 1

    # The precon has all its cards, real; a proxy in another deck's box doesn't count anywhere else.
    assert all(x["state"] is None for x in holdings(client, precon).values())
    issues = client.get(f"/api/decks/{upgrade}/validate").json()["issues"]
    assert any(i["code"] == "proxies" and i["severity"] == "info" for i in issues)


def test_proxies_are_not_owned(client):
    bolt = card(client, "Lightning Bolt")
    box = client.post("/api/locations", json={"name": "Box", "kind": "deck"}).json()
    item = client.post("/api/collection", json={"card_id": bolt["id"], "kind": "proxy", "location_id": box["id"],
                                                "finish": "foil", "condition": "LP"}).json()
    assert (item["kind"], item["finish"], item["condition"]) == ("proxy", "nonfoil", "NM")  # don't apply to proxies

    stats = client.get("/api/collection/stats").json()
    assert (stats["copies"], stats["proxies"]) == (0, 1)
    found = client.get("/api/cards", params={"q": "Lightning Bolt", "owned": "owned"}).json()
    assert found["total"] == 0
    with_proxies = client.get("/api/cards", params={"q": "Lightning Bolt", "owned": "owned", "include_proxies": True})
    assert with_proxies.json()["total"] == 1
    assert card(client, "Lightning Bolt")["owned"] == 0
    assert client.get("/api/collection/export", params={"format": "arena"}).text.strip() == ""
    loc = next(loc for loc in client.get("/api/locations").json() if loc["id"] == box["id"])
    assert (loc["card_count"], loc["proxy_count"]) == (0, 1)
    usage = client.get(f"/api/cards/{bolt['id']}/usage").json()
    assert (usage["owned"], usage["proxies"], usage["locations"][0]["kind"]) == (0, 1, "proxy")


def test_candidates_skip_proxied_cards(client, decks):
    _, upgrade = decks
    bolt = card(client, "Lightning Bolt")
    client.post(f"/api/decks/{upgrade}/proxies", json={"card_id": bolt["id"]})
    names = {c["name"] for c in client.get(f"/api/decks/{upgrade}/proxy-candidates").json()}
    assert "Lightning Bolt" not in names and "Serra Angel" in names
    again = client.get(f"/api/decks/{upgrade}/proxy-candidates", params={"include_proxied": True}).json()
    assert "Lightning Bolt" in {c["name"] for c in again}  # printing worn proxies again


def test_replace_with_real(client, decks):
    _, upgrade = decks
    bolt, serra = card(client, "Lightning Bolt"), card(client, "Serra Angel")
    proxy = client.post(f"/api/decks/{upgrade}/proxies", json={"card_id": bolt["id"], "quantity": 2}).json()
    box = proxy["location"]["id"]

    # Bought one: a new real copy in the box, one proxy left.
    real = client.post(f"/api/collection/{proxy['id']}/replace-with-real", json={"finish": "foil", "condition": "EX"}).json()
    assert (real["kind"], real["location"]["id"], real["finish"], real["condition"]) == ("real", box, "foil", "EX")
    assert client.get("/api/collection", params={"kind": "proxy"}).json()[0]["quantity"] == 1

    # A loose real copy you already had moves into the box instead.
    serra_proxy = client.post(f"/api/decks/{upgrade}/proxies", json={"card_id": serra["id"]}).json()
    loose = client.post("/api/collection", json={"card_id": serra["id"], "quantity": 2}).json()
    moved = client.post(f"/api/collection/{serra_proxy['id']}/replace-with-real",
                        json={"use_existing_item_id": loose["id"]}).json()
    assert moved["location"]["id"] == box and moved["quantity"] == 1
    serras = {(i["kind"], i["location"]["id"] if i["location"] else None): i["quantity"]
              for i in client.get("/api/collection", params={"card_id": serra["id"]}).json()}
    assert serras == {("real", box): 1, ("real", None): 1}  # no proxy left

    assert client.post(f"/api/collection/{loose['id']}/replace-with-real", json={}).status_code == 422  # not a proxy


def test_missing_export_with_and_without_proxied(client, decks):
    _, upgrade = decks
    bolt = card(client, "Lightning Bolt")
    client.post(f"/api/decks/{upgrade}/proxies", json={"card_id": bolt["id"]})
    report = client.get(f"/api/decks/{upgrade}/missing").json()
    entry = next(e for e in report["entries"] if e["name"] == "Lightning Bolt")
    assert (entry["missing"], entry["proxied"]) == (1, 1)  # still to buy

    shopping = client.get(f"/api/decks/{upgrade}/missing/export", params={"format": "cardmarket"}).text
    assert "1 Lightning Bolt" in shopping
    no_copy = client.get(f"/api/decks/{upgrade}/missing/export",
                         params={"format": "cardmarket", "include_proxied": False}).text
    assert "Lightning Bolt" not in no_copy and "1 Serra Angel" in no_copy


def test_backup_keeps_proxies(client):
    bolt = card(client, "Lightning Bolt")
    box = client.post("/api/locations", json={"name": "Box", "kind": "deck"}).json()
    client.post("/api/collection", json={"card_id": bolt["id"], "kind": "proxy", "location_id": box["id"]})
    client.post("/api/collection", json={"card_id": bolt["id"]})
    backup = client.get("/api/backup/export").json()
    client.post("/api/backup/import", json=backup, params={"replace": True})
    kinds = sorted((i["kind"], bool(i["printed_at"])) for i in client.get("/api/collection").json())
    assert kinds == [("proxy", True), ("real", False)]
