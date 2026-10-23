import csv
import io
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect
from mtgdm.scryfall import ScryfallClient
from mtgdm.scryfall import tags as tags_module
from mtgdm.scryfall.tags import sync_tags
from tests.helpers import fixture_cards

CARDS = {c["name"]: c for c in fixture_cards()}
TAGGED = {
    "ramp": ["Sol Ring", "Arcane Signet"],
    "removal": ["Swords to Plowshares", "Path to Exile", "Lightning Bolt"],
    "draw": ["Bygone Bishop"],
}


class FakeSearch:
    """Scryfall's /cards/search as CSV pages; tiny page size to test paging."""

    def __init__(self):
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        query = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        self.requests.append(query)
        tag = query["q"].removeprefix("otag:")
        names = TAGGED.get(tag, [])
        page = int(query.get("page", 1))
        chunk = names[(page - 1) * 2:page * 2]
        if not chunk:
            return httpx.Response(422 if page > 1 else 404, json={"object": "error", "details": "no cards"})
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["name", "set", "collector_number", "scryfall_id"])
        for name in chunk:
            c = CARDS[name]
            writer.writerow([name, c["set"], c["collector_number"], c["id"]])
        return httpx.Response(200, text=out.getvalue(), headers={"Content-Type": "text/csv"})


@pytest.fixture
def scryfall(monkeypatch):
    monkeypatch.setattr(tags_module, "PAGE_SIZE", 2)
    fake = FakeSearch()
    return fake, ScryfallClient(httpx.Client(transport=httpx.MockTransport(fake)), min_interval=0)


def test_sync_tags_and_weekly_refresh(card_settings, scryfall):
    fake, client = scryfall
    conn = connect(card_settings.db_path)
    progress = []
    assert sync_tags(conn, client, lambda *p: progress.append(p)) == 6
    stored = {(tag, name) for tag, name in conn.execute(
        "SELECT t.tag, MIN(c.name) FROM card_tags t JOIN cards c ON c.oracle_id = t.oracle_id GROUP BY t.tag, t.oracle_id")}
    assert stored == {(tag, name) for tag, names in TAGGED.items() for name in names}
    assert progress[-1][0] == "tags"
    removal_pages = [int(q.get("page", 1)) for q in fake.requests if q["q"] == "otag:removal"]
    assert removal_pages == [1, 2]  # 3 cards at 2 per page: the short second page is the last
    assert all(q["format"] == "csv" for q in fake.requests)

    # Fresh for a week: no requests; forced or a week later: fetched again.
    count = len(fake.requests)
    assert sync_tags(conn, client) is None and len(fake.requests) == count
    assert sync_tags(conn, client, now=datetime.now(UTC) + timedelta(days=8)) == 6
    conn.close()


def test_tags_in_search_and_deck_stats(card_settings, scryfall):
    _, client = scryfall
    conn = connect(card_settings.db_path)
    sync_tags(conn, client)
    conn.close()
    with TestClient(create_app(card_settings)) as app:
        names = {c["name"] for c in app.get("/api/cards", params={"q": "otag:removal"}).json()["items"]}
        assert names == set(TAGGED["removal"])
        both = app.get("/api/cards", params={"tag": ["removal"], "q": "bolt"}).json()["items"]
        assert [c["name"] for c in both] == ["Lightning Bolt"]
        assert app.get("/api/cards", params={"q": "-otag:ramp sol ring"}).json()["total"] == 0

        deck = app.post("/api/decks", json={"name": "Tags", "format": "freeform", "platform": "paper"}).json()
        for name, qty in (("Sol Ring", 1), ("Lightning Bolt", 4), ("Path to Exile", 2), ("Serra Angel", 3)):
            app.post(f"/api/decks/{deck['id']}/cards", json={"card_id": CARDS[name]["id"], "quantity": qty})
        stats = app.get(f"/api/decks/{deck['id']}/stats").json()
        assert stats["functions"] == {"ramp": 1, "removal": 6}  # in the tags' order
