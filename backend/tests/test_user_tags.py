import pytest

from tests.helpers import fixture_cards
from tests.test_backup import make_client

PRINTINGS = {(c["name"], c["set"], c["collector_number"]): c["id"] for c in fixture_cards()}
SOL_RING = PRINTINGS[("Sol Ring", "sld", "2132")]
SOL_RING_OTHER = PRINTINGS[("Sol Ring", "frc", "21")]
BOLT = next(c["id"] for c in fixture_cards() if c["name"] == "Lightning Bolt")


@pytest.fixture
def app(tmp_path, card_db_template):
    with make_client(tmp_path, card_db_template, "a") as client:
        yield client


def names(app, q):
    return {c["name"] for c in app.get("/api/cards", params={"q": q}).json()["items"]}


def test_tags_per_card_in_any_case(app):
    resp = app.put(f"/api/cards/{SOL_RING}/user-tags", json={"tags": ["  Wincon ", "wincon", "pet   card", ""]})
    assert resp.json() == ["pet card", "Wincon"]  # trimmed, one per spelling in any case, sorted
    # Every printing of the card has them.
    assert app.get(f"/api/cards/{SOL_RING_OTHER}").json()["user_tags"] == ["pet card", "Wincon"]
    app.put(f"/api/cards/{BOLT}/user-tags", json={"tags": ["WINCON"]})

    assert names(app, "tag:wincon") == {"Sol Ring", "Lightning Bolt"}
    assert names(app, 'tag:"pet card"') == {"Sol Ring"}
    assert "Sol Ring" not in names(app, "-tag:wincon sol")
    assert app.get("/api/user-tags").json() == [{"tag": "pet card", "cards": 1}, {"tag": "Wincon", "cards": 2}]

    assert app.put(f"/api/cards/{SOL_RING}/user-tags", json={"tags": []}).json() == []
    assert names(app, "tag:wincon") == {"Lightning Bolt"}
    assert app.put("/api/cards/nope/user-tags", json={"tags": ["x"]}).status_code == 404


def test_tags_in_the_backup(app, tmp_path, card_db_template):
    app.put(f"/api/cards/{SOL_RING}/user-tags", json={"tags": ["wincon", "pet card"]})
    backup = app.get("/api/backup/export").json()
    assert {"name": "Sol Ring", "tags": ["pet card", "wincon"]}.items() <= backup["user_tags"][0].items()

    # Found by name when the oracle id is unknown; a card nowhere to be found is reported.
    backup["user_tags"][0]["oracle_id"] = "00000000-0000-0000-0000-000000000000"
    backup["user_tags"].append({"oracle_id": None, "name": "No Such Card", "tags": ["x"]})
    with make_client(tmp_path, card_db_template, "b") as other:
        result = other.post("/api/backup/import", json=backup).json()
        assert result["missing_cards"] == ["No Such Card"]
        assert other.get(f"/api/cards/{SOL_RING}").json()["user_tags"] == ["pet card", "wincon"]

    # Replace starts from no tags.
    app.put(f"/api/cards/{BOLT}/user-tags", json={"tags": ["burn"]})
    app.post("/api/backup/import", params={"replace": True}, json=app.get("/api/backup/export").json())
    assert app.get("/api/user-tags").json() == [
        {"tag": "burn", "cards": 1}, {"tag": "pet card", "cards": 1}, {"tag": "wincon", "cards": 1}]
