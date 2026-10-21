import io

import cv2
import httpx
import numpy as np
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect
from mtgdm.decks.pdf import deck_pages, render_pdf
from mtgdm.scryfall import ScryfallClient
from tests.helpers import SEEDS_DIR

FETCHED: list[str] = []


def fake_cdn(request: httpx.Request) -> httpx.Response:
    """Any card image: a plain JPEG of the "large" size."""
    FETCHED.append(str(request.url))
    image = np.full((936, 672, 3), 120, np.uint8)
    return httpx.Response(200, content=cv2.imencode(".jpg", image)[1].tobytes())


@pytest.fixture
def client(card_settings):
    scryfall = ScryfallClient(httpx.Client(transport=httpx.MockTransport(fake_cdn)), min_interval=0)
    with TestClient(create_app(card_settings, scryfall=scryfall)) as c:
        c.settings = card_settings
        yield c


def import_seed(client, file: str) -> int:
    report = client.post("/api/import/parse", json={"text": (SEEDS_DIR / file).read_text(encoding="utf-8")}).json()
    meta = report["meta"]
    return client.post("/api/import/commit", json={
        "name": meta["name"], "format": meta["format"], "platform": meta["platform"],
        "entries": [{"card_id": l["card"]["id"], "quantity": l["quantity"], "board": l["board"]} for l in report["lines"]],
    }).json()["id"]


def test_page_order(client):
    deck_id = import_seed(client, "doctor-who-blast-from-the-past.txt")
    conn = connect(client.settings.db_path)
    pages = deck_pages(conn, deck_id)
    deck = client.get(f"/api/decks/{deck_id}").json()
    by_id = {c["card"]["id"]: c for c in deck["cards"]}

    # Commander(s) first, then the companion (Doctor Who: a Doctor + a companion as partner commanders).
    commanders = [c["card"]["id"] for c in deck["cards"] if c["board"] == "commander"]
    assert [p.card_id for p in pages[:len(commanders)]] == commanders
    rest = [p for p in pages[len(commanders):] if p.face == 0]
    kinds = ["Land" in (by_id[p.card_id]["card"]["type_line"] or "").split("//")[0] for p in rest]
    assert kinds == sorted(kinds), "lands come last"
    spells = [by_id[p.card_id]["card"] for p, land in zip(rest, kinds) if not land]
    assert [(c["cmc"], c["name"]) for c in spells] == sorted((c["cmc"], c["name"]) for c in spells)
    # One page per card (not per copy), plus back faces; sideboard/maybeboard left out.
    main = [c for c in deck["cards"] if c["board"] in ("main", "commander", "companion")]
    assert len([p for p in pages if p.face == 0]) == len(main)
    assert all(p.quantity == by_id[p.card_id]["quantity"] for p in pages)


def test_double_faced_cards_get_two_pages(client):
    deck = client.post("/api/decks", json={"name": "DFC"}).json()
    delver = client.get("/api/cards", params={"q": "delver of secrets"}).json()["items"][0]
    assert delver["image_faces"] == 2
    client.post(f"/api/decks/{deck['id']}/cards", json={"card_id": delver["id"], "quantity": 4})
    pages = deck_pages(connect(client.settings.db_path), deck["id"])
    assert [(p.face, p.quantity) for p in pages] == [(0, 4), (1, 4)]


def test_pdf_endpoint(client):
    deck_id = import_seed(client, "giada-font-of-hope.txt")
    resp = client.get(f"/api/decks/{deck_id}/export/pdf")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
    assert 'filename="Giada_ Font of Hope.pdf"' in resp.headers["content-disposition"]
    assert "filename*=UTF-8''Giada%2C%20Font%20of%20Hope.pdf" in resp.headers["content-disposition"]
    pdf = pdfium.PdfDocument(resp.content)
    pages = deck_pages(connect(client.settings.db_path), deck_id)
    assert len(pdf) == len(pages)
    width, height = pdf[0].get_size()
    assert height > width  # portrait, card-shaped
    assert any("/large/" in url for url in FETCHED)
    assert client.get("/api/decks/999/export/pdf").status_code == 404


def test_offline_pages_are_text():
    from mtgdm.decks.pdf import Page

    data = render_pdf([Page("x", 0, 2, "Sol Ring", "{1}")], lambda card_id, face: None)
    assert len(pdfium.PdfDocument(io.BytesIO(data).getvalue())) == 1
    assert len(pdfium.PdfDocument(render_pdf([], lambda c, f: None))) == 1  # empty deck: one blank page
