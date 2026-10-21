"""Photo -> recognized cards: detect, straighten, OCR (both orientations if needed),
match text, re-rank by image."""

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

from mtgdm.scan.detect import CARD_RATIO, Quad, _reading_order, find_cards, warp, whole_image_quad
from mtgdm.scan.match import Candidate, ImageLoader, Matcher
from mtgdm.scan.ocr.base import OcrEngine
from mtgdm.scan.reader import CardText, read_card

GOOD_ENOUGH = 0.9  # text match this strong: no need to try the card upside down


@dataclass
class ScannedCard:
    corners: np.ndarray          # 4x2 in the original image (tl, tr, br, bl of the card as read)
    image: np.ndarray            # straightened card, upright
    text: CardText
    candidates: list[Candidate]
    upside_down: bool

    @property
    def confidence(self) -> float:
        return self.candidates[0].score if self.candidates else 0.0


Kind = Literal["auto", "single", "page"]
PAGE_MAX_CARDS = 9


def scan_image(image: np.ndarray, matcher: Matcher, engine: OcrEngine, *,
               load_image: ImageLoader | None = None, kind: Kind = "auto",
               max_cards: int | None = None) -> list[ScannedCard]:
    """Recognize the card(s) in an image. auto: a page when at least two cards are found."""
    quads = locate_cards(image, kind, max_cards)
    return [_scan_card(image, quad.corners, matcher, engine, load_image) for quad in quads]


def locate_cards(image: np.ndarray, kind: Kind = "auto", max_cards: int | None = None) -> list[Quad]:
    if kind == "single" or max_cards == 1:
        if is_cropped_card(image):
            return [whole_image_quad(image)]  # a scan already cropped to the card
        return find_cards(image, max_cards=1) or [whole_image_quad(image)]
    limit = max_cards or PAGE_MAX_CARDS
    page = find_cards(image, max_cards=limit)
    if kind == "page" or len(page) >= 2:
        return _fill_grid_gaps(image, page, limit)
    return locate_cards(image, "single")


def _fill_grid_gaps(image: np.ndarray, quads: list[Quad], limit: int) -> list[Quad]:
    """Cards a page detection missed (dark cards on a dark background, a card touching the image
    edge): the found cards define the grid's columns and rows, and every empty-handed crossing
    that isn't blank is searched like a manual grid cell."""
    if len(quads) < 3 or len(quads) >= limit:
        return quads
    boxes = [(q.corners[:, 0].min(), q.corners[:, 1].min(), q.corners[:, 0].max(), q.corners[:, 1].max())
             for q in quads]
    width = float(np.median([b[2] - b[0] for b in boxes]))
    height = float(np.median([b[3] - b[1] for b in boxes]))
    h, w = image.shape[:2]
    columns = _extend(_bands([((b[0] + b[2]) / 2, b[0], b[2]) for b in boxes], width), w)
    rows = _extend(_bands([((b[1] + b[3]) / 2, b[1], b[3]) for b in boxes], height), h)
    if len(columns) < 2 and len(rows) < 2:
        return quads
    # How much detail a card shows (text, art edges), measured on the cards that were found: an
    # empty pocket or background shows much less.
    card_detail = float(np.median([_detail(image[int(b[1]):int(b[3]), int(b[0]):int(b[2])]) for b in boxes]))
    filled = list(quads)
    for top, bottom in rows:
        for left, right in columns:
            if len(filled) >= limit:
                break
            if any(left <= (b[0] + b[2]) / 2 <= right and top <= (b[1] + b[3]) / 2 <= bottom for b in boxes):
                continue
            # The crossing, widened a little: the missing card may sit slightly off its neighbours.
            x0, x1 = max(0, int(left - 0.08 * width)), min(w, int(right + 0.08 * width))
            y0, y1 = max(0, int(top - 0.08 * height)), min(h, int(bottom + 0.08 * height))
            cell = image[y0:y1, x0:x1]
            if cell.size == 0 or _looks_empty(cell):
                continue
            corners = _detect_in_cell(cell)
            # Same size as the cards around it, or it is something else (a sleeve edge, a fragment).
            if corners is not None and abs(cv2.contourArea(corners) / (width * height) - 1) <= 0.25:
                filled.append(Quad(corners=corners + np.array([x0, y0], np.float32), score=0.5))
            elif _detail(image[int(max(0, top)):int(bottom), int(max(0, left)):int(right)]) >= 0.4 * card_detail:
                # A card whose outline can't be told from the background (black card, black sleeve,
                # dark background): the crossing itself is the card.
                filled.append(Quad(corners=np.array(
                    [[left, top], [right, top], [right, bottom], [left, bottom]], np.float32).clip(0, [w, h]),
                    score=0.4))
    filled.sort(key=_reading_order(filled))
    return filled


def _detail(region: np.ndarray) -> float:
    """Share of edge pixels at a fixed scale (text and art have many, an empty pocket few)."""
    if region.size == 0:
        return 0.0
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY) if region.ndim == 3 else region
    small = cv2.resize(gray, (150, 210), interpolation=cv2.INTER_AREA)
    return float(np.count_nonzero(cv2.Canny(cv2.GaussianBlur(small, (3, 3), 0), 60, 150))) / small.size


def _extend(bands: list[tuple[float, float]], limit: float) -> list[tuple[float, float]]:
    """Regularly spaced columns (or rows) continue while another one fits in the image: a column
    whose cards were all missed (e.g. dark cards) has no card to define it."""
    if len(bands) < 2:
        return bands
    pitch = float(np.median(np.diff([start for start, _ in bands])))
    size = float(np.median([end - start for start, end in bands]))
    if pitch < size:  # overlapping bands: not a grid
        return bands
    extended = list(bands)
    while extended[0][0] - pitch >= -0.1 * size:
        extended.insert(0, (extended[0][0] - pitch, extended[0][0] - pitch + size))
    while extended[-1][0] + pitch + size <= limit + 0.1 * size:
        extended.append((extended[-1][0] + pitch, extended[-1][0] + pitch + size))
    return extended


def _bands(spans: list[tuple[float, float, float]], size: float) -> list[tuple[float, float]]:
    """Group (center, start, end) spans whose centers are within half a card: one column or row each."""
    bands: list[list[tuple[float, float, float]]] = []
    for span in sorted(spans):
        if bands and span[0] - bands[-1][-1][0] < 0.5 * size:
            bands[-1].append(span)
        else:
            bands.append([span])
    return [(float(np.median([s[1] for s in band])), float(np.median([s[2] for s in band]))) for band in bands]


def scan_grid(image: np.ndarray, matcher: Matcher, engine: OcrEngine, rows: int, cols: int, *,
              region: tuple[float, float, float, float] | None = None,
              load_image: ImageLoader | None = None) -> list[ScannedCard]:
    """Fallback when detection fails: split a region (relative x0, y0, x1, y1; default: the
    whole image) into rows x cols cells with one card each. Empty cells are skipped."""
    return [_scan_card(image, corners, matcher, engine, load_image) for corners in grid_quads(image, rows, cols, region)]


def grid_quads(image: np.ndarray, rows: int, cols: int,
               region: tuple[float, float, float, float] | None = None) -> list[np.ndarray]:
    """Card corners per non-empty cell, in image coordinates, in reading order."""
    h, w = image.shape[:2]
    x0, y0, x1, y1 = region or (0.0, 0.0, 1.0, 1.0)
    cell_w, cell_h = (x1 - x0) * w / cols, (y1 - y0) * h / rows
    quads = []
    for r in range(rows):
        for c in range(cols):
            left, top = x0 * w + c * cell_w, y0 * h + r * cell_h
            cell = image[int(top):int(top + cell_h), int(left):int(left + cell_w)]
            if cell.size == 0 or _looks_empty(cell):
                continue
            corners = _detect_in_cell(cell)
            if corners is None:
                corners = _fit_card(cell.shape)  # the user said there is a card in every cell
            quads.append(corners + np.array([int(left), int(top)], np.float32))
    return quads


def _detect_in_cell(cell: np.ndarray) -> np.ndarray | None:
    """The card outline in a cell, if one that looks like the whole card is found (an art box or
    text frame is not). A manual grid falls back to a card-shaped rectangle (the user said there
    is a card); filling gaps after page detection does not (the slot may be empty)."""
    found = find_cards(cell, max_cards=1)
    if found and _is_whole_card(found[0].corners, cell.shape):
        return found[0].corners
    # A card touching the cell edge (sleeves, a tight grid) is rejected by detection, which skips
    # outlines on the image border: try again with the cell padded in its background colour.
    pad = max(8, round(0.04 * max(cell.shape[:2])))
    edge = np.concatenate([cell[0], cell[-1], cell[:, 0], cell[:, -1]])
    background = [int(v) for v in np.median(edge.reshape(-1, cell.shape[2] if cell.ndim == 3 else 1), axis=0)]
    padded = cv2.copyMakeBorder(cell, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=background)
    found = find_cards(padded, max_cards=1)
    if found:
        corners = found[0].corners - np.array([pad, pad], np.float32)
        if _is_whole_card(corners, cell.shape):
            return corners
    return None


def _is_whole_card(corners: np.ndarray, shape: tuple[int, ...]) -> bool:
    h, w = shape[:2]
    slack = 0.05 * max(h, w)
    if (corners[:, 0].min() < -slack or corners[:, 1].min() < -slack
            or corners[:, 0].max() > w + slack or corners[:, 1].max() > h + slack):
        return False
    # Extents, not side lengths: the corner order from detection does not say which side is the top.
    width = float(corners[:, 0].max() - corners[:, 0].min())
    height = float(corners[:, 1].max() - corners[:, 1].min())
    # Cards in a grid are upright; art boxes and text frames are landscape.
    upright = width > 0 and abs(height / width - CARD_RATIO) / CARD_RATIO <= 0.12
    # Scanner cells can be much bigger than the card, so compare with the largest card that fits.
    fitted = _fit_card(shape)
    big_enough = cv2.contourArea(corners.astype(np.float32)) >= 0.2 * cv2.contourArea(fitted)
    return bool(upright and big_enough and _is_rectangle(corners))


def _is_rectangle(corners: np.ndarray, tolerance: float = 0.08) -> bool:
    """Opposite sides of similar length and equal diagonals: a card seen from above, not a
    trapezoid spanning a sleeve and the neighbouring card."""
    sides = [float(np.linalg.norm(corners[i] - corners[(i + 1) % 4])) for i in range(4)]
    diagonals = [float(np.linalg.norm(corners[0] - corners[2])), float(np.linalg.norm(corners[1] - corners[3]))]

    def close(a: float, b: float) -> bool:
        return abs(a - b) <= tolerance * max(a, b)

    return close(sides[0], sides[2]) and close(sides[1], sides[3]) and close(*diagonals)


def _fit_card(shape: tuple[int, ...], margin: float = 0.02) -> np.ndarray:
    """The largest upright card-shaped rectangle centred in the cell."""
    h, w = shape[:2]
    avail_w, avail_h = w * (1 - 2 * margin), h * (1 - 2 * margin)
    card_w = min(avail_w, avail_h / CARD_RATIO)
    card_h = card_w * CARD_RATIO
    x, y = (w - card_w) / 2, (h - card_h) / 2
    return np.array([[x, y], [x + card_w, y], [x + card_w, y + card_h], [x, y + card_h]], np.float32)


def _looks_empty(cell: np.ndarray) -> bool:
    """A plain cell (just background) has almost no texture."""
    gray = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY) if cell.ndim == 3 else cell
    small = cv2.resize(gray, (64, 64), interpolation=cv2.INTER_AREA)
    return float(small.std()) < 8.0


def is_cropped_card(image: np.ndarray, tolerance: float = 0.03) -> bool:
    """The whole image has the card's proportions (portrait or landscape). Phone photos (3:4) are
    4.6% off and do not count."""
    h, w = image.shape[:2]
    ratio = max(h, w) / min(h, w)
    return abs(ratio - CARD_RATIO) / CARD_RATIO <= tolerance


def _scan_card(image: np.ndarray, corners: np.ndarray, matcher: Matcher, engine: OcrEngine,
               load_image: ImageLoader | None) -> ScannedCard:
    straight = warp(image, corners)
    best: tuple[float, bool, np.ndarray, CardText] | None = None
    for upside_down in (False, True):
        card = cv2.rotate(straight, cv2.ROTATE_180) if upside_down else straight
        text = read_card(engine.recognize(card))
        candidates = matcher.match(text)
        quality = candidates[0].score if candidates else 0.0
        if best is None or quality > best[0]:
            best = (quality, upside_down, card, text)
        if quality >= GOOD_ENOUGH:
            break

    _, upside_down, card, text = best
    candidates = matcher.match(text, card, load_image)
    if upside_down:
        corners = corners[[2, 3, 0, 1]]
    return ScannedCard(corners=corners, image=card, text=text, candidates=candidates, upside_down=upside_down)
