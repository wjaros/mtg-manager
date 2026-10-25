import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from tests.helpers import fixture_cards

CARDS = {c["name"]: c for c in fixture_cards()}


@pytest.fixture
def app(card_settings):
    with TestClient(create_app(card_settings)) as client:
        yield client


def deck(app, name, fmt, platform, cards, commander=None):
    created = app.post("/api/decks", json={"name": name, "format": fmt, "platform": platform}).json()
    if commander:
        app.post(f"/api/decks/{created['id']}/cards", json={"card_id": CARDS[commander]["id"], "board": "commander"})
    for card, quantity in cards:
        app.post(f"/api/decks/{created['id']}/cards", json={"card_id": CARDS[card]["id"], "quantity": quantity})
    return created["id"]


def rows(app, a, b):
    resp = app.get(f"/api/decks/{a}/compare/{b}")
    assert resp.status_code == 200, resp.text
    return resp.json(), {r["name"]: r for r in resp.json()["rows"]}


def test_paper_deck_against_its_arena_version(app):
    paper = deck(app, "Giada", "commander", "paper",
                 [("Swords to Plowshares", 1), ("Sol Ring", 1), ("Plains", 10), ("Serra Angel", 1)],
                 commander="Giada, Font of Hope")
    arena = deck(app, "Giada Arena", "brawl", "arena",
                 [("Path to Exile", 1), ("Plains", 12), ("Serra Angel", 1), ("Lightning Strike", 1),
                  ("Arcane Signet", 1)],
                 commander="Giada, Font of Hope")
    result, by_name = rows(app, paper, arena)
    assert result["a"]["color_identity"] == ["W"] and result["b"]["platform"] == "arena"
    assert {n: (r["a"], r["b"]) for n, r in by_name.items()} == {
        "Giada, Font of Hope": (1, 1), "Swords to Plowshares": (1, 0), "Sol Ring": (1, 0), "Plains": (10, 12),
        "Serra Angel": (1, 1), "Path to Exile": (0, 1), "Lightning Strike": (0, 1), "Arcane Signet": (0, 1),
    }

    # Into the Arena Brawl deck: legal there and on Arena, in Arena's printing.
    swords = by_name["Swords to Plowshares"]["fit_b"]
    assert swords["legal"] and swords["on_platform"] and swords["addable"] == 1
    assert "arena" in app.get(f"/api/cards/{swords['card_id']}").json()["games"]
    sol_ring = by_name["Sol Ring"]["fit_b"]
    assert not sol_ring["legal"] and not sol_ring["on_platform"] and sol_ring["addable"] == 0

    # Into the paper Commander deck: within Giada's colors (white) only; basic lands have no limit.
    assert by_name["Path to Exile"]["fit_a"]["addable"] == 1
    assert by_name["Arcane Signet"]["fit_a"]["addable"] == 1  # colorless fits
    strike = by_name["Lightning Strike"]["fit_a"]
    assert strike["legal"] and not strike["in_identity"] and strike["addable"] == 0
    assert by_name["Plains"]["fit_a"]["addable"] == 2 and by_name["Plains"]["fit_b"]["addable"] == 0
    assert by_name["Serra Angel"]["fit_a"]["addable"] == 0  # both have it

    # The printing offered for a paper deck can be added; the comparison then agrees.
    path = by_name["Path to Exile"]["fit_a"]["card_id"]
    app.post(f"/api/decks/{paper}/cards", json={"card_id": path})
    assert rows(app, paper, arena)[1]["Path to Exile"]["a"] == 1


def test_copy_limits_and_no_commander(app):
    singleton = deck(app, "Giada", "commander", "paper", [], commander="Giada, Font of Hope")
    playset = deck(app, "Removal", "freeform", "paper", [("Path to Exile", 4), ("Sol Ring", 2)])
    result, by_name = rows(app, singleton, playset)
    assert result["b"]["color_identity"] is None
    assert by_name["Path to Exile"]["fit_a"]["addable"] == 1  # singleton format: one copy
    assert by_name["Sol Ring"]["fit_a"]["addable"] == 1
    assert by_name["Giada, Font of Hope"]["fit_b"]["addable"] == 1  # freeform: no limit, no identity


def test_unknown_or_empty_decks(app):
    empty = deck(app, "Empty", "freeform", "paper", [])
    other = deck(app, "Other", "freeform", "paper", [])
    assert rows(app, empty, other)[0]["rows"] == []
    assert app.get(f"/api/decks/{empty}/compare/999").status_code == 404
