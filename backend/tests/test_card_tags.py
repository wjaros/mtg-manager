import gzip
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect
from mtgdm.scryfall import ScryfallClient
from mtgdm.scryfall.tags import FUNCTION_TAGS, SYNCED_KEY, sync_tags
from tests.helpers import fixture_cards

CARDS = {c["name"]: c for c in fixture_cards()}
TAGGED = {
    "ramp": ["Sol Ring", "Arcane Signet"],
    "removal": ["Swords to Plowshares", "Path to Exile", "Lightning Bolt"],
    "draw": ["Bygone Bishop"],
}
NOT_LOCAL = "00000000-0000-0000-0000-000000000000"  # a card the local data doesn't have


def tag(tag_id, slug, names=(), parents=(), children=(), oracle_ids=()):
    taggings = [{"oracle_id": CARDS[n]["oracle_id"], "weight": "median"} for n in names]
    taggings += [{"oracle_id": o, "weight": "median"} for o in oracle_ids]
    return {"object": "tag", "id": tag_id, "slug": slug, "label": slug, "type": "oracle", "description": None,
            "parent_ids": list(parents), "child_ids": list(children), "aliases": [], "taggings": taggings}


def oracle_tags(with_draw=True):
    """A small Tagger hierarchy: functions with direct cards, children and grandchildren, linked
    from either side, plus tags the app doesn't count."""
    ramp, removal, draw = FUNCTION_TAGS["ramp"], FUNCTION_TAGS["removal"], FUNCTION_TAGS["draw"]
    tags = [
        tag(ramp, "ramp", ["Sol Ring"], children=["mana-rock"]),
        tag("mana-rock", "mana-rock", ["Arcane Signet"], parents=[ramp]),
        tag(removal, "removal", children=["spot-removal"]),  # no cards of its own
        tag("spot-removal", "spot-removal", ["Swords to Plowshares", "Path to Exile"]),  # linked from the parent only
        tag("burn-creature", "burn-creature", ["Lightning Bolt"], parents=["spot-removal", "gone"]),
        tag("cycle-test", "cycle-test", ["Serra Angel"], oracle_ids=[NOT_LOCAL]),
    ]
    if with_draw:
        tags += [tag(draw, "draw", children=["cantrip"]), tag("cantrip", "cantrip", ["Bygone Bishop"], parents=[draw])]
    return gzip.compress("".join(json.dumps(t) + "\n" for t in tags).encode())


class FakeScryfall:
    """bulk-data on api.scryfall.com, the oracle_tags file on data.scryfall.io."""

    def __init__(self):
        self.payload = oracle_tags()
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if request.url.path == "/bulk-data":
            return httpx.Response(200, json={"object": "list", "has_more": False, "data": [{
                "object": "bulk_data", "type": "oracle_tags", "updated_at": "2026-10-24T21:00:44.481+00:00",
                "jsonl_download_uri": "https://data.scryfall.io/oracle-tags/x.jsonl.gz",
                "compressed_size": len(self.payload),
            }]})
        if request.url.host == "data.scryfall.io":
            return httpx.Response(200, stream=httpx.ByteStream(self.payload))
        return httpx.Response(404)


@pytest.fixture
def scryfall():
    fake = FakeScryfall()
    return fake, ScryfallClient(httpx.Client(transport=httpx.MockTransport(fake)), min_interval=0)


def stored_functions(conn):
    return {(tag, name) for tag, name in conn.execute(
        "SELECT t.tag, MIN(c.name) FROM card_tags t JOIN cards c ON c.oracle_id = t.oracle_id GROUP BY t.tag, t.oracle_id")}


def test_sync_tags_and_weekly_refresh(card_settings, scryfall):
    fake, client = scryfall
    conn = connect(card_settings.db_path)
    progress = []
    assert sync_tags(conn, client, card_settings.bulk_dir, lambda *p: progress.append(p)) == 6
    # A function's cards: its own and its descendants' (two levels down, linked from either side).
    assert stored_functions(conn) == {(tag, name) for tag, names in TAGGED.items() for name in names}
    assert progress[-1] == ("tags", len(fake.payload), len(fake.payload))
    assert not any("/cards/search" in url for url in fake.requests)

    # Every tag is kept with its hierarchy; taggings only of local cards, links only between known tags.
    assert conn.execute("SELECT COUNT(*) FROM oracle_tags").fetchone()[0] == 8
    assert [r[0] for r in conn.execute("SELECT tag_id FROM oracle_taggings WHERE oracle_id = ?",
                                       (CARDS["Serra Angel"]["oracle_id"],))] == ["cycle-test"]
    assert not conn.execute("SELECT 1 FROM oracle_taggings WHERE oracle_id = ?", (NOT_LOCAL,)).fetchone()
    assert [r[0] for r in conn.execute("SELECT parent_id FROM oracle_tag_parents WHERE tag_id = 'burn-creature'")] == [
        "spot-removal"]

    # Fresh for a week: no requests; forced or a week later: fetched again.
    count = len(fake.requests)
    assert sync_tags(conn, client, card_settings.bulk_dir) is None and len(fake.requests) == count
    assert sync_tags(conn, client, card_settings.bulk_dir, now=datetime.now(UTC) + timedelta(days=8)) == 6
    conn.close()


def test_functions_from_an_older_version_dont_count_as_fresh(card_settings, scryfall):
    _, client = scryfall
    conn = connect(card_settings.db_path)
    with conn:  # what 0.1.10 left: functions synced through search today, no oracle tags
        conn.execute("INSERT INTO card_tags(oracle_id, tag) VALUES (?, 'ramp')", (CARDS["Sol Ring"]["oracle_id"],))
        conn.execute("INSERT INTO meta(key, value) VALUES (?, ?)",
                     (SYNCED_KEY, datetime.now(UTC).isoformat(timespec="seconds")))
    assert sync_tags(conn, client, card_settings.bulk_dir) == 6
    conn.close()


def test_function_tag_gone_from_tagger_keeps_its_cards(card_settings, scryfall, caplog):
    fake, client = scryfall
    conn = connect(card_settings.db_path)
    sync_tags(conn, client, card_settings.bulk_dir)
    fake.payload = oracle_tags(with_draw=False)
    with caplog.at_level(logging.WARNING):
        assert sync_tags(conn, client, card_settings.bulk_dir, force=True) == 5
    assert ("draw", "Bygone Bishop") in stored_functions(conn)
    assert FUNCTION_TAGS["draw"] in caplog.text
    conn.close()


def test_tags_in_search_and_deck_stats(card_settings, scryfall):
    _, client = scryfall
    conn = connect(card_settings.db_path)
    sync_tags(conn, client, card_settings.bulk_dir)
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
