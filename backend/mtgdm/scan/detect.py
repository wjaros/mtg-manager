"""Finding cards in a photo or scan and straightening them."""

from dataclasses import dataclass

import cv2
import numpy as np

CARD_RATIO = 88 / 63           # height / width of a Magic card
RATIO_TOLERANCE = 0.14         # relative; perspective and rounded corners skew the measured ratio
WORK_SIZE = 1000               # detection runs on a downscaled copy (long side, px)
MIN_AREA = 0.015               # of the image, so a 3x3 page still qualifies
MIN_SCORE = 0.55               # shape fit (ratio + fill) a candidate needs
PAGE_SEPARATION = 0.006        # erosion separating cards a few mm apart on a page (of the long side)
WARP_SIZE = (744, 1040)        # straightened card (width, height): Scryfall "png" resolution


@dataclass
class Quad:
    corners: np.ndarray   # 4x2 float32: tl, tr, br, bl in original image coordinates
    score: float          # higher is better (fit to the card shape)

    @property
    def area(self) -> float:
        return float(cv2.contourArea(self.corners.astype(np.float32)))


def order_corners(pts: np.ndarray) -> np.ndarray:
    """tl, tr, br, bl; for a landscape quad the long side becomes vertical (portrait card)."""
    pts = pts.astype(np.float32).reshape(4, 2)
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    ordered = np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)
    if len({tuple(p) for p in ordered.tolist()}) < 4:  # degenerate ordering (45° rotation): sort by angle
        center = pts.mean(axis=0)
        angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
        ordered = pts[np.argsort(angles)]
        ordered = np.roll(ordered, -int(np.argmin(ordered.sum(axis=1))), axis=0)
    width = (np.linalg.norm(ordered[0] - ordered[1]) + np.linalg.norm(ordered[3] - ordered[2])) / 2
    height = (np.linalg.norm(ordered[0] - ordered[3]) + np.linalg.norm(ordered[1] - ordered[2])) / 2
    if width > height:
        ordered = np.roll(ordered, -1, axis=0)  # rotate the labels so the long side is vertical
    return ordered


def _shape_score(quad: np.ndarray, contour_area: float) -> float | None:
    width = (np.linalg.norm(quad[0] - quad[1]) + np.linalg.norm(quad[3] - quad[2])) / 2
    height = (np.linalg.norm(quad[0] - quad[3]) + np.linalg.norm(quad[1] - quad[2])) / 2
    if min(width, height) < 1:
        return None
    ratio_error = abs(max(width, height) / min(width, height) - CARD_RATIO) / CARD_RATIO
    if ratio_error > RATIO_TOLERANCE:
        return None
    quad_area = cv2.contourArea(quad)
    fill = contour_area / quad_area if quad_area else 0
    if fill < 0.8:
        return None
    return (1 - ratio_error / RATIO_TOLERANCE) * 0.6 + fill * 0.4


def _edge_maps(gray: np.ndarray) -> list[np.ndarray]:
    """Several binarizations: whichever separates card from background best wins."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    median = float(np.median(blurred))
    edges = cv2.Canny(blurred, int(max(0, 0.66 * median)), int(min(255, 1.33 * median)))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    maps = [cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)]
    _, otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    for binary in (otsu, 255 - otsu):
        maps.append(cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=2))
    # Strong local edges only (fine for low-contrast backgrounds).
    grad = cv2.morphologyEx(blurred, cv2.MORPH_GRADIENT, kernel)
    _, grad_bin = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    maps.append(cv2.morphologyEx(grad_bin, cv2.MORPH_CLOSE, kernel, iterations=2))
    return maps


def _page_foreground(gray: np.ndarray) -> np.ndarray:
    """Cards white, background black, judged by the page margin (bright lid or dark open lid)."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    margin = np.concatenate([blurred[:8].ravel(), blurred[-8:].ravel(), blurred[:, :8].ravel(), blurred[:, -8:].ravel()])
    background = float(np.median(margin))
    # Distance from the background brightness separates cards whatever their border colour.
    distance = cv2.absdiff(blurred, np.full_like(blurred, int(background)))
    _, mask = cv2.threshold(distance, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)   # fill thin gaps inside a card
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)   # cut hairline bridges between cards
    # Solid silhouettes: light card areas (frames, text boxes) look like the background and leave
    # holes, which erosion would turn into broken rings.
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    solid = np.zeros_like(mask)
    cv2.drawContours(solid, contours, -1, 255, thickness=cv2.FILLED)
    return solid


def find_cards(image: np.ndarray, max_cards: int = 1) -> list[Quad]:
    """Card-shaped quadrilaterals without overlaps: the best single card, or up to max_cards
    cards of a page in reading order."""
    h, w = image.shape[:2]
    scale = WORK_SIZE / max(h, w)
    small = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY) if small.ndim == 3 else small
    quads = _page_cards(gray, max_cards) if max_cards > 1 else _single_card(gray)
    return [Quad(corners=q.corners / scale, score=q.score) for q in quads]


def _candidate(contour: np.ndarray, gray: np.ndarray, grow: float = 0) -> tuple[np.ndarray, np.ndarray] | None:
    """(hull, refined quad) of a contour of plausible size, not touching the image border."""
    area = cv2.contourArea(contour)
    image_area = gray.shape[0] * gray.shape[1]
    if area < MIN_AREA * image_area or area > 0.98 * image_area:
        return None
    hull = cv2.convexHull(contour)
    approx = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
    pts = approx.reshape(-1, 2) if len(approx) == 4 else cv2.boxPoints(cv2.minAreaRect(hull))
    quad = _refine_corners(hull.reshape(-1, 2).astype(np.float32), order_corners(pts))
    if grow:
        quad = _grow(quad, grow)
    if _touches_border(quad, gray.shape):
        return None  # the frame of the photo itself, or a card cut off by it
    return hull, quad


def _single_card(gray: np.ndarray) -> list[Quad]:
    found: list[Quad] = []
    for binary in _edge_maps(gray):
        contours, _ = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        for contour in contours:
            if (cand := _candidate(contour, gray)) is None:
                continue
            hull, quad = cand
            score = _shape_score(quad, cv2.contourArea(hull))
            if score is not None and score >= MIN_SCORE:
                found.append(Quad(corners=quad, score=score))
    # Largest card-shaped outline wins. Erring large is deliberate: a soft shadow around the card
    # only adds margin, while picking the inner frame would cut off the collector line at the
    # bottom. Smaller card-shaped parts inside (the halves of a split card) are ignored.
    return sorted(found, key=lambda q: q.area, reverse=True)[:1]


def _page_cards(gray: np.ndarray, max_cards: int) -> list[Quad]:
    """A page: plain background (scanner lid or open lid) and cards as solid silhouettes. Cards a
    few millimetres apart touch in the mask: erode until they separate, then grow each outline
    back. Blobs of 2-3 cards that really touch are cut into equal parts."""
    shrink = max(2, round(PAGE_SEPARATION * max(gray.shape)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * shrink + 1, 2 * shrink + 1))
    mask = cv2.erode(_page_foreground(gray), kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

    shaped: list[Quad] = []
    # (hull, area, long side, short side, upright) after growing back
    outlines: list[tuple[np.ndarray, float, float, float, bool]] = []
    for contour in contours:
        if (cand := _candidate(contour, gray, grow=shrink)) is None:
            continue
        hull, quad = cand
        grown_area = cv2.contourArea(hull) + shrink * cv2.arcLength(hull, True)
        (_, _), (side_a, side_b), _ = cv2.minAreaRect(hull)
        _, _, box_w, box_h = cv2.boundingRect(hull)
        outlines.append((hull, grown_area, max(side_a, side_b) + 2 * shrink, min(side_a, side_b) + 2 * shrink,
                         box_h > box_w))
        score = _shape_score(quad, grown_area)
        if score is not None and score >= MIN_SCORE:
            shaped.append(Quad(corners=quad, score=score))

    typical = _card_area([(area, long, short, upright) for _, area, long, short, upright in outlines])
    singles: list[Quad] = []
    if typical:
        singles = [q for q in shaped if abs(q.area / typical - 1) <= 0.15]
        # Two or three touching cards make one outline of 2-3 card areas (a pair even looks like a
        # landscape card): cut it into cards.
        for hull, grown_area, long, short, _ in outlines:
            parts = round(grown_area / typical)
            if parts in (2, 3) and abs(grown_area / (parts * typical) - 1) <= 0.15 and _cards_side_by_side(long, short, parts):
                singles += _split(hull, parts, shrink)

    accepted: list[Quad] = []
    for quad in sorted(singles, key=lambda q: q.score, reverse=True):
        if any(_overlap(quad, other) > 0.3 for other in accepted):
            continue
        accepted.append(quad)
        if len(accepted) == max_cards:
            break
    accepted.sort(key=_reading_order(accepted))
    return accepted


def _split(hull: np.ndarray, parts: int, grow: float) -> list[Quad]:
    """Cut the bounding rectangle of `parts` touching cards into equal cards along its long side."""
    box = order_corners(cv2.boxPoints(cv2.minAreaRect(hull)))  # long side is tl -> bl
    tl, tr, br, bl = box
    pieces = []
    for i in range(parts):
        a, b = i / parts, (i + 1) / parts
        piece = np.array([tl + (bl - tl) * a, tr + (br - tr) * a, tr + (br - tr) * b, tl + (bl - tl) * b], np.float32)
        piece = _grow(order_corners(piece), grow)
        pieces.append(Quad(corners=piece, score=MIN_SCORE))  # lowest confidence: a guess
    return pieces


def _grow(quad: np.ndarray, amount: float) -> np.ndarray:
    """Move every side of a quad outward by `amount` pixels (undo an erosion)."""
    width = (np.linalg.norm(quad[0] - quad[1]) + np.linalg.norm(quad[3] - quad[2])) / 2
    height = (np.linalg.norm(quad[0] - quad[3]) + np.linalg.norm(quad[1] - quad[2])) / 2
    x_axis = ((quad[1] - quad[0]) + (quad[2] - quad[3])) / 2
    y_axis = ((quad[3] - quad[0]) + (quad[2] - quad[1])) / 2
    x_axis /= np.linalg.norm(x_axis) or 1
    y_axis /= np.linalg.norm(y_axis) or 1
    sx = np.array([-1, 1, 1, -1], np.float32)[:, None]
    sy = np.array([-1, -1, 1, 1], np.float32)[:, None]
    grown = quad + sx * x_axis * amount + sy * y_axis * amount
    # Keep the quad's own shape (perspective) while growing it.
    return grown.astype(np.float32) if width > 2 * amount and height > 2 * amount else quad


def _cards_side_by_side(long: float, short: float, parts: int) -> bool:
    """An outline of `parts` touching cards in a row: cut along the long side, every piece is card
    shaped. (A single card cut in three would give landscape slivers.)"""
    piece_a, piece_b = long / parts, short
    ratio = max(piece_a, piece_b) / max(1e-6, min(piece_a, piece_b))
    return abs(ratio - CARD_RATIO) / CARD_RATIO <= 0.15


def _card_area(outlines: list[tuple[float, float, float, bool]]) -> float | None:
    """The size of one card on a page. Outlines are (area, long side, short side, upright): single
    cards, or 2-3 touching cards side by side. The size that explains the most upright outlines as
    single cards wins (then the most cards in total, then the smaller size). Upright, because
    cards on a page stand upright while a pair of cards, and the halves dark cards fall apart
    into, lie landscape with nearly a card's proportions."""
    best, best_key = None, (0, 0)
    for candidate in sorted(area for area, _, _, _ in outlines):
        singles = cards = 0
        for area, long, short, upright in outlines:
            parts = round(area / candidate)
            if parts in (1, 2, 3) and abs(area / (parts * candidate) - 1) <= 0.15 and (
                    parts == 1 or _cards_side_by_side(long, short, parts)):
                cards += parts
                singles += parts == 1 and upright
        if (singles, cards) > best_key:
            best, best_key = candidate, (singles, cards)
    return best


def _reading_order(quads: list[Quad]):
    """Rows top to bottom, then left to right (rows grouped by card height)."""
    heights = [np.linalg.norm(q.corners[0] - q.corners[3]) for q in quads] or [1.0]
    row_height = float(np.median(heights))

    # Group into rows: a card starts a new row when its center is clearly below the row's first card.
    rows: dict[int, int] = {}
    row, row_top = -1, None
    for q in sorted(quads, key=lambda q: q.corners.mean(axis=0)[1]):
        cy = q.corners.mean(axis=0)[1]
        if row_top is None or cy - row_top > 0.5 * row_height:
            row, row_top = row + 1, cy
        rows[id(q)] = row

    def key(q: Quad) -> tuple[int, float]:
        return rows[id(q)], float(q.corners.mean(axis=0)[0])

    return key


def _refine_corners(points: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Fit a straight line to each side of the outline and intersect neighbours: the real card
    corners are rounded, so polygon vertices sit inside the corners the card's edges point to."""
    lines = []
    for i in range(4):
        a, b = quad[i], quad[(i + 1) % 4]
        side = b - a
        length = float(np.linalg.norm(side))
        if length < 1:
            return quad
        normal = np.array([-side[1], side[0]]) / length
        t = (points - a) @ side / (length * length)       # position along the side (0..1)
        dist = np.abs((points - a) @ normal)              # distance from the side
        # Middle 70% of the side only: away from the rounded corners.
        near = points[(t > 0.15) & (t < 0.85) & (dist < 0.04 * length)]
        if len(near) < 2:
            # CHAIN_APPROX_SIMPLE keeps few points on straight runs: sample the side instead.
            near = np.array([a + side * f for f in (0.2, 0.5, 0.8)], np.float32)
        vx, vy, x0, y0 = cv2.fitLine(near.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
        lines.append((np.array([x0, y0]), np.array([vx, vy])))
    corners = []
    for i in range(4):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        m = np.array([d1, -d2]).T
        if abs(np.linalg.det(m)) < 1e-6:
            return quad
        t1, _ = np.linalg.solve(m, p2 - p1)
        corners.append(p1 + t1 * d1)
    refined = np.array(corners, np.float32)
    # Guard against a bad fit: stay close to the polygon.
    if np.max(np.linalg.norm(refined - quad, axis=1)) > 0.1 * np.linalg.norm(quad[0] - quad[2]):
        return quad
    return refined


def _touches_border(quad: np.ndarray, shape: tuple[int, ...], margin: float = 0.005) -> bool:
    h, w = shape[:2]
    m = margin * max(h, w)
    return bool(np.any(quad[:, 0] < m) or np.any(quad[:, 0] > w - 1 - m)
                or np.any(quad[:, 1] < m) or np.any(quad[:, 1] > h - 1 - m))


def _overlap(a: Quad, b: Quad) -> float:
    """Intersection over the smaller area."""
    inter, _ = cv2.intersectConvexConvex(a.corners.astype(np.float32), b.corners.astype(np.float32))
    return float(inter) / max(1.0, min(a.area, b.area))


def warp(image: np.ndarray, corners: np.ndarray, size: tuple[int, int] = WARP_SIZE) -> np.ndarray:
    """Straightened card (perspective removed) at a fixed resolution."""
    w, h = size
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32)
    m = cv2.getPerspectiveTransform(corners.astype(np.float32), dst)
    return cv2.warpPerspective(image, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def whole_image_quad(image: np.ndarray) -> Quad:
    """Fallback for a single card filling the frame (already cropped scan)."""
    h, w = image.shape[:2]
    return Quad(np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32), score=0.0)
