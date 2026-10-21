import io
import json
import sys
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.scan.ocr.base import available_engines
from mtgdm.scan.synth import synth_photo
from mtgdm.scryfall import ScryfallClient

pytestmark = pytest.mark.skipif("rapidocr" not in available_engines(), reason="RapidOCR not installed")

SCANS = Path(__file__).parent / "fixtures" / "scans"
CARDS = SCANS / "cards"
MANIFEST = json.loads((CARDS / "manifest.json").read_text(encoding="utf-8"))
GIADA = next(c for c in MANIFEST if c["set"] == "fdn" and c["collector_number"] == "141")
SERRA = next(c for c in MANIFEST if c["set"] == "dom" and c["collector_number"] == "33")


def fake_cdn(request: httpx.Request) -> httpx.Response:
    """Card images by the Scryfall id in the image URL (fixture images only)."""
    card_id = request.url.path.rsplit("/", 1)[-1].split(".")[0]
    path = CARDS / f"{card_id}.jpg"
    if request.url.host == "cards.scryfall.io" and path.is_file():
        return httpx.Response(200, content=path.read_bytes())
    return httpx.Response(404)


@pytest.fixture
def client(card_settings):
    scryfall = ScryfallClient(httpx.Client(transport=httpx.MockTransport(fake_cdn)), min_interval=0)
    with TestClient(create_app(card_settings, scryfall=scryfall)) as c:
        yield c


def photo_bytes(entry: dict, seed: int = 3) -> bytes:
    image = synth_photo(cv2.imread(str(CARDS / f"{entry['id']}.jpg")), np.random.default_rng(seed), upside_down=False).image
    return cv2.imencode(".jpg", image)[1].tobytes()


def upload_all(client, data: bytes, name: str = "photo.jpg", mime: str = "image/jpeg", **form) -> list[dict]:
    resp = client.post("/api/scans", files={"file": (name, data, mime)}, data={"engine": "rapidocr", **form})
    assert resp.status_code == 201, resp.text
    return resp.json()


def upload(client, data: bytes, name: str = "photo.jpg", **form) -> dict:
    scans = upload_all(client, data, name, **form)
    assert len(scans) == 1
    return scans[0]


def test_upload_review_commit(client):
    scan = upload(client, photo_bytes(GIADA))
    assert scan["status"] == "processed" and scan["ocr_engine"] == "rapidocr"
    item = scan["items"][0]
    assert item["chosen"]["id"] == GIADA["id"]
    assert item["confidence"] >= 0.9 and item["status"] == "pending"
    assert (item["ocr_name"], item["ocr_number"], item["ocr_set"]) == ("Giada, Font of Hope", "141", "fdn")
    assert len(item["corners"]) == 4

    original = client.get(f"/api/scans/{scan['id']}/image")
    assert original.headers["content-type"] == "image/jpeg"
    crop = client.get(f"/api/scans/{scan['id']}/items/{item['id']}/image")
    # Ids are reused after deletes: never serve a cached image for a reused URL.
    assert original.headers["cache-control"] == crop.headers["cache-control"] == "no-cache"
    assert crop.status_code == 200 and cv2.imdecode(np.frombuffer(crop.content, np.uint8), 1).shape[:2] == (1040, 744)

    box = client.post("/api/locations", json={"name": "Binder"}).json()
    updated = client.patch(f"/api/scans/{scan['id']}/items/{item['id']}", json={
        "status": "accepted", "quantity": 2, "finish": "foil", "condition": "EX", "location_id": box["id"],
    }).json()
    assert updated["items"][0]["status"] == "accepted"

    result = client.post(f"/api/scans/{scan['id']}/commit").json()
    assert result == {"added": 2, "items": 1}
    copies = client.get("/api/collection").json()
    assert [(c["card"]["id"], c["quantity"], c["finish"], c["condition"], c["location"]["name"], c["source"])
            for c in copies] == [(GIADA["id"], 2, "foil", "EX", "Binder", "scan")]
    assert client.get(f"/api/scans/{scan['id']}").json()["status"] == "committed"
    assert client.post(f"/api/scans/{scan['id']}/commit").status_code == 422  # never twice


def test_correct_the_card_by_hand(client):
    scan = upload(client, photo_bytes(SERRA))
    item = scan["items"][0]
    giada_id = GIADA["id"]
    corrected = client.patch(f"/api/scans/{scan['id']}/items/{item['id']}", json={"chosen_card_id": giada_id}).json()
    assert corrected["items"][0]["chosen"]["id"] == giada_id
    assert corrected["items"][0]["status"] == "accepted"  # choosing by hand accepts
    assert client.patch(f"/api/scans/{scan['id']}/items/{item['id']}", json={"chosen_card_id": "nope"}).status_code == 422


def test_rejected_and_pending_items_are_not_added(client):
    scan = upload(client, photo_bytes(SERRA))
    item = scan["items"][0]
    client.patch(f"/api/scans/{scan['id']}/items/{item['id']}", json={"status": "rejected"})
    assert client.post(f"/api/scans/{scan['id']}/commit").json() == {"added": 0, "items": 0}
    assert client.get("/api/collection").json() == []


def test_cropped_scan_without_background(client):
    data = (CARDS / f"{SERRA['id']}.jpg").read_bytes()
    item = upload(client, data, "scan.jpg")["items"][0]
    assert item["chosen"]["id"] == SERRA["id"]


def test_delete_keeps_collection(client, card_settings):
    scan = upload(client, photo_bytes(GIADA))
    item = scan["items"][0]
    client.patch(f"/api/scans/{scan['id']}/items/{item['id']}", json={"status": "accepted"})
    client.post(f"/api/scans/{scan['id']}/commit")
    assert client.delete(f"/api/scans/{scan['id']}").status_code == 204
    assert not (card_settings.scans_dir / str(scan["id"])).exists()
    assert len(client.get("/api/collection").json()) == 1
    assert client.get(f"/api/scans/{scan['id']}").status_code == 404
    assert client.get("/api/scans").json() == []


def test_bad_uploads(client):
    bad_type = client.post("/api/scans", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert bad_type.status_code == 422
    broken = client.post("/api/scans", files={"file": ("photo.jpg", b"not an image", "image/jpeg")})
    assert broken.status_code == 422
    engine = client.post("/api/scans", files={"file": ("p.jpg", photo_bytes(GIADA), "image/jpeg")}, data={"engine": "x"})
    assert engine.status_code == 422
    assert "rapidocr" in client.get("/api/scan-engines").json()["available"]


# --- pages (E6) -----------------------------------------------------------------------


def page_image(seed: int, **kwargs):
    from mtgdm.scan.synth import synth_page

    images = [cv2.imread(str(CARDS / f"{c['id']}.jpg")) for c in MANIFEST]
    return synth_page(images, np.random.default_rng(seed), **kwargs)


def test_page_scan_finds_cards_in_reading_order(client):
    page = page_image(4, fill=1.0)
    scan = upload(client, cv2.imencode(".jpg", page.image)[1].tobytes(), "page.jpg")
    assert scan["kind"] == "page"
    names = [i["chosen"]["name"] if i["chosen"] else None for i in scan["items"]]
    expected = [MANIFEST[index]["name"] for index, _ in page.cards]
    assert len(names) >= len(expected) - 1
    # Reading order: rows top to bottom, left to right (match by position of the found cards).
    assert sum(n == e for n, e in zip(names, expected)) >= len(expected) - 2


def test_pdf_pages_become_separate_scans(client):
    from PIL import Image

    pages = [page_image(seed, fill=0.3, rows=2, cols=2) for seed in (8, 9)]
    pil = [Image.fromarray(cv2.cvtColor(p.image, cv2.COLOR_BGR2RGB)) for p in pages]
    buffer = io.BytesIO()
    pil[0].save(buffer, format="PDF", save_all=True, append_images=pil[1:], resolution=300)
    scans = upload_all(client, buffer.getvalue(), "scan.pdf", "application/pdf")
    assert [s["original_name"] for s in scans] == ["scan.pdf (str. 1)", "scan.pdf (str. 2)"]
    for scan, page in zip(scans, pages):
        assert len(scan["items"]) == len(page.cards)


def test_manual_grid(client):
    page = page_image(5, fill=1.0, rows=2, cols=2)
    scan = upload(client, cv2.imencode(".jpg", page.image)[1].tobytes(), "page.jpg")
    regridded = client.post(f"/api/scans/{scan['id']}/grid", json={"rows": 2, "cols": 2}).json()
    assert regridded["kind"] == "page" and len(regridded["items"]) == 4
    expected = {MANIFEST[index]["name"] for index, _ in page.cards}
    assert {i["chosen"]["name"] for i in regridded["items"] if i["chosen"]} == expected
    # A region holding only the top row.
    top_row = client.post(f"/api/scans/{scan['id']}/grid", json={"rows": 1, "cols": 2, "region": [0, 0, 1, 0.5]}).json()
    assert len(top_row["items"]) == 2
    assert client.post(f"/api/scans/{scan['id']}/grid", json={"rows": 0, "cols": 2}).status_code == 422


def test_grid_skips_empty_cells(client):
    page = page_image(6, fill=1.0, rows=1, cols=2)
    scan = upload(client, cv2.imencode(".jpg", page.image)[1].tobytes(), "page.jpg")
    # 3x3 grid over a page with only two cards in the first row band.
    result = client.post(f"/api/scans/{scan['id']}/grid", json={"rows": 3, "cols": 2}).json()
    assert len(result["items"]) <= 4


@pytest.mark.skipif(sys.platform != "darwin", reason="HEIC through ImageIO is macOS only (elsewhere: pillow-heif)")
def test_heic_photo_on_macos(client):
    """iPhone photos: decoded by macOS ImageIO (same pixels as the JPEG it was made from, BGR,
    capped size), then recognized like any photo."""
    from mtgdm.scan.imageio_mac import decode
    from mtgdm.scan.service import decode_images

    data = (SCANS / "giada-photo.heic").read_bytes()
    (image,) = decode_images(data, "IMG_0001.HEIC")
    original = cv2.imread(str(SCANS / "giada-photo.jpg"))
    assert image.shape == original.shape
    assert float(np.abs(image.astype(int) - original.astype(int)).mean()) < 6  # lossy, but same colours
    assert max(decode(data, 800).shape[:2]) == 800
    item = upload(client, data, "IMG_0001.HEIC")["items"][0]
    assert item["chosen"]["id"] == GIADA["id"]


def test_heic_elsewhere_asks_for_jpg(client, monkeypatch):
    from mtgdm.scan import service

    monkeypatch.setattr(service.sys, "platform", "win32")
    resp = client.post("/api/scans", files={"file": ("IMG_0001.HEIC", b"whatever", "image/heic")},
                       headers={"Accept-Language": "en"})
    assert resp.status_code == 422 and "macOS only" in resp.json()["detail"]
