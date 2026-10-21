import gzip
import json

import httpx
import pytest

from mtgdm.scryfall import ScryfallClient
from mtgdm.scryfall.bulk import (
    META_UPDATED_AT,
    get_meta,
    import_cards,
    iter_bulk_file,
    sync_cards,
)
from tests.helpers import FIXTURE, fixture_cards

UPDATED_AT = "2026-10-20T09:06:24.827+00:00"


def fake_scryfall(payload: bytes, updated_at: str = UPDATED_AT, calls: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if request.url.path == "/bulk-data":
            return httpx.Response(200, json={"object": "list", "has_more": False, "data": [{
                "object": "bulk_data", "type": "default_cards", "updated_at": updated_at,
                "jsonl_download_uri": "https://data.scryfall.io/default-cards/x.jsonl.gz",
                "compressed_size": len(payload),
            }]})
        if request.url.host == "data.scryfall.io":
            # A stream, like a real network response (content= bodies can't be read with iter_raw).
            return httpx.Response(200, stream=httpx.ByteStream(payload))
        return httpx.Response(404)

    return ScryfallClient(httpx.Client(transport=httpx.MockTransport(handler)), min_interval=0)


def card_by(db, name, set_code=None):
    sql = "SELECT * FROM cards WHERE name = ?" + (" AND set_code = ?" if set_code else "")
    return db.execute(sql, (name, set_code) if set_code else (name,)).fetchone()


def test_sync_downloads_gzipped_jsonl_and_imports(db, tmp_path):
    payload = FIXTURE.read_bytes()
    progress = []
    result = sync_cards(db, fake_scryfall(payload), tmp_path, on_progress=lambda *a: progress.append(a))

    assert not result.skipped
    assert result.cards == len(fixture_cards())
    assert db.execute("SELECT COUNT(*) FROM cards").fetchone()[0] == result.cards
    assert db.execute("SELECT COUNT(*) FROM card_details").fetchone()[0] == result.cards
    assert get_meta(db, META_UPDATED_AT) == UPDATED_AT
    assert ("download", len(payload), len(payload)) in progress
    assert (tmp_path / "default_cards.data").read_bytes() == payload
    assert not list(tmp_path.glob("*.part"))


def test_sync_skips_when_bulk_unchanged(db, tmp_path):
    payload = FIXTURE.read_bytes()
    sync_cards(db, fake_scryfall(payload), tmp_path)
    calls = []
    result = sync_cards(db, fake_scryfall(payload, calls=calls), tmp_path)
    assert result.skipped
    assert not any("data.scryfall.io" in c for c in calls)


def test_reimport_removes_vanished_unreferenced_cards(db):
    cards = fixture_cards()
    import_cards(db, cards, "v1")
    serra = [c for c in cards if c["name"] == "Serra Angel"]
    kept_id = serra[0]["id"]
    db.execute("INSERT INTO decks(id, name) VALUES (1, 'test')")
    db.execute("INSERT INTO deck_cards(deck_id, card_id) VALUES (1, ?)", (kept_id,))

    result = import_cards(db, [c for c in cards if c["name"] != "Serra Angel"], "v2")

    assert result.removed == len(serra) - 1
    remaining = [r[0] for r in db.execute("SELECT id FROM cards WHERE name = 'Serra Angel'")]
    assert remaining == [kept_id]  # still used by a deck
    assert db.execute("SELECT COUNT(*) FROM card_details WHERE id NOT IN (SELECT id FROM cards)").fetchone()[0] == 0


def test_multi_face_cards_get_combined_fields(db):
    import_cards(db, fixture_cards(), UPDATED_AT)

    delver = card_by(db, "Delver of Secrets // Insectile Aberration")
    assert delver["layout"] == "transform"
    assert delver["mana_cost"] == "{U} // "
    assert "\n//\n" in delver["oracle_text"]
    assert json.loads(delver["colors"]) == ["U"]
    assert delver["image_faces"] == 2
    assert delver["oracle_id"]

    fire_ice = card_by(db, "Fire // Ice")
    assert fire_ice["mana_cost"] == "{1}{R} // {1}{U}"
    assert sorted(json.loads(fire_ice["colors"])) == ["R", "U"]
    assert fire_ice["image_faces"] == 1

    twice = db.execute(
        "SELECT layout, mana_cost FROM cards WHERE set_code = 'who' AND collector_number = '61'"
    ).fetchone()
    # mtg.wtf lists it as 61a; Scryfall uses plain 61.
    assert twice["layout"] == "adventure"
    assert twice["mana_cost"] == "{4}{U}{U} // {2}{U}"


def test_raw_keeps_only_extra_fields(db):
    import_cards(db, fixture_cards(), UPDATED_AT)
    row = db.execute(
        "SELECT d.raw, c.artist FROM card_details d JOIN cards c USING (id) WHERE c.name = 'Serra Angel' LIMIT 1"
    ).fetchone()
    raw = json.loads(row["raw"])
    assert raw["power"] == "4" and raw["toughness"] == "4"
    assert "purchase_uris" not in raw and "image_uris" not in raw and "name" not in raw
    assert row["artist"]


def test_oracle_cards_defaults(db):
    import_cards(db, fixture_cards(), UPDATED_AT)
    rows = {
        r["name"]: r for r in db.execute(
            """SELECT o.name, d.set_code, d.collector_number, d.promo, d.border_color, d.games,
                      a.games AS arena_games
               FROM oracle_cards o
               JOIN cards d ON d.id = o.default_card_id
               LEFT JOIN cards a ON a.id = o.arena_card_id"""
        )
    }
    giada = rows["Giada, Font of Hope"]
    assert (giada["set_code"], giada["collector_number"]) == ("fdn", "141")
    assert "arena" in json.loads(giada["arena_games"])
    # Not on Arena at all.
    assert rows["Sol Ring"]["arena_games"] is None
    assert rows["The Fourth Doctor"]["arena_games"] is None
    # Cards with full printing history in the fixture (decklist cards keep only a few printings).
    for name in ("Serra Angel", "Sol Ring", "Command Tower", "Lightning Bolt", "Fire // Ice", "Plains"):
        row = rows[name]
        assert row["promo"] == 0, name
        assert "paper" in json.loads(row["games"]), name
        assert row["set_code"] != "plst", name


@pytest.mark.parametrize("gzipped", [True, False])
@pytest.mark.parametrize("as_array", [True, False])
def test_iter_bulk_file_formats(tmp_path, gzipped, as_array):
    cards = fixture_cards()[:3]
    if as_array:
        text = "[\n" + ",\n".join(json.dumps(c) for c in cards) + "\n]"
    else:
        text = "\n".join(json.dumps(c) for c in cards) + "\n"
    data = text.encode()
    path = tmp_path / "bulk"
    path.write_bytes(gzip.compress(data) if gzipped else data)
    assert [c["id"] for c in iter_bulk_file(path)] == [c["id"] for c in cards]
