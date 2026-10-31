from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect
from mtgdm.mtgjson import products
from mtgdm.mtgjson.client import MtgjsonClient
from mtgdm.mtgjson.precons import precon_decklist, search_precons, sync_precons
from mtgdm.mtgjson.products import (
    ProductDeckPlan,
    ProductImportRequest,
    get_product,
    get_product_deck,
    import_product,
    search_products,
)

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
    assert {k: v for k, v in loaded.items() if v} == {"LoreholdSpirit_SOC": True}
    assert {"LoreholdLegacies_C21", "AngelicHost_DOM", "BeginnerBoxAllies_TLA"} <= loaded.keys()
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
    assert "AngelicHost_DOM" in [p.file_name for p in search_precons(db, "dominaria")]  # the set's name
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


def test_browse_and_missing_suggestions(card_settings):
    fake = FakeMtgjson()
    with TestClient(create_app(card_settings, mtgjson=mtgjson_client(fake))) as client:
        conn = connect(card_settings.db_path)
        sync_precons(conn, mtgjson_client(fake))
        cards = conn.execute(
            "SELECT pc.card_id, pc.name FROM precon_cards pc JOIN cards c ON c.id = pc.card_id"
            " WHERE pc.file_name = 'LoreholdSpirit_SOC' AND pc.board = 'main' ORDER BY pc.rowid"
        ).fetchall()
        conn.close()

        # Own one card of the precon.
        client.post("/api/collection", json={"card_id": cards[0]["card_id"]})
        overview = client.get("/api/precons/commander").json()
        assert [o["precon"]["file_name"] for o in overview] == ["LoreholdSpirit_SOC"]  # loaded Commander decks only
        soc = overview[0]
        assert soc["colors"] == ["W", "R"] and soc["owned"] == 1 and soc["cards"] == 10  # commander + 9
        assert soc["price_eur"] >= 0

        # A deck missing four of the precon's cards: the precon is suggested.
        deck = client.post("/api/decks", json={"name": "Wants", "format": "freeform", "platform": "paper"}).json()
        for c in cards[1:5]:
            client.post(f"/api/decks/{deck['id']}/cards", json={"card_id": c["card_id"]})
        suggestions = client.get(f"/api/decks/{deck['id']}/missing/precons").json()
        assert [(s["precon"]["file_name"], s["covers"]) for s in suggestions] == [("LoreholdSpirit_SOC", 4)]
        assert sorted(s for s in suggestions[0]["names"]) == sorted(c["name"] for c in cards[1:5])

        # Two missing cards are not worth a precon.
        small = client.post("/api/decks", json={"name": "Two", "format": "freeform", "platform": "paper"}).json()
        for c in cards[1:3]:
            client.post(f"/api/decks/{small['id']}/cards", json={"card_id": c["card_id"]})
        assert client.get(f"/api/decks/{small['id']}/missing/precons").json() == []
        assert client.get("/api/decks/999/missing/precons").status_code == 404


def test_products_group_decks_of_one_box(db):
    sync_precons(db, mtgjson_client(FakeMtgjson()))
    products = {p.key: p for p in search_products(db)}
    # "Beginner Box - X" decks of one set make a product; Starter Kit decks of a set are one box; a lone
    # Box Set deck and Commander decks are no product.
    assert products.keys() == {"tla-beginner-box", "blb-starter-kit"}
    box = products["tla-beginner-box"]
    assert (box.name, box.code, box.type, box.decks, box.set_name is not None) == ("Beginner Box", "tla", "Box Set", 3, True)
    assert [p.key for p in search_products(db, "zuko")] == ["tla-beginner-box"]
    assert [p.key for p in search_products(db, "blb")] == ["blb-starter-kit"]
    # Words match from their start ("tla" isn't in "Atlantis"); a box called by another kind's name is
    # still found, ranked after the products matching every word.
    assert [p.key for p in search_products(db, "tla")] == ["tla-beginner-box"]
    assert [p.key for p in search_products(db, "airbender starter kit")] == ["tla-beginner-box"]
    assert [p.key for p in search_products(db, "starter kit")] == ["blb-starter-kit"]
    assert [p.key for p in search_products(db, "begginer box")] == ["tla-beginner-box"]  # a typo
    assert search_products(db, "lorehold") == []


def test_product_decks_are_fetched_and_matched(db):
    fake = FakeMtgjson()
    client = mtgjson_client(fake)
    sync_precons(db, client)
    fake.requests.clear()
    detail = get_product(db, client, "tla-beginner-box")
    assert sorted(fake.requests) == [f"decks/BeginnerBox{n}_TLA.json" for n in ("AangTutorial", "Allies", "ZukoTutorial")]
    decks = {d.name: d for d in detail.decks}
    assert list(decks) == ["Aang Tutorial", "Allies", "Zuko Tutorial"]
    assert {d.cards for d in decks.values()} == {20}
    assert (decks["Aang Tutorial"].colors, decks["Zuko Tutorial"].colors) == (["W"], ["R"])
    assert all(line.status == "matched" for d in detail.decks for line in d.lines)
    # Stored now: no download the second time.
    fake.requests.clear()
    get_product(db, client, "tla-beginner-box")
    assert fake.requests == []


def test_import_combined_halves_into_owned_decks(card_settings):
    fake = FakeMtgjson()
    with TestClient(create_app(card_settings, mtgjson=mtgjson_client(fake))) as client:
        conn = connect(card_settings.db_path)
        sync_precons(conn, mtgjson_client(fake))
        assert client.get("/api/precons/products", params={"q": "beginner"}).json()[0]["key"] == "tla-beginner-box"
        decks = {d["name"]: d["file_name"] for d in client.get("/api/precons/products/tla-beginner-box").json()["decks"]}
        url = "/api/precons/products/tla-beginner-box/import"

        plan = {"name": "Aang vs Zuko", "file_names": [decks["Aang Tutorial"], decks["Zuko Tutorial"]]}
        reused = client.post(url, json={"decks": [plan, {"name": "Again", "file_names": [decks["Zuko Tutorial"]]}]})
        assert reused.status_code == 400 and "Zuko Tutorial" in reused.json()["detail"]
        assert client.post(url, json={"decks": [{"name": "X", "file_names": ["Nope"]}]}).status_code == 400
        assert client.post("/api/precons/products/nope/import", json={"decks": [plan]}).status_code == 404
        assert conn.execute("SELECT COUNT(*) FROM decks").fetchone()[0] == 0  # nothing created by those

        result = client.post(url, json={"decks": [plan], "own": True, "add_unused": True}).json()
        assert (result["added"], result["skipped"]) == (60, 0)
        deck = client.get(f"/api/decks/{result['deck_ids'][0]}").json()
        assert (deck["name"], deck["format"], deck["counts"]["main"]) == ("Aang vs Zuko", "freeform", 40)
        assert "Aang Tutorial + Zuko Tutorial" in deck["description"]
        in_box = conn.execute("SELECT SUM(quantity) FROM collection_items WHERE location_id = ?",
                              (deck["location_id"],)).fetchone()[0]
        unused = conn.execute("SELECT SUM(quantity) FROM collection_items WHERE location_id IS NULL").fetchone()[0]
        assert (in_box, unused) == (40, 20)
        conn.close()


def test_big_products_fetch_decks_one_by_one(db, monkeypatch):
    monkeypatch.setattr(products, "EAGER_DECKS", 2)  # the 3-deck box counts as big (Jumpstart has 121 packs)
    fake = FakeMtgjson()
    client = mtgjson_client(fake)
    sync_precons(db, client)
    fake.requests.clear()
    detail = get_product(db, client, "tla-beginner-box")
    assert fake.requests == [] and not any(d.loaded or d.lines for d in detail.decks)

    aang = get_product_deck(db, client, "tla-beginner-box", "BeginnerBoxAangTutorial_TLA")
    assert (aang.loaded, aang.cards, fake.requests) == (True, 20, ["decks/BeginnerBoxAangTutorial_TLA.json"])
    assert [d.loaded for d in get_product(db, client, "tla-beginner-box").decks] == [True, False, False]

    # The import fetches only the decks it uses.
    fake.requests.clear()
    plan = ProductDeckPlan(name="Zuko", file_names=["BeginnerBoxZukoTutorial_TLA"])
    result = import_product(db, client, "tla-beginner-box", ProductImportRequest(decks=[plan]))
    assert len(result.deck_ids) == 1 and fake.requests == ["decks/BeginnerBoxZukoTutorial_TLA.json"]
