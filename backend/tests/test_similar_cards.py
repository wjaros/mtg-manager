import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.cards import similar as engine
from mtgdm.db import connect
from mtgdm.scryfall.tags import SYNCED_KEY
from tests.helpers import fixture_cards

CARDS = {c["name"]: c for c in fixture_cards()}
CYCLE = "1adda1a4-e23d-4212-a4da-58303a20e00c"  # Tagger's root of all card cycles
# Tagger tags: a rare one shared by the exile removal spells, a broad one on many spells, and a cycle
# (rarer than anything, but saying nothing about what the cards do).
TAGS = {
    "removal-exile": ["Swords to Plowshares", "Path to Exile", "Epic Downfall"],
    "single-target": ["Swords to Plowshares", "Path to Exile", "Epic Downfall", "Lightning Bolt", "Lightning Strike",
                      "Explosive Shot", "Mortify", "Heartless Act", "Feed the Swarm", "Duress", "Deny Entry"],
    "removal-burn": ["Lightning Bolt", "Lightning Strike", "Explosive Shot"],
    "removal": [],
    CYCLE: [],
    "cycle-test": ["Swords to Plowshares", "Reprieve"],
}
PARENTS = [("removal-exile", "removal"), ("removal-burn", "removal"), ("cycle-test", CYCLE)]


@pytest.fixture
def app(card_settings):
    conn = connect(card_settings.db_path)
    with conn:
        for tag, names in TAGS.items():
            conn.execute("INSERT INTO oracle_tags(id, slug, label) VALUES (?, ?, ?)", (tag, tag, tag))
            conn.executemany("INSERT INTO oracle_taggings(oracle_id, tag_id, weight) VALUES (?, ?, 'median')",
                             [(CARDS[n]["oracle_id"], tag) for n in names])
        conn.executemany("INSERT INTO oracle_tag_parents(tag_id, parent_id) VALUES (?, ?)", PARENTS)
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
    for name in ("Karametra's Blessing", "Reprieve"):  # white instants doing something else
        app.post("/api/collection", json={"card_id": CARDS[name]["id"]})
    result = similar(app, "Swords to Plowshares")
    # Only close owned matches: the weak ones a small collection has are left out.
    assert names(result, "owned") == ["Path to Exile"] and result["owned"][0]["card"]["owned"] == 2
    assert "Path to Exile" not in names(result)

    deck = app.post("/api/decks", json={"name": "W", "format": "commander", "platform": "paper"}).json()
    app.post(f"/api/decks/{deck['id']}/cards", json={"card_id": path["id"], "quantity": 1})
    in_deck = names(similar(app, "Swords to Plowshares", deck=deck["id"]))
    assert "Path to Exile" not in in_deck  # already in the deck (owned or not)
    assert similar(app, "Swords to Plowshares", deck=deck["id"])["owned"] == []
    assert in_deck  # other white removal is still suggested


def test_legal_only_or_all_marked(app):
    pioneer = app.post("/api/decks", json={"name": "P", "format": "pioneer", "platform": "paper"}).json()["id"]
    app.post(f"/api/decks/{pioneer}/cards", json={"card_id": CARDS["Karametra's Blessing"]["id"]})
    legal = similar(app, "Swords to Plowshares", colors="wb", deck=pioneer)
    assert "Epic Downfall" in names(legal) and "Path to Exile" not in names(legal)  # not legal in Pioneer
    assert all(item["legal"] for item in legal["others"])

    every = similar(app, "Swords to Plowshares", colors="wb", deck=pioneer, legal_only=False)
    marks = {item["card"]["name"]: item["legal"] for item in every["others"]}
    assert marks["Path to Exile"] is False and marks["Epic Downfall"] is True
    assert "Karametra's Blessing" not in marks  # the deck's own cards stay out either way

    # An Arena deck plays only Arena cards, freeform too (Wave of Reckoning isn't on Arena).
    arena = app.post("/api/decks", json={"name": "A", "format": "freeform", "platform": "arena"}).json()["id"]
    assert "Wave of Reckoning" not in names(similar(app, "Swords to Plowshares", colors="wb", deck=arena))
    every = similar(app, "Swords to Plowshares", colors="wb", deck=arena, legal_only=False)["others"]
    marks = {item["card"]["name"]: item["legal"] for item in every}
    assert marks["Wave of Reckoning"] is False and marks["Path to Exile"] is True

    assert {item["legal"] for item in similar(app, "Swords to Plowshares")["others"]} == {None}  # no deck


def test_unknown_card_or_deck(app):
    assert app.get("/api/cards/nope/similar").status_code == 404
    swords = CARDS["Swords to Plowshares"]["id"]
    assert app.get(f"/api/cards/{swords}/similar", params={"deck": 999}).status_code == 404
    assert app.get(f"/api/cards/{swords}/similar", params={"colors": "x"}).status_code == 422


def test_without_tags_text_alone(card_settings):
    with TestClient(create_app(card_settings)) as app:  # no tags synced yet
        assert names(similar(app, "Lightning Bolt"))[0] == "Lightning Strike"


def test_cycles_dont_count_and_tags_share_ancestors(app, card_settings):
    # Reprieve shares only a (very rare) cycle tag with Swords: no reason to suggest it.
    assert "Reprieve" not in names(similar(app, "Swords to Plowshares"))

    conn = connect(card_settings.db_path)
    data = engine._load_tag_data(conn)
    conn.close()
    assert {CYCLE, "cycle-test"} <= data.excluded and data.lift({"cycle-test"}) == set()
    assert data.lift({"removal-exile"}) == {"removal-exile", "removal"}
    assert data.df["removal"] == 6  # the cards of both children


def test_phrases():
    # Keyword lines are terms of their own; mana symbol pairs from costs are not phrases.
    assert engine._phrases("Flying\nVigilance (Attacking doesn't cause this creature to tap.)", "Serra Angel") == [
        "flying", "vigilance"]
    assert engine._phrases("Flashback {6}{R}{W}", "Molten Note") == ["flashback 6"]
    assert engine._phrases("Molten Note deals damage to target creature.", "Molten Note")[:2] == [
        "deals damage", "damage to"]
