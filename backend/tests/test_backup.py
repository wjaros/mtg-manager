import shutil

import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.config import Settings
from tests.helpers import SEEDS_DIR


def make_client(tmp_path, template, name):
    settings = Settings(data_dir=tmp_path / name, frontend_dist=tmp_path / "dist")
    settings.ensure_dirs()
    shutil.copy(template, settings.db_path)
    return TestClient(create_app(settings))


@pytest.fixture
def source(tmp_path, card_db_template):
    with make_client(tmp_path, card_db_template, "source") as c:
        yield c


@pytest.fixture
def target(tmp_path, card_db_template):
    with make_client(tmp_path, card_db_template, "target") as c:
        yield c


def import_seed(client, file: str) -> int:
    report = client.post("/api/import/parse", json={"text": (SEEDS_DIR / file).read_text(encoding="utf-8")}).json()
    meta = report["meta"]
    return client.post("/api/import/commit", json={
        "name": meta["name"], "format": meta["format"], "platform": meta["platform"],
        "preferred_sets": meta["preferred_sets"],
        "entries": [{"card_id": l["card"]["id"], "quantity": l["quantity"], "board": l["board"]} for l in report["lines"]],
    }).json()["id"]


def fill(client):
    deck_id = import_seed(client, "doctor-who-blast-from-the-past.txt")
    import_seed(client, "quintorius-lorehold-spirit.txt")
    client.post(f"/api/decks/{deck_id}/collection")
    binder = client.post("/api/locations", json={"name": "Binder", "kind": "binder"}).json()
    bolt = client.get("/api/cards", params={"q": "lightning bolt"}).json()["items"][0]
    client.post("/api/collection", json={"card_id": bolt["id"], "finish": "foil", "condition": "LP",
                                         "language": "pl", "location_id": binder["id"], "note": "z turnieju"})


def snapshot(client):
    decks = sorted(
        (d["name"], d["format"], d["commander_name"], d["counts"]["total"], d["location_id"] is not None)
        for d in client.get("/api/decks").json()
    )
    items = sorted(
        (i["card"]["id"], i["quantity"], i["finish"], i["language"], i["condition"],
         i["location"]["name"] if i["location"] else None, i["note"])
        for i in client.get("/api/collection").json()
    )
    return decks, items


def test_export_import_round_trip(source, target):
    fill(source)
    resp = source.get("/api/backup/export")
    assert "attachment" in resp.headers["content-disposition"]
    backup = resp.json()
    assert backup["format"] == "mtgdm-backup" and len(backup["decks"]) == 2

    result = target.post("/api/backup/import", json=backup).json()
    assert result["missing_cards"] == []
    assert result["decks"] == 2 and result["locations"] == 2
    assert snapshot(target) == snapshot(source)


def test_replace_vs_merge(source):
    fill(source)
    backup = source.get("/api/backup/export").json()
    before = snapshot(source)

    source.post("/api/backup/import", json=backup)  # merge: everything twice
    assert len(source.get("/api/decks").json()) == 4

    source.post("/api/backup/import", params={"replace": True}, json=backup)
    assert snapshot(source) == before


def test_cards_resolved_by_set_number_then_name(source, target):
    fill(source)
    backup = source.get("/api/backup/export").json()
    deck = backup["decks"][0]
    deck["cards"][0]["card_id"] = "00000000-0000-0000-0000-000000000000"  # unknown id, same set/number
    deck["cards"][1].update(card_id="x", set="zzz", collector_number="0")  # only the name matches
    deck["cards"][2].update(card_id="x", set="zzz", collector_number="0", name="Not A Real Card")

    result = target.post("/api/backup/import", json=backup).json()
    assert result["missing_cards"] == ["Not A Real Card"]
    imported = next(d for d in target.get("/api/decks").json() if d["name"] == deck["name"])
    assert imported["counts"]["total"] == 99


def test_invalid_files_change_nothing(source):
    fill(source)
    before = snapshot(source)
    assert source.post("/api/backup/import", json={"hello": "world"}).status_code == 422
    broken = source.get("/api/backup/export").json()
    del broken["decks"][1]["name"]
    resp = source.post("/api/backup/import", params={"replace": True}, json=broken)
    assert resp.status_code == 422
    assert snapshot(source) == before
    newer = {**source.get("/api/backup/export").json(), "version": 99}
    assert source.post("/api/backup/import", json=newer).status_code == 422


def test_deck_history_round_trip(source, target):
    deck_id = import_seed(source, "quintorius-lorehold-spirit.txt")
    bolt = source.get("/api/cards", params={"q": "lightning bolt"}).json()["items"][0]
    source.post(f"/api/decks/{deck_id}/cards", json={"card_id": bolt["id"], "board": "maybe"})
    source.post(f"/api/decks/{deck_id}/versions", json={"note": "bolt"})
    source.post(f"/api/decks/{deck_id}/cards", json={"card_id": bolt["id"], "board": "sideboard"})  # unsaved

    def history(client):
        deck = client.get("/api/decks").json()[0]
        versions = client.get(f"/api/decks/{deck['id']}/versions").json()
        return [(v["number"], v["note"], v["total"], v["added"], v["removed"]) for v in versions], deck["unsaved_changes"]

    target.post("/api/backup/import", json=source.get("/api/backup/export").json())
    assert history(target) == history(source)
    assert history(target)[1] == 1

    # Older backups without history: the restored deck becomes version 1.
    backup = source.get("/api/backup/export").json()
    del backup["decks"][0]["versions"]
    target.post("/api/backup/import", json=backup, params={"replace": True})
    assert history(target) == ([(1, "Przywrócono z kopii", 100, 102, 0)], 0)
