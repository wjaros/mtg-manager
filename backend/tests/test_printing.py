import time

import cv2
import httpx
import numpy as np
import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect
from mtgdm.printing.layout import Correction, PageLayout, calibrate
from mtgdm.printing.profiles import (
    Measurements,
    PrintSettings,
    ProfileCreate,
    calibrate_profile,
    create_profile,
    recompute,
    save_settings,
)
from mtgdm.scryfall import ScryfallClient
from tests.test_missing import ADDED, PRECON, import_deck, upgrade_text

MM_TO_PT = 72 / 25.4
FETCHED: list[str] = []


# --- layout --------------------------------------------------------------------------


def test_grid_is_centred():
    a4 = PageLayout("a4", 63, 88)
    assert a4.grid.x == pytest.approx(10.5) and a4.grid.y == pytest.approx(16.5)
    assert (a4.grid.w, a4.grid.h) == pytest.approx((189, 264))
    letter = PageLayout("letter", 63, 88)
    assert letter.grid.x == pytest.approx(13.45) and letter.grid.y == pytest.approx(7.7)

    frames = a4.frames()
    assert len(frames) == 9
    centre = frames[4]
    assert (centre.x, centre.y, centre.w, centre.h) == pytest.approx((73.5, 104.5, 63, 88))


def test_gap_and_cut_guides():
    shared = PageLayout("a4", 63, 88)
    assert len(shared.edges()[0]) == 4 and shared.cut_lines() == []
    gapped = PageLayout("a4", 63, 88, gap=1.0)
    assert gapped.grid.w == pytest.approx(191) and gapped.grid.x == pytest.approx(9.5)
    assert gapped.frames()[1].x == pytest.approx(9.5 + 64)
    assert len(gapped.edges()[0]) == 6 and len(gapped.cut_lines()) == 12

    # Crop marks stay in the margins: never over a card.
    for layout in (shared, gapped, PageLayout("letter", 63, 88)):
        g = layout.grid
        for m in layout.crop_marks():
            inside_x = g.x < min(m.x1, m.x2) and max(m.x1, m.x2) < g.right
            inside_y = g.y < min(m.y1, m.y2) and max(m.y1, m.y2) < g.bottom
            assert not (inside_x and inside_y)
            assert (m.x1 == m.x2 and (m.y2 <= g.y or m.y1 >= g.bottom)) or \
                   (m.y1 == m.y2 and (m.x2 <= g.x or m.x1 >= g.right))
    # Letter's top margin is narrow: shorter marks that end in the printable area.
    letter = PageLayout("letter", 63, 88)
    assert letter.mark_length == pytest.approx(7.7 - 3 - 1) and not letter.overflow()


def test_compensated_geometry():
    c = Correction(scale_x=1.02, scale_y=0.985, offset_x=0.4, offset_y=-0.3)
    frame = PageLayout("a4", 63, 88).frames()[4]
    page = c.rect(frame)
    assert (page.x, page.y, page.w, page.h) == pytest.approx((73.5 * 1.02 + 0.4, 104.5 * 0.985 - 0.3, 64.26, 86.68))

    # A printer that does the inverse (p -> p / scale - offset / scale) prints the nominal frame.
    printed_x = page.x / c.scale_x - c.offset_x / c.scale_x
    printed_w = page.w / c.scale_x
    assert (printed_x, printed_w) == pytest.approx((frame.x, frame.w))

    # The image is never stretched: one scale, centred in the compensated frame.
    image = c.image_rect(frame)
    assert image.w / image.h == pytest.approx(63 / 88)
    assert image.w == pytest.approx(63 * 1.0025)
    assert image.x + image.w / 2 == pytest.approx(page.x + page.w / 2)
    assert image.y + image.h / 2 == pytest.approx(page.y + page.h / 2)

    assert PageLayout("a4", 63, 88, 2.0).overflow(Correction(1.08, 1.08)) is True


# --- calibration ---------------------------------------------------------------------


def test_calibration_round_trip():
    """Simulate a printer: printed = k * drawn + o, per axis."""
    kx, ox, ky, oy = 0.985, 0.7, 1.012, -1.1
    layout = PageLayout("a4", 63, 88)
    g = layout.grid
    result = calibrate("a4", 63, 88, measured_a=g.w * kx, measured_b=g.h * ky,
                       measured_left=g.x * kx + ox, measured_top=g.y * ky + oy)
    c = result.correction
    assert (c.scale_x, c.scale_y) == pytest.approx((1 / kx, 1 / ky))
    assert result.difference_x_pct == pytest.approx(-1.5) and result.difference_y_pct == pytest.approx(1.2)
    assert not result.out_of_range
    # The compensated page prints at nominal size and position.
    for frame in layout.frames():
        page = c.rect(frame)
        assert page.x * kx + ox == pytest.approx(frame.x)
        assert page.y * ky + oy == pytest.approx(frame.y)
        assert page.w * kx == pytest.approx(frame.w) and page.h * ky == pytest.approx(frame.h)

    # Without edge measurements: scale only.
    assert calibrate("a4", 63, 88, 189, 264).correction == Correction()
    # "Fit to page" left on (or a typo): flagged.
    assert calibrate("a4", 63, 88, 170, 264).out_of_range


def test_profile_keeps_its_calibration_card_size(db):
    profile = create_profile(db, ProfileCreate(name="Brother laser"))
    assert profile.is_default  # the first one
    result = calibrate_profile(db, profile.id, Measurements(measured_a_mm=187.5, measured_b_mm=265.0))
    assert result.profile.scale_x == pytest.approx(189 / 187.5)
    assert result.profile.card_w_mm == 63

    # A different card size later: the printer's factors stay, recomputed from the raw measurements.
    save_settings(db, PrintSettings(card_w_mm=63.5, card_h_mm=88.9))
    again = recompute(result.profile)
    assert (again.scale_x, again.scale_y) == pytest.approx((result.profile.scale_x, result.profile.scale_y))


# --- API -----------------------------------------------------------------------------


def fake_cdn(request: httpx.Request) -> httpx.Response:
    """Any card image: an RGBA PNG for "png", a JPEG otherwise."""
    FETCHED.append(str(request.url))
    if "/png/" in str(request.url) or str(request.url).endswith(".png"):
        image = np.full((1040, 745, 4), 200, np.uint8)
        image[:20, :20, 3] = 0  # a transparent corner
        return httpx.Response(200, content=cv2.imencode(".png", image)[1].tobytes())
    return httpx.Response(200, content=cv2.imencode(".jpg", np.full((936, 672, 3), 120, np.uint8))[1].tobytes())


@pytest.fixture
def client(card_settings):
    scryfall = ScryfallClient(httpx.Client(transport=httpx.MockTransport(fake_cdn)), min_interval=0)
    with TestClient(create_app(card_settings, scryfall=scryfall)) as c:
        c.settings = card_settings
        yield c


def card(client, name: str) -> dict:
    return next(c for c in client.get("/api/cards", params={"q": f'!"{name}"'}).json()["items"])


def test_candidates(client):
    precon = import_deck(client, PRECON)
    assert client.post(f"/api/decks/{precon}/collection").status_code == 200  # every copy in the precon's box
    upgrade = import_deck(client, upgrade_text())
    bolt = card(client, "Lightning Bolt")
    # A loose copy can go into the upgrade: not a candidate.
    assert client.post("/api/collection", json={"card_id": bolt["id"]}).status_code == 201

    got = client.get(f"/api/decks/{upgrade}/proxy-candidates").json()
    missing = {c["name"]: c["qty"] for c in got if c["reason"] == "missing"}
    assert missing == {name: 1 for name in ADDED if name != "Lightning Bolt"}
    in_other = [c for c in got if c["reason"] == "in_other_deck"]
    assert in_other and all(c["other_decks"] == ["Quintorius – Lorehold Spirit (precon)"] for c in in_other)
    assert not any(c["name"] in ("Plains", "Mountain") for c in got)  # basics left out by default

    with_basics = client.get(f"/api/decks/{upgrade}/proxy-candidates", params={"include_basics": True}).json()
    plains = {c["reason"]: c["qty"] for c in with_basics if c["name"] == "Plains"}
    assert plains == {"missing": 1, "in_other_deck": 11}  # 12 needed, the 11 owned are in the precon's box

    assert client.get(f"/api/decks/{precon}/proxy-candidates").json() == []
    assert client.get("/api/decks/999/proxy-candidates").status_code == 404


def wait(client, job_id: str) -> dict:
    for _ in range(200):
        status = client.get(f"/api/print/jobs/{job_id}").json()
        if status["stage"] in ("done", "error"):
            return status
        time.sleep(0.05)
    raise AssertionError("print job did not finish")


def image_count(page) -> int:
    return sum(1 for _ in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE]))


def test_proxy_pdf(client):
    delver = card(client, "Delver of Secrets")
    assert delver["image_faces"] == 2
    serra = card(client, "Serra Angel")
    body = {"items": [{"card_id": serra["id"], "qty": 6}, {"card_id": delver["id"], "qty": 2}], "title": "Łódź deck"}
    resp = client.post("/api/print/jobs", json=body)
    assert resp.status_code == 202, resp.text
    status = wait(client, resp.json()["id"])
    assert status["stage"] == "done", status
    assert status["pages"] == 2 and status["total"] == 10  # 6 + 2 copies x 2 faces
    assert any("/png/" in url or url.endswith(".png") for url in FETCHED)

    pdf = client.get(f"/api/print/jobs/{status['id']}/pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert "filename*=UTF-8''%C5%81%C3%B3d%C5%BA%20deck%20-%20proxies.pdf" in pdf.headers["content-disposition"]
    doc = pdfium.PdfDocument(pdf.content)
    assert len(doc) == 2
    assert doc[0].get_size() == pytest.approx((210 * MM_TO_PT, 297 * MM_TO_PT))
    assert image_count(doc[0]) == 9 and image_count(doc[1]) == 1

    front_only = client.post("/api/print/jobs", json={
        "items": [{"card_id": delver["id"], "qty": 2, "faces": "front"}], "paper": "letter",
    }).json()
    status = wait(client, front_only["id"])
    doc = pdfium.PdfDocument(client.get(f"/api/print/jobs/{status['id']}/pdf").content)
    assert status["total"] == 2 and len(doc) == 1
    assert doc[0].get_size() == pytest.approx((215.9 * MM_TO_PT, 279.4 * MM_TO_PT))

    assert client.post("/api/print/jobs", json={"items": []}).status_code == 422
    assert client.post("/api/print/jobs", json={"items": [{"card_id": "nope", "qty": 1}]}).status_code == 404
    assert client.get("/api/print/jobs/nope/pdf").status_code == 404


def test_profiles_and_calibration_pages(client):
    page = client.get("/api/print/calibration.pdf", params={"paper": "letter"})
    assert page.status_code == 200
    assert pdfium.PdfDocument(page.content)[0].get_size() == pytest.approx((215.9 * MM_TO_PT, 279.4 * MM_TO_PT))

    profile = client.post("/api/print/profiles", json={"name": "Epson photo", "paper": "letter"}).json()
    second = client.post("/api/print/profiles", json={"name": "Brother", "is_default": True}).json()
    assert [p["name"] for p in client.get("/api/print/profiles").json()] == ["Brother", "Epson photo"]

    result = client.post(f"/api/print/profiles/{profile['id']}/calibrate",
                         json={"measured_a_mm": 186.0, "measured_b_mm": 266.0, "measured_left_mm": 14.0}).json()
    assert result["profile"]["scale_x"] == pytest.approx(189 / 186)
    assert result["difference_x_pct"] == pytest.approx((186 / 189 - 1) * 100)
    assert result["out_of_range"] is False
    bad = client.post(f"/api/print/profiles/{profile['id']}/calibrate",
                      json={"measured_a_mm": 150.0, "measured_b_mm": 264.0}).json()
    assert bad["out_of_range"] is True

    verification = client.get("/api/print/calibration.pdf", params={"paper": "letter", "profile_id": profile["id"]})
    assert verification.status_code == 200 and len(pdfium.PdfDocument(verification.content)) == 1

    assert client.delete(f"/api/print/profiles/{second['id']}").status_code == 204
    assert client.get("/api/print/profiles").json()[0]["is_default"] is True  # the remaining one
    assert client.patch("/api/print/profiles/999", json={"name": "x"}).status_code == 404

    settings = client.put("/api/print/settings", json={"card_w_mm": 63.5, "card_h_mm": 88.9}).json()
    assert client.get("/api/print/settings").json() == settings
    assert client.put("/api/print/settings", json={"card_w_mm": 10, "card_h_mm": 88}).status_code == 422


def test_backup_keeps_profiles(client):
    profile = client.post("/api/print/profiles", json={"name": "Brother"}).json()
    client.post(f"/api/print/profiles/{profile['id']}/calibrate", json={"measured_a_mm": 187, "measured_b_mm": 265})
    client.put("/api/print/settings", json={"card_w_mm": 63.5, "card_h_mm": 88.9})
    backup = client.get("/api/backup/export").json()
    assert backup["printer_profiles"][0]["measured_a_mm"] == 187

    conn = connect(client.settings.db_path)
    conn.execute("DELETE FROM printer_profiles")
    conn.execute("DELETE FROM meta WHERE key LIKE 'print_%'")
    conn.commit()
    result = client.post("/api/backup/import", json=backup, params={"replace": True}).json()
    assert result["printer_profiles"] == 1
    restored = client.get("/api/print/profiles").json()[0]
    assert restored["scale_x"] == pytest.approx(189 / 187) and restored["is_default"] is True
    assert client.get("/api/print/settings").json() == {"card_w_mm": 63.5, "card_h_mm": 88.9}
