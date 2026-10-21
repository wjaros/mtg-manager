"""Synthetic card photos for tests and accuracy benchmarks: a real card image placed on a random
background with rotation, perspective, lighting, blur, noise, glare and JPEG compression. The
ground truth (which card, where its corners are) is known exactly."""

from dataclasses import dataclass

import cv2
import numpy as np

CARD_RATIO = 88 / 63  # height / width


@dataclass
class SynthPhoto:
    image: np.ndarray       # BGR
    corners: np.ndarray     # 4x2 float32, card corners tl, tr, br, bl in image coordinates
    upside_down: bool


def rounded_card(card: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Card image and an alpha mask with the real card's rounded corners."""
    h, w = card.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    r = int(w * 0.045)
    cv2.rectangle(mask, (r, 0), (w - r, h), 255, -1)
    cv2.rectangle(mask, (0, r), (w, h - r), 255, -1)
    for cx, cy in ((r, r), (w - r - 1, r), (r, h - r - 1), (w - r - 1, h - r - 1)):
        cv2.circle(mask, (cx, cy), r, 255, -1)
    return card, mask


def background(rng: np.random.Generator, width: int, height: int) -> np.ndarray:
    """Plain, gradient or textured table-like surface, dark or light."""
    base = rng.integers(10, 245, size=3).astype(np.float32)
    img = np.ones((height, width, 3), np.float32) * base
    kind = rng.integers(0, 3)
    if kind == 1:  # gradient
        ramp = np.linspace(-1, 1, width, dtype=np.float32)[None, :, None]
        img += ramp * rng.uniform(10, 50)
    elif kind == 2:  # texture (wood / fabric like)
        noise = rng.normal(0, 1, (height // 8 + 1, width // 8 + 1)).astype(np.float32)
        noise = cv2.resize(noise, (width, height), interpolation=cv2.INTER_CUBIC)
        img += noise[:, :, None] * rng.uniform(8, 25)
    return np.clip(img, 0, 255).astype(np.uint8)


def synth_photo(card_bgr: np.ndarray, rng: np.random.Generator, *, upside_down: bool | None = None,
                canvas: tuple[int, int] = (1600, 2000)) -> SynthPhoto:
    """One synthetic photo of a single card (canvas = width, height)."""
    width, height = canvas
    bg = background(rng, width, height)
    card, mask = rounded_card(card_bgr)
    if upside_down is None:
        upside_down = rng.random() < 0.15
    if upside_down:
        card, mask = cv2.rotate(card, cv2.ROTATE_180), cv2.rotate(mask, cv2.ROTATE_180)
    ch, cw = card.shape[:2]

    # Target quad: scaled, rotated and perspective-jittered rectangle, kept inside the canvas.
    card_h = rng.uniform(0.55, 0.85) * height
    card_w = card_h / CARD_RATIO
    angle = np.deg2rad(rng.uniform(-14, 14))
    cx = width / 2 + rng.uniform(-0.08, 0.08) * width
    cy = height / 2 + rng.uniform(-0.06, 0.06) * height
    rect = np.array([[-card_w / 2, -card_h / 2], [card_w / 2, -card_h / 2],
                     [card_w / 2, card_h / 2], [-card_w / 2, card_h / 2]], np.float32)
    rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]], np.float32)
    quad = rect @ rot.T + np.array([cx, cy], np.float32)
    quad += rng.uniform(-0.035, 0.035, (4, 2)).astype(np.float32) * card_w  # perspective
    # Keep the whole card in the frame (a cut-off card is a different problem).
    margin = 0.03 * min(width, height)
    lo, hi = quad.min(axis=0), quad.max(axis=0)
    fit = min(1.0, (width - 2 * margin) / (hi[0] - lo[0]), (height - 2 * margin) / (hi[1] - lo[1]))
    center = (lo + hi) / 2
    quad = (quad - center) * fit + np.clip(center, [margin + (hi[0] - lo[0]) * fit / 2, margin + (hi[1] - lo[1]) * fit / 2],
                                            [width - margin - (hi[0] - lo[0]) * fit / 2, height - margin - (hi[1] - lo[1]) * fit / 2])
    quad = quad.astype(np.float32)

    src = np.array([[0, 0], [cw - 1, 0], [cw - 1, ch - 1], [0, ch - 1]], np.float32)
    m = cv2.getPerspectiveTransform(src, quad)
    warped = cv2.warpPerspective(card, m, (width, height), flags=cv2.INTER_LINEAR)
    alpha = cv2.warpPerspective(mask, m, (width, height), flags=cv2.INTER_LINEAR).astype(np.float32) / 255

    # Soft shadow under the card.
    shadow = cv2.GaussianBlur(alpha, (0, 0), 12) * rng.uniform(0.2, 0.5)
    img = bg.astype(np.float32) * (1 - shadow[:, :, None])
    img = img * (1 - alpha[:, :, None]) + warped.astype(np.float32) * alpha[:, :, None]

    # Lighting: brightness / contrast / color cast, vignette.
    img = img * rng.uniform(0.75, 1.15) + rng.uniform(-20, 20)
    img *= rng.uniform(0.92, 1.08, 3).astype(np.float32)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    vignette = 1 - 0.25 * (((xx - width / 2) / width) ** 2 + ((yy - height / 2) / height) ** 2) * rng.uniform(0, 2)
    img *= vignette[:, :, None]

    # Glare (sleeve / foil reflection) in a random spot.
    if rng.random() < 0.35:
        gx, gy = rng.uniform(0.2, 0.8) * width, rng.uniform(0.2, 0.8) * height
        blob = np.exp(-(((xx - gx) / (width * rng.uniform(0.05, 0.15))) ** 2 + ((yy - gy) / (height * 0.05)) ** 2))
        img += blob[:, :, None] * rng.uniform(40, 120)

    img = np.clip(img, 0, 255).astype(np.uint8)
    sigma = rng.uniform(0, 1.6)
    if sigma > 0.3:
        img = cv2.GaussianBlur(img, (0, 0), sigma)
    img = np.clip(img.astype(np.int16) + rng.normal(0, rng.uniform(1, 6), img.shape).astype(np.int16), 0, 255).astype(np.uint8)
    ok, jpeg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(60, 92))])
    img = cv2.imdecode(jpeg, cv2.IMREAD_COLOR)

    corners = quad if not upside_down else quad[[2, 3, 0, 1]]
    return SynthPhoto(image=img, corners=corners.astype(np.float32), upside_down=upside_down)


@dataclass
class SynthPage:
    image: np.ndarray                  # BGR
    cards: list[tuple[int, np.ndarray]]  # (index into the source card list, 4x2 corners), reading order


A4_300DPI = (2480, 3508)  # width, height
CARD_300DPI = (744, 1039)


def whiten_border(card: np.ndarray, width: float = 0.04) -> np.ndarray:
    """Imitate an old white-bordered printing (Revised, 4th Edition): paint the outer border white."""
    out = card.copy()
    h, w = out.shape[:2]
    b = int(w * width)
    out[:b], out[-b:], out[:, :b], out[:, -b:] = 235, 235, 235, 235
    return out


def synth_page(cards_bgr: list[np.ndarray], rng: np.random.Generator, *, background: str = "white",
               rows: int = 3, cols: int = 3, fill: float = 1.0, white_border: bool = False) -> SynthPage:
    """Flatbed scan of up to rows x cols cards on an A4 page: white (lid closed) or black (lid open)
    background, cards slightly shifted and skewed, flat light, scanner noise."""
    width, height = A4_300DPI
    if background == "white":
        base = rng.uniform(225, 250)
        page = np.full((height, width, 3), base, np.float32)
    else:
        page = np.full((height, width, 3), rng.uniform(5, 25), np.float32)
        # Open lid: a bit of room light falling in from one side.
        ramp = np.linspace(0, rng.uniform(0, 25), width, dtype=np.float32)[None, :, None]
        page += ramp
    page += rng.normal(0, 2, (height, width, 1)).astype(np.float32)

    cw, ch = CARD_300DPI
    gap_x = (width - cols * cw) / (cols + 1)
    gap_y = (height - rows * ch) / (rows + 1)
    placed: list[tuple[int, np.ndarray]] = []
    slot = 0
    for r in range(rows):
        for c in range(cols):
            if rng.random() > fill:
                slot += 1
                continue
            index = int(rng.integers(0, len(cards_bgr)))
            source = cv2.resize(cards_bgr[index], (cw, ch), interpolation=cv2.INTER_CUBIC)
            if white_border:
                source = whiten_border(source)
            card, mask = rounded_card(source)
            cx = gap_x + c * (cw + gap_x) + cw / 2 + rng.uniform(-0.35, 0.35) * gap_x
            cy = gap_y + r * (ch + gap_y) + ch / 2 + rng.uniform(-0.35, 0.35) * gap_y
            angle = np.deg2rad(rng.uniform(-3, 3))
            rect = np.array([[-cw / 2, -ch / 2], [cw / 2, -ch / 2], [cw / 2, ch / 2], [-cw / 2, ch / 2]], np.float32)
            rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]], np.float32)
            quad = (rect @ rot.T + np.array([cx, cy], np.float32)).astype(np.float32)
            src = np.array([[0, 0], [cw - 1, 0], [cw - 1, ch - 1], [0, ch - 1]], np.float32)
            m = cv2.getPerspectiveTransform(src, quad)
            warped = cv2.warpPerspective(card, m, (width, height)).astype(np.float32)
            alpha = cv2.warpPerspective(mask, m, (width, height)).astype(np.float32)[:, :, None] / 255
            page = page * (1 - alpha) + warped * alpha
            placed.append((index, quad))
            slot += 1

    page = np.clip(page * rng.uniform(0.95, 1.05) + rng.normal(0, 1.5, page.shape), 0, 255).astype(np.uint8)
    ok, jpeg = cv2.imencode(".jpg", page, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(80, 95))])
    return SynthPage(image=cv2.imdecode(jpeg, cv2.IMREAD_COLOR), cards=placed)
