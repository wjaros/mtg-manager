import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from mtgdm.db import connect
from mtgdm.scan.detect import find_cards
from mtgdm.scan.match import Matcher, _lookalikes
from mtgdm.scan.ocr.base import OcrLine, available_engines, get_engine
from mtgdm.scan.pipeline import is_cropped_card, scan_image
from mtgdm.scan.reader import read_card
from mtgdm.scan.synth import synth_photo

CARDS = Path(__file__).parent / "fixtures" / "scans" / "cards"
MANIFEST = json.loads((CARDS / "manifest.json").read_text(encoding="utf-8"))


def by_key(set_code: str, number: str) -> dict:
    return next(c for c in MANIFEST if c["set"] == set_code and c["collector_number"] == number)


def card_image(entry: dict) -> np.ndarray:
    return cv2.imread(str(CARDS / f"{entry['id']}.jpg"))


def line(text: str, x: float, y: float, w: float = 0.3, h: float = 0.02) -> OcrLine:
    return OcrLine(text=text, confidence=1.0, x=x, y=y, w=w, h=h)


# --- reading OCR lines -------------------------------------------------------------


def test_reader_2024_frame():
    card = read_card([
        line("Giada, Font of Hope", 0.08, 0.06, 0.48),
        line("1", 0.82, 0.06, 0.04),
        line("2/2", 0.82, 0.92, 0.08),
        line("R 0141", 0.06, 0.94),
        line("FDN • EN KAI CARPENTER", 0.06, 0.958),
        line("™ & © 2024 Wizards of the Coast", 0.59, 0.958),
    ])
    assert (card.name, card.collector_number, card.set_code, card.language) == ("Giada, Font of Hope", "141", "fdn", "en")
    assert card.artist == "Kai Carpenter"


def test_reader_2015_frame_and_glued_ocr():
    card = read_card([line("117/331 U", 0.06, 0.94), line("2X2 • EN CHRISTOPHER MOELLER", 0.06, 0.958)])
    assert (card.collector_number, card.set_code) == ("117", "2x2")
    glued = read_card([line("M0002", 0.06, 0.94), line("WHO★ENDAVID AUDEN NASH", 0.06, 0.958)])
    assert (glued.collector_number, glued.set_code, glued.language) == ("2", "who", "en")


def test_reader_old_frames():
    m10 = read_card([line("™ & © 1993-2009 Wizards of the Coast LLC. 146/249", 0.08, 0.94, 0.7)])
    assert (m10.collector_number, m10.set_code, m10.year) == ("146", None, 2009)
    old = read_card([line("Illus. Kaja Foglio", 0.08, 0.91), line("© 1995 Wizards of the Coast, Inc.", 0.08, 0.94, 0.6)])
    assert (old.collector_number, old.artist, old.year) == (None, "Kaja Foglio", 1995)


def test_reader_ignores_power_toughness_and_rules_text():
    card = read_card([
        line("token. (Artifacts, legendaries, and Sagas", 0.08, 0.86, 0.8),
        line("4/4", 0.82, 0.92, 0.08),
        line("M 0002", 0.06, 0.94),
    ])
    assert card.collector_number == "2" and card.set_code is None


def test_reader_fixes_ocr_lookalikes():
    assert read_card([line("R O14l", 0.06, 0.94)]).collector_number == "141"
    assert read_card([line("61a/303 R", 0.06, 0.94)]).collector_number == "61a"


def test_set_code_lookalikes():
    assert set(_lookalikes("M1O")) >= {"M1O", "M10", "MIO", "MI0"}


# --- detection ------------------------------------------------------------------------


def test_detects_cards_in_synthetic_photos():
    rng = np.random.default_rng(11)
    good = 0
    for i in range(20):
        photo = synth_photo(card_image(MANIFEST[i % len(MANIFEST)]), rng)
        quads = find_cards(photo.image)
        if quads:
            height = np.linalg.norm(photo.corners[0] - photo.corners[3])
            error = min(np.max(np.linalg.norm(quads[0].corners - photo.corners[order], axis=1))
                        for order in ([0, 1, 2, 3], [2, 3, 0, 1])) / height
            good += error < 0.04
    assert good >= 16, good


def test_cropped_scan_is_recognized_by_its_shape():
    assert is_cropped_card(np.zeros((936, 672, 3), np.uint8))
    assert not is_cropped_card(np.zeros((4032, 3024, 3), np.uint8))  # phone photo 3:4


# --- matching and the whole pipeline -------------------------------------------------


@pytest.fixture(scope="module")
def matcher(card_db_template):
    conn = connect(card_db_template)
    yield Matcher(conn)
    conn.close()


def load_fixture_image(card_id: str):
    path = CARDS / f"{card_id}.jpg"
    return cv2.imread(str(path)) if path.is_file() else None


def test_match_by_set_and_number(matcher):
    from mtgdm.scan.reader import CardText

    giada = by_key("fdn", "141")
    top = matcher.match(CardText(name="Giada, Font of Hope", collector_number="141", set_code="fdn"))[0]
    assert top.card_id == giada["id"] and top.score >= 0.98
    # Misread set code (0 for O) still finds the printing; a wrong name lowers confidence.
    assert matcher.match(CardText(collector_number="33", set_code="d0m"))[0].name == "Serra Angel"
    # Number says Giada, name says Lightning Bolt: the conflicting printing loses its top spot.
    conflict = matcher.match(CardText(name="Lightning Bolt", collector_number="141", set_code="fdn"))
    assert conflict[0].name == "Lightning Bolt"
    assert all(c.score < 0.5 for c in conflict if c.card_id == giada["id"])


def test_match_by_fuzzy_name(matcher):
    from mtgdm.scan.reader import CardText

    found = matcher.match(CardText(name="S words to Dlowshares"))
    assert found and found[0].name == "Swords to Plowshares"
    assert matcher.match(CardText(name="xq")) == []


ENGINES = [e for e in ("rapidocr", "apple_vision") if e in available_engines()]


@pytest.mark.parametrize("engine_name", ENGINES)
def test_pipeline_on_synthetic_photos(matcher, engine_name):
    engine = get_engine(engine_name)
    rng = np.random.default_rng(23)
    cases = [by_key(*k) for k in (("fdn", "141"), ("2x2", "117"), ("who", "2"), ("dom", "33"), ("cmm", "410"), ("ice", "54"))]
    names = printings = 0
    for entry in cases:
        photo = synth_photo(card_image(entry), rng, upside_down=entry["set"] == "who")
        result = scan_image(photo.image, matcher, engine, load_image=load_fixture_image)[0]
        top = result.candidates[0]
        names += top.name == entry["name"]
        printings += top.card_id == entry["id"]
    assert names == len(cases)
    assert printings >= len(cases) - 1


@pytest.mark.parametrize("background", ["white", "black"])
def test_detects_cards_on_pages(background):
    from mtgdm.scan.synth import synth_page

    images = [card_image(c) for c in MANIFEST]
    rng = np.random.default_rng(17)
    total = found = extra = 0
    for _ in range(4):
        page = synth_page(images, rng, background=background, fill=0.85, white_border=background == "black")
        quads = find_cards(page.image, max_cards=9)
        unused = list(range(len(quads)))
        for _, truth in page.cards:
            total += 1
            width = np.linalg.norm(truth[0] - truth[1])
            near = [i for i in unused if np.linalg.norm(quads[i].corners.mean(axis=0) - truth.mean(axis=0)) < 0.4 * width]
            if near:
                found += 1
                unused.remove(near[0])
        extra += len(unused)
    assert found >= 0.8 * total, (found, total)  # ~93% on a larger sample (scripts/scan_benchmark.py --pages)
    assert extra <= 1


def test_grid_finds_whole_cards_in_binder_photo():
    """Photo of a binder page (black sleeves): per cell, an art box or text frame must never be
    taken for the card, and every quad stays in its cell with card proportions."""
    from mtgdm.scan.pipeline import grid_quads

    image = cv2.imread(str(Path(__file__).parent / "fixtures" / "scans" / "binder-page.jpg"))
    h, w = image.shape[:2]
    quads = grid_quads(image, 3, 3)
    assert len(quads) == 9
    for index, quad in enumerate(quads):
        row, col = divmod(index, 3)
        cx, cy = quad.mean(axis=0)
        assert col * w / 3 <= cx <= (col + 1) * w / 3 and row * h / 3 <= cy <= (row + 1) * h / 3
        width = (np.linalg.norm(quad[0] - quad[1]) + np.linalg.norm(quad[3] - quad[2])) / 2
        height = (np.linalg.norm(quad[0] - quad[3]) + np.linalg.norm(quad[1] - quad[2])) / 2
        assert abs(height / width - 88 / 63) < 0.15, (index, width, height)
        assert width * height > 0.45 * (w / 3) * (h / 3), index  # binder sleeves: the card fills its cell


def test_grid_cell_fallback_is_card_shaped():
    from mtgdm.scan.pipeline import _fit_card, _is_whole_card

    art_box = np.array([[40, 30], [250, 30], [250, 190], [40, 190]], np.float32)  # landscape, small
    assert not _is_whole_card(art_box, (370, 280))
    card = np.array([[10, 8], [245, 8], [245, 335], [10, 335]], np.float32)
    assert _is_whole_card(card, (370, 280))
    small_card = np.array([[80, 90], [200, 90], [200, 258], [80, 258]], np.float32)  # big scanner cell
    assert _is_whole_card(small_card, (370, 280))
    assert not _is_whole_card(small_card / 3, (370, 280))  # tiny: a symbol or noise
    trapezoid = np.array([[10, 8], [245, 30], [270, 300], [0, 360]], np.float32)
    assert not _is_whole_card(trapezoid, (370, 280))
    fitted = _fit_card((370, 280))
    assert _is_whole_card(fitted, (370, 280))


def test_page_with_dark_cards_on_dark_background():
    """Scanner page with the lid open (black background), sleeves, and two black-bordered dark
    cards that fall apart in the foreground mask: whole cards are found, missing grid crossings
    are filled, nothing is cut in halves or thirds."""
    from mtgdm.scan.pipeline import locate_cards

    image = cv2.imread(str(Path(__file__).parent / "fixtures" / "scans" / "binder-page-scan.jpg"))
    h, w = image.shape[:2]
    quads = locate_cards(image, "auto")
    cells = sorted((int(q.corners.mean(axis=0)[1] * 3 / h), int(q.corners.mean(axis=0)[0] * 3 / w)) for q in quads)
    assert cells == [(r, c) for r in range(3) for c in range(3)]
    for q in quads:
        box_w = q.corners[:, 0].max() - q.corners[:, 0].min()
        box_h = q.corners[:, 1].max() - q.corners[:, 1].min()
        assert box_h > box_w and box_w > 0.2 * w  # upright, whole cards
