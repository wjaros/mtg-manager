import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect
from mtgdm.scryfall.tags import SYNCED_KEY
from tests.helpers import fixture_cards

CARDS = {c["name"]: c for c in fixture_cards()}
# Tagger tags: a rare one shared by the exile removal spells, a broad one on many spells.
TAGS = {
    "removal-exile": ["Swords to Plowshares", "Path to Exile", "Epic Downfall"],
    "single-target": ["Swords to Plowshares", "Path to Exile", "Epic Downfall", "Lightning Bolt", "Lightning Strike",
                      "Explosive Shot", "Mortify", "Heartless Act", "Feed the Swarm", "Duress", "Deny Entry"],
}


@pytest.fixture
def app(card_settings):
    conn = connect(card_settings.db_path)
    with conn:
        for tag, names in TAGS.items():
            conn.execute("INSERT INTO oracle_tags(id, slug, label) VALUES (?, ?, ?)", (tag, tag, tag))
            conn.executemany("INSERT INTO oracle_taggings(oracle_id, tag_id, weight) VALUES (?, ?, 'median')",
                             [(CARDS[n]["oracle_id"], tag) for n in names])
        conn.execute("INSERT INTO meta(key, value) VALUES (?, '2026-10-25T00:00:00+00:00')", (SYNCED_KEY,))
    conn.close()
    with TestClient(create_app(card_settings)) as client:
        yield client


def similar(app, name, **params):
    resp = app.get(f"/api/cards/{CARDS[name]['id']}/similar", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def names(result, part="others"):
    return [item["card"]["name"] for item in result[part]]


def test_same_text_ranks_first(app):
    result = similar(app, "Lightning Bolt")
    assert result["colors"] == ["R"]
    assert names(result)[0] == "Lightning Strike"
    assert "Lightning Bolt" not in names(result)
    assert all(0 < item["score"] <= 1 for item in result["others"]) and result["owned"] == []


def test_shared_rare_tags_and_colors(app):
    # Default: the card's own color identity (colorless fits); instants and sorceries alike.
    found = names(similar(app, "Swords to Plowshares"))
    assert found[0] == "Path to Exile"
    assert "Epic Downfall" not in found and "Lightning Bolt" not in found
    assert all("Creature" not in CARDS[n]["type_line"].split("//")[0] for n in found)

    widened = similar(app, "Swords to Plowshares", colors="wb")
    assert widened["colors"] == ["W", "B"]
    assert names(widened)[:2] == ["Path to Exile", "Epic Downfall"]  # the rare exile tag beats the broad one

    colorless = similar(app, "Swords to Plowshares", colors="C")
    assert colorless["colors"] == [] and all(item["card"]["color_identity"] == [] for item in colorless["others"])


def test_owned_apart_and_deck_context(app):
    path = CARDS["Path to Exile"]
    assert app.post("/api/collection", json={"card_id": path["id"], "quantity": 2}).status_code == 201
    result = similar(app, "Swords to Plowshares")
    assert names(result, "owned") == ["Path to Exile"] and result["owned"][0]["card"]["owned"] == 2
    assert "Path to Exile" not in names(result)

    deck = app.post("/api/decks", json={"name": "W", "format": "commander", "platform": "paper"}).json()
    app.post(f"/api/decks/{deck['id']}/cards", json={"card_id": path["id"], "quantity": 1})
    in_deck = names(similar(app, "Swords to Plowshares", deck=deck["id"]))
    assert "Path to Exile" not in in_deck  # already in the deck (owned or not)
    assert similar(app, "Swords to Plowshares", deck=deck["id"])["owned"] == []
    assert in_deck  # other white removal is still suggested


def test_unknown_card_or_deck(app):
    assert app.get("/api/cards/nope/similar").status_code == 404
    swords = CARDS["Swords to Plowshares"]["id"]
    assert app.get(f"/api/cards/{swords}/similar", params={"deck": 999}).status_code == 404
    assert app.get(f"/api/cards/{swords}/similar", params={"colors": "x"}).status_code == 422


def test_without_tags_text_alone(card_settings):
    with TestClient(create_app(card_settings)) as app:  # no tags synced yet
        assert names(similar(app, "Lightning Bolt"))[0] == "Lightning Strike"
