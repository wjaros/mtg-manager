import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from tests.helpers import fixture_cards

PRINTINGS = {(c["name"], c["set"], c["collector_number"]): c["id"] for c in fixture_cards()}


def printing(name, set_code, number):
    return PRINTINGS[(name, set_code, number)]


@pytest.fixture
def app(card_settings):
    with TestClient(create_app(card_settings)) as client:
        yield client


def shown(app, name, **params):
    """The printing the cards view shows for one card."""
    items = app.get("/api/cards", params={"q": f'!"{name}"', **params}).json()["items"]
    assert [c["name"] for c in items] == [name]
    return items[0]["id"]


def own(app, card_id, quantity=1, kind="real"):
    assert app.post("/api/collection", json={"card_id": card_id, "quantity": quantity, "kind": kind}).status_code == 201


def test_cards_view_shows_the_printing_owned_in_most_copies(app):
    default = shown(app, "Sol Ring")
    own(app, printing("Sol Ring", "slz", "356"), 5, kind="proxy")  # proxies don't count
    assert shown(app, "Sol Ring") == default

    own(app, printing("Sol Ring", "sld", "2132"))
    own(app, printing("Sol Ring", "sld", "2783"), 2)
    assert shown(app, "Sol Ring") == printing("Sol Ring", "sld", "2783")
    own(app, printing("Sol Ring", "fdc", "286"), 2)  # 2 copies each: the newest entry
    assert shown(app, "Sol Ring") == printing("Sol Ring", "fdc", "286")

    # The deckbuilder's pool searches the same way, but a printing filter decides the printing.
    assert shown(app, "Sol Ring", identity="WUBRG") == printing("Sol Ring", "fdc", "286")
    assert shown(app, "Sol Ring", set=["frc"]) == printing("Sol Ring", "frc", "21")


def test_arena_keeps_its_own_printing(app):
    arena = shown(app, "Arcane Signet", game="arena")
    own(app, printing("Arcane Signet", "who", "830"))
    assert shown(app, "Arcane Signet") == printing("Arcane Signet", "who", "830")
    assert shown(app, "Arcane Signet", game="arena") == arena
