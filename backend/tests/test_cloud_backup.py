import json
import shutil

import pytest
from fastapi.testclient import TestClient

from mtgdm import cloud_backup
from mtgdm.app import create_app
from mtgdm.config import Settings
from mtgdm.db import connect


@pytest.fixture
def computers(tmp_path, card_db_template):
    """Two installs of the app (two "computers") and the folder a sync client shares between them."""
    shared = tmp_path / "iCloud Drive" / "MTG Deck Manager"
    clients = []
    for name in ("home", "work"):
        s = Settings(data_dir=tmp_path / name, frontend_dist=tmp_path / "dist")
        s.ensure_dirs()
        shutil.copy(card_db_template, s.db_path)
        clients.append(TestClient(create_app(s)))
    for c in clients:
        c.__enter__()
    yield clients[0], clients[1], shared
    for c in clients:
        c.__exit__(None, None, None)


def card(client, name: str) -> dict:
    return client.get("/api/cards", params={"q": f'!"{name}"'}).json()["items"][0]


def enable(client, folder) -> dict:
    resp = client.put("/api/backup/cloud", json={"folder": str(folder), "enabled": True})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_writes_on_change_only(computers, monkeypatch):
    home, _, shared = computers
    monkeypatch.setattr(cloud_backup, "machine_name", lambda: "home-mac")
    home.post("/api/collection", json={"card_id": card(home, "Serra Angel")["id"]})
    status = enable(home, shared)
    assert status["last_written_at"] and status["newer"] is None
    data = json.loads((shared / "mtgdm-backup.json").read_text(encoding="utf-8"))
    assert data["machine"]["name"] == "home-mac" and len(data["collection"]) == 1

    conn = connect(home.app.state.settings.db_path)
    assert cloud_backup.write_if_changed(conn) is False  # nothing changed
    home.post("/api/decks", json={"name": "New deck"})
    assert cloud_backup.write_if_changed(conn) is True
    assert len(json.loads((shared / "mtgdm-backup.json").read_text(encoding="utf-8"))["decks"]) == 1
    # The previous file went to history; no temporary files are left.
    assert len(list((shared / "history").glob("mtgdm-backup-*.json"))) == 1
    assert not list(shared.glob(".*part"))
    conn.close()


def test_other_computer_loads_newer_data(computers, monkeypatch):
    home, work, shared = computers
    home.post("/api/collection", json={"card_id": card(home, "Serra Angel")["id"], "quantity": 4})
    enable(home, shared)
    # The work computer has its own (older, different) data.
    work.post("/api/decks", json={"name": "Work deck"})
    status = enable(work, shared)
    newer = status["newer"]
    assert newer is not None and newer["collection_items"] == 1 and newer["decks"] == 0
    # Its own data doesn't overwrite the file while the newer one waits.
    conn = connect(work.app.state.settings.db_path)
    assert cloud_backup.write_if_changed(conn) is False
    conn.close()

    result = work.post("/api/backup/cloud/load").json()
    assert result["collection_items"] == 1
    assert work.get("/api/collection").json()[0]["quantity"] == 4
    assert work.get("/api/decks").json() == []  # replaced (and kept in history)
    history = [json.loads(p.read_text(encoding="utf-8")) for p in (shared / "history").glob("*.json")]
    assert any(h["machine"].get("replaced") and h["decks"][0]["name"] == "Work deck" for h in history)

    # Loaded = in sync: no offer, nothing to write back, and home isn't offered its own data back.
    assert work.get("/api/backup/cloud").json()["newer"] is None
    conn = connect(work.app.state.settings.db_path)
    assert cloud_backup.write_if_changed(conn) is False
    conn.close()
    assert home.get("/api/backup/cloud").json()["newer"] is None

    # A change at work is offered at home.
    work.post("/api/decks", json={"name": "Built at work"})
    conn = connect(work.app.state.settings.db_path)
    assert cloud_backup.write_if_changed(conn) is True
    conn.close()
    assert home.get("/api/backup/cloud").json()["newer"]["decks"] == 1


def test_dismiss_keeps_own_data(computers):
    home, work, shared = computers
    home.post("/api/decks", json={"name": "Home deck"})
    enable(home, shared)
    assert enable(work, shared)["newer"] is not None
    assert work.post("/api/backup/cloud/dismiss").status_code == 204
    assert work.get("/api/backup/cloud").json()["newer"] is None
    # Now work's own data may be written (it becomes the newest for home).
    work.post("/api/decks", json={"name": "Work deck"})
    conn = connect(work.app.state.settings.db_path)
    assert cloud_backup.write_if_changed(conn) is True
    conn.close()
    assert home.get("/api/backup/cloud").json()["newer"] is not None


def test_bad_folder(computers, tmp_path):
    home, _, _ = computers
    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    resp = home.put("/api/backup/cloud", json={"folder": str(blocker / "sub"), "enabled": True})
    assert resp.status_code == 422
    assert home.put("/api/backup/cloud", json={"folder": None, "enabled": True}).status_code == 422
    off = home.put("/api/backup/cloud", json={"folder": None, "enabled": False}).json()
    assert off["enabled"] is False


def test_history_is_trimmed(tmp_path):
    for i in range(cloud_backup.KEEP_HISTORY + 5):
        cloud_backup._keep_in_history(tmp_path, {"machine": {"name": "m", "written_at": f"2026-01-01T00:00:{i:02d}"}})
    kept = sorted(p.name for p in (tmp_path / "history").glob("*.json"))
    assert len(kept) == cloud_backup.KEEP_HISTORY and kept[-1].endswith("00-00-24-m.json")
