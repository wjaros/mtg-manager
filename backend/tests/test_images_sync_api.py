import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect
from mtgdm.scryfall import ScryfallClient
from mtgdm.scryfall.bulk import CardSyncResult
from mtgdm.scryfall.manager import SyncManager
from mtgdm.scryfall.sync import SyncResult
from tests.helpers import fixture_cards

CARDS = fixture_cards()


class FakeScryfall:
    def __init__(self):
        self.image_requests: list[str] = []
        self.fail_images = False

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "cards.scryfall.io":
            self.image_requests.append(str(request.url))
            if self.fail_images:
                return httpx.Response(503, text="down")
            return httpx.Response(200, content=b"JPEG:" + request.url.path.encode())
        if request.url.path == "/bulk-data":
            return httpx.Response(200, json={"object": "list", "has_more": False, "data": [
                {"type": "default_cards", "updated_at": "2026-10-21T00:00:00+00:00"},
            ]})
        return httpx.Response(404, json={"object": "error", "details": "unexpected"})


@pytest.fixture
def fake():
    return FakeScryfall()


@pytest.fixture
def settings(card_settings):
    return card_settings


@pytest.fixture
def client(settings, fake):
    scryfall = ScryfallClient(httpx.Client(transport=httpx.MockTransport(fake)), min_interval=0)
    with TestClient(create_app(settings, scryfall=scryfall)) as c:
        yield c


def card_id(name: str) -> str:
    return next(c["id"] for c in CARDS if c["name"] == name)


def test_image_downloaded_once_then_served_from_cache(client, fake, settings):
    cid = card_id("Serra Angel")
    first = client.get(f"/api/images/{cid}/normal")
    assert first.status_code == 200
    assert first.headers["content-type"] == "image/jpeg"
    assert first.content.startswith(b"JPEG:/normal/")
    assert client.get(f"/api/images/{cid}/normal").content == first.content
    assert len(fake.image_requests) == 1
    assert (settings.images_dir / "cards" / "normal" / cid[:2] / f"{cid}-0.jpg").is_file()


def test_double_faced_images(client, fake):
    cid = card_id("Delver of Secrets // Insectile Aberration")
    front = client.get(f"/api/images/{cid}/small", params={"face": 0})
    back = client.get(f"/api/images/{cid}/small", params={"face": 1})
    assert front.status_code == back.status_code == 200
    assert front.content != back.content
    # Single-faced cards have no back image.
    assert client.get(f"/api/images/{card_id('Sol Ring')}/small", params={"face": 1}).status_code == 404


def test_image_errors(client, fake):
    assert client.get("/api/images/nope/normal").status_code == 404
    assert client.get(f"/api/images/{card_id('Sol Ring')}/huge").status_code == 422
    fake.fail_images = True
    assert client.get(f"/api/images/{card_id('Sol Ring')}/large").status_code == 502


def test_concurrent_requests_download_once(settings, fake):
    from mtgdm.scryfall.images import ImageCache

    scryfall = ScryfallClient(httpx.Client(transport=httpx.MockTransport(fake)), min_interval=0)
    cache = ImageCache(settings.images_dir, scryfall)
    cid = card_id("Giada, Font of Hope")

    def worker():
        conn = connect(settings.db_path)
        cache.get(conn, cid, "normal")
        conn.close()

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(fake.image_requests) == 1


def test_sync_status(client, settings):
    status = client.get("/api/sync/status").json()
    assert status["card_count"] == len(CARDS)
    assert status["oracle_count"] > 0
    assert status["cards_updated_at"] == "2026-10-20T09:06:24.827+00:00"
    assert status["progress"]["running"] is False
    assert status["data_dir"] == str(settings.data_dir)


def test_sync_check(client):
    check = client.get("/api/sync/check").json()
    assert check == {
        "local_updated_at": "2026-10-20T09:06:24.827+00:00",
        "remote_updated_at": "2026-10-21T00:00:00+00:00",
        "update_available": True,
    }


def test_sync_start_runs_in_background_and_streams_events(client):
    gate = threading.Event()
    calls = []

    def runner(settings, *, force, client, on_progress):
        calls.append(force)
        on_progress("download", 5, 10)
        gate.wait(5)
        on_progress("import", 100, 0)
        return SyncResult(sets=3, cards=CardSyncResult(updated_at="x", cards=100))

    manager: SyncManager = client.app.state.sync_manager
    manager._runner = runner

    resp = client.post("/api/sync/start", json={"force": True})
    assert resp.status_code == 202 and resp.json()["running"]
    assert client.post("/api/sync/start").status_code == 409

    deadline = time.time() + 5
    while manager.snapshot().stage != "download" and time.time() < deadline:
        time.sleep(0.01)
    gate.set()

    with client.stream("GET", "/api/sync/events") as stream:
        events = [json.loads(line[len("data: "):]) for line in stream.iter_lines() if line.startswith("data: ")]
    final = events[-1]
    assert final["running"] is False
    assert final["result"]["cards"] == 100 and final["error"] is None
    assert calls == [True]


def test_sync_error_is_reported(client):
    def runner(settings, **kwargs):
        raise RuntimeError("disk full")

    manager: SyncManager = client.app.state.sync_manager
    manager._runner = runner
    assert client.post("/api/sync/start").status_code == 202
    manager.wait(5)
    progress = client.get("/api/sync/status").json()["progress"]
    assert progress["running"] is False and progress["error"] == "disk full"
