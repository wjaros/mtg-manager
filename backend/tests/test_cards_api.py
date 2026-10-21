
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect, migrate
from mtgdm.scryfall.bulk import import_cards
from tests.helpers import fixture_cards


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    from mtgdm.config import Settings

    tmp = tmp_path_factory.mktemp("cards")
    settings = Settings(data_dir=tmp / "data", frontend_dist=tmp / "dist")
    settings.ensure_dirs()
    conn = connect(settings.db_path)
    migrate(conn)
    import_cards(conn, fixture_cards(), "v1")
    (settings.images_dir / "sets").mkdir()
    (settings.images_dir / "sets" / "who.svg").write_text("<svg/>", encoding="utf-8")
    with conn:
        conn.execute("UPDATE sets SET icon_path = 'sets/who.svg' WHERE code = 'who'")
    conn.close()
    with TestClient(create_app(settings)) as c:
        yield c


def get(client, **params):
    resp = client.get("/api/cards", params={"page_size": 200, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def names(resp) -> list[str]:
    assert resp.status_code == 200, resp.text
    return [c["name"] for c in resp.json()["items"]]


def test_search_by_name_prefix_one_row_per_card(client):
    resp = client.get("/api/cards", params={"q": "giad"})
    assert names(resp) == ["Errant and Giada", "Giada, Font of Hope", "Luxior, Giada's Gift"]
    giada = resp.json()["items"][1]
    assert (giada["set_code"], giada["collector_number"]) == ("fdn", "141")
    assert giada["image_faces"] == 1
    assert giada["color_identity"] == ["W"]


def test_search_all_printings(client):
    resp = client.get("/api/cards", params={"q": "Giada, Font of Hope", "unique": "prints"})
    items = resp.json()["items"]
    assert resp.json()["total"] == len(items) > 5
    assert {i["name"] for i in items} == {"Giada, Font of Hope"}


def test_multi_word_and_split_names(client):
    assert names(client.get("/api/cards", params={"q": "fire ice"})) == ["Fire // Ice"]
    assert names(client.get("/api/cards", params={"q": "insectile"})) == ["Delver of Secrets // Insectile Aberration"]


def test_rules_text_search(client):
    found = names(client.get("/api/cards", params={"text": "vigilance flying"}))
    assert "Serra Angel" in found and "Giada, Font of Hope" in found
    assert "Sol Ring" not in found


def test_color_modes(client):
    exact_w = [c["name"] for c in get(client, colors="W", color_mode="exact")]
    assert "Giada, Font of Hope" in exact_w and "Errant and Giada" not in exact_w

    include_w = [c["name"] for c in get(client, colors="W")]
    assert "Errant and Giada" in include_w and "Sol Ring" not in include_w

    identity_w = [c["name"] for c in get(client, colors="W", color_mode="identity")]
    # Colorless cards fit any identity; Errant and Giada (GW) does not fit mono-W.
    assert {"Giada, Font of Hope", "Sol Ring", "Command Tower", "Plains"} <= set(identity_w)
    assert "Errant and Giada" not in identity_w

    colorless = get(client, colors="C", type="Artifact")
    assert {"Haywire Mite", "Luxior, Giada's Gift", "Sol Ring"} <= {c["name"] for c in colorless}
    assert all(c["colors"] == [] for c in colorless)


def test_mana_value_type_and_order(client):
    found = get(client, mv=[1], type="Creature", order="mv")
    found_names = [c["name"] for c in found]
    assert {"Delver of Secrets // Insectile Aberration", "Haywire Mite"} <= set(found_names)
    assert found_names == sorted(found_names, key=str.lower)
    assert all(c["cmc"] == 1 and "Creature" in c["type_line"] for c in found)
    assert "Serra Angel" in [c["name"] for c in get(client, mv=[5])]
    seven_plus = get(client, mv=[7])
    assert seven_plus and all(c["cmc"] >= 7 for c in seven_plus)


def test_printing_level_filters(client):
    who = get(client, set="WHO", type="Legendary")
    assert {"The Fourth Doctor", "Sarah Jane Smith"} <= {c["name"] for c in who}
    assert all(c["set_code"] == "who" and "Legendary" in c["type_line"] for c in who)

    mythic = [c["name"] for c in get(client, rarity="mythic")]
    assert "Giada, Font of Hope" in mythic
    assert "Plains" not in mythic


def test_format_and_game_filters(client):
    brawl_arena = get(client, format="brawl", game="arena")
    found = {c["name"] for c in brawl_arena}
    assert "Giada, Font of Hope" in found
    assert "Sol Ring" not in found and "The Fourth Doctor" not in found
    assert all("arena" in c["games"] for c in brawl_arena)
    assert client.get("/api/cards", params={"format": "nope"}).status_code == 422


def test_extras_hidden_by_default(client):
    assert "Clue" not in names(client.get("/api/cards", params={"q": "clue"}))
    assert names(client.get("/api/cards", params={"q": "clue", "include_extras": True})) == ["Clue"]


def test_paging(client):
    first = client.get("/api/cards", params={"page_size": 5}).json()
    second = client.get("/api/cards", params={"page_size": 5, "page": 2}).json()
    assert first["total"] == second["total"] >= 15
    assert len(first["items"]) == len(second["items"]) == 5
    assert not {c["id"] for c in first["items"]} & {c["id"] for c in second["items"]}


def test_card_detail_and_printings(client):
    serra = client.get("/api/cards", params={"q": "serra angel"}).json()["items"][0]
    detail = client.get(f"/api/cards/{serra['id']}").json()
    assert detail["power"] == "4" and detail["toughness"] == "4"
    assert detail["artist"]
    assert detail["legalities"]["commander"] == "legal"
    assert detail["printings_count"] == len(client.get(f"/api/cards/{serra['id']}/printings").json())

    delver = client.get("/api/cards", params={"q": "delver"}).json()["items"][0]
    faces = client.get(f"/api/cards/{delver['id']}").json()["faces"]
    assert [f["name"] for f in faces] == ["Delver of Secrets", "Insectile Aberration"]

    assert client.get("/api/cards/nope").status_code == 404
    assert client.get("/api/cards/nope/printings").status_code == 404


def test_sets_and_icons(client):
    sets = {s["code"]: s for s in client.get("/api/sets").json()}
    assert sets["who"]["card_count"] > 0 and sets["who"]["has_icon"]
    resp = client.get("/api/sets/who/icon")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/svg+xml"
    assert client.get("/api/sets/fdn/icon").status_code == 404


def test_identity_param_combines_with_colors(client):
    # Deckbuilding pool for a mono-white commander, user looking at colorless cards only.
    found = [c["name"] for c in get(client, identity="W", colors="C", type="Artifact")]
    assert {"Luxior, Giada's Gift", "Sol Ring"} <= set(found)
    # Haywire Mite is colorless but has {G} in its text, so its identity is green.
    assert "Haywire Mite" not in found
    found = names(client.get("/api/cards", params={"identity": "W", "q": "giada"}))
    assert found == ["Giada, Font of Hope", "Luxior, Giada's Gift"]
    # Colorless commander: only colorless identity.
    assert all(c["color_identity"] == [] for c in get(client, identity="C"))
