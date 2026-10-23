from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect
from mtgdm.mtgjson.client import MtgjsonClient
from mtgdm.mtgjson.precons import precon_decklist, search_precons, sync_precons

FIXTURES = Path(__file__).parent / "fixtures" / "mtgjson"
QUINTORIUS = "Quintorius, History Chaser"


class FakeMtgjson:
    """Serves the fixture files like https://mtgjson.com/api/v5/ (404 for the rest)."""

    def __init__(self, offline: bool = False):
        self.requests: list[str] = []
        self.offline = offline

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v5/")
        self.requests.append(path)
        if self.offline:
            raise httpx.ConnectError("offline", request=request)
        file = FIXTURES / path
        if not file.is_file():
            return httpx.Response(404)
        return httpx.Response(200, content=file.read_bytes(), headers={"Content-Type": "application/json"})


def mtgjson_client(fake: FakeMtgjson) -> MtgjsonClient:
    return MtgjsonClient(httpx.Client(transport=httpx.MockTransport(fake)), min_interval=0, sleep=lambda s: None)


@pytest.fixture
def db(card_settings):
    conn = connect(card_settings.db_path)
    yield conn
    conn.close()


def test_sync_stores_the_list_and_fetches_commander_decks(db):
    fake = FakeMtgjson()
    progress = []
    fetched = sync_precons(db, mtgjson_client(fake), lambda stage, done, total: progress.append((stage, done, total)))
    # The Commander deck with a file is loaded; the one without (404) is skipped, not fatal; the theme
    # deck stays a list entry until imported.
    assert fetched == 1
    loaded = {r[0]: r[1] is not None for r in db.execute("SELECT file_name, loaded_at FROM precons")}
    assert loaded == {"LoreholdSpirit_SOC": True, "LoreholdLegacies_C21": False, "AngelicHost_DOM": False}
    assert progress[-1] == ("precons", 2, 2) and all(p[0] == "precons" for p in progress)

    # The next sync only asks for what is still missing.
    fake.requests.clear()
    sync_precons(db, mtgjson_client(fake))
    assert fake.requests == ["DeckList.json", "decks/LoreholdLegacies_C21.json"]


def test_search_by_deck_commander_or_set(db):
    sync_precons(db, mtgjson_client(FakeMtgjson()))
    assert [p.file_name for p in search_precons(db, "quintorius")] == ["LoreholdSpirit_SOC"]
    assert [p.file_name for p in search_precons(db, "lorehold")] == ["LoreholdSpirit_SOC", "LoreholdLegacies_C21"]
    assert [p.file_name for p in search_precons(db, "dom")] == ["AngelicHost_DOM"]
    soc = search_precons(db, "spirit")[0]
    assert (soc.commanders, soc.code, soc.set_name is not None, soc.loaded) == ([QUINTORIUS], "soc", True, True)
    commander_only = search_precons(db, "", ["Commander Deck"])
    assert {p.type for p in commander_only} == {"Commander Deck"}


def test_decklist_text_uses_exact_printings(db):
    client = mtgjson_client(FakeMtgjson())
    sync_precons(db, client)
    deck = precon_decklist(db, client, "LoreholdSpirit_SOC")
    lines = deck.text.splitlines()
    assert lines[:4] == ["# name: Lorehold Spirit (SOC precon)", "# format: commander", "# platform: paper",
                         "# source: MTGJSON LoreholdSpirit_SOC"]
    assert lines[5] == "Commander" and lines[6].startswith(f"1 {QUINTORIUS} (SOC) ")
    assert "Deck" in lines
    # A printing the local card data doesn't have: MTGJSON's set and number.
    assert "1 Lightning Bolt (XYZ) 1" in lines


def test_import_through_the_api(card_settings):
    fake = FakeMtgjson()
    with TestClient(create_app(card_settings, mtgjson=mtgjson_client(fake))) as client:
        conn = connect(card_settings.db_path)
        sync_precons(conn, mtgjson_client(fake))
        conn.close()
        found = client.get("/api/precons", params={"q": "angelic"}).json()
        assert [p["file_name"] for p in found] == ["AngelicHost_DOM"] and not found[0]["loaded"]

        # Not loaded yet: fetched on demand.
        deck = client.get("/api/precons/AngelicHost_DOM/decklist").json()
        assert deck["precon"]["loaded"] and "Sideboard" in deck["text"] and "# format: freeform" in deck["text"]
        report = client.post("/api/import/parse", json={"text": deck["text"]}).json()
        serra = next(line for line in report["lines"] if line["name"] == "Serra Angel")
        assert serra["quantity"] == 4 and serra["card"] is not None
        assert report["meta"]["name"] == "Angelic Host (DOM precon)"

        assert client.get("/api/precons/Nope/decklist").status_code == 404


def test_offline_download_is_reported(card_settings):
    online = FakeMtgjson()
    conn = connect(card_settings.db_path)
    sync_precons(conn, mtgjson_client(online))
    conn.close()
    with TestClient(create_app(card_settings, mtgjson=mtgjson_client(FakeMtgjson(offline=True)))) as client:
        resp = client.get("/api/precons/AngelicHost_DOM/decklist")
        assert resp.status_code == 502
        # Loaded decks don't need the network.
        assert client.get("/api/precons/LoreholdSpirit_SOC/decklist").status_code == 200
