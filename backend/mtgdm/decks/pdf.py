"""Deck as a PDF for browsing on a phone: one card per page, commanders and companion
first, then by mana value (cheapest first, then by name), lands last. Double-faced cards get a
page per face; sideboard and maybeboard are left out."""

import io
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from mtgdm.cards.search import card_summaries
from mtgdm.decks.service import get_deck

PAGE_WIDTH = 672                # Scryfall "large" image width
CARD_HEIGHT = 936
CAPTION_HEIGHT = 84
BACKGROUND = (15, 18, 24)
TEXT = (232, 234, 240)
DPI = 160                       # ~4.2 x 6.4 in pages: phone-sized
# Mana symbol circles (Scryfall's symbol colors); generic and other symbols are grey.
SYMBOL_COLORS = {"W": (248, 246, 216), "U": (193, 215, 233), "B": (186, 177, 171), "R": (228, 153, 119),
                 "G": (163, 192, 149)}
GENERIC = (204, 194, 192)
SYMBOL_SIZE = 34
_SYMBOL_RE = re.compile(r"\{([^}]+)\}")


@dataclass
class Page:
    card_id: str
    face: int
    quantity: int
    name: str
    mana_cost: str


def deck_pages(conn: sqlite3.Connection, deck_id: int) -> list[Page]:
    deck = get_deck(conn, deck_id)
    summaries = {c.id: c for c in card_summaries(conn, [e.card.id for e in deck.cards])}

    def is_land(entry) -> bool:
        return "Land" in (entry.card.type_line or "").split("//")[0]

    head = [e for e in deck.cards if e.board in ("commander", "companion")]
    head.sort(key=lambda e: e.board != "commander")  # commanders, then the companion
    main = [e for e in deck.cards if e.board == "main"]
    spells = sorted((e for e in main if not is_land(e)), key=lambda e: (e.card.cmc or 0, e.card.name))
    lands = sorted((e for e in main if is_land(e)), key=lambda e: e.card.name)

    pages = []
    for entry in head + spells + lands:
        faces = max(1, summaries[entry.card.id].image_faces) if entry.card.id in summaries else 1
        for face in range(faces):
            pages.append(Page(entry.card.id, face, entry.quantity, entry.card.name, entry.card.mana_cost or ""))
    return pages


def render_pdf(pages: list[Page], image: Callable[[str, int], Path | None]) -> bytes:
    """`image(card_id, face)` returns a local image file, or None (offline): a text page instead."""
    font = ImageFont.load_default(size=30)
    small = ImageFont.load_default(size=24)
    rendered = []
    for page in pages:
        canvas = Image.new("RGB", (PAGE_WIDTH, CARD_HEIGHT + CAPTION_HEIGHT), BACKGROUND)
        path = image(page.card_id, page.face)
        draw = ImageDraw.Draw(canvas)
        if path is not None:
            with Image.open(path) as card:
                card = card.convert("RGB")
                card.thumbnail((PAGE_WIDTH, CARD_HEIGHT))
                canvas.paste(card, ((PAGE_WIDTH - card.width) // 2, (CARD_HEIGHT - card.height) // 2))
        else:
            draw.text((PAGE_WIDTH / 2, CARD_HEIGHT / 2), page.name, fill=TEXT, font=font, anchor="mm")
        y = CARD_HEIGHT + CAPTION_HEIGHT / 2
        # The default font has no "×".
        draw.text((24, y), f"{page.quantity}x  {page.name}", fill=TEXT, font=font, anchor="lm")
        if page.mana_cost and page.face == 0:
            _mana_cost(draw, page.mana_cost.split(" // ")[0], PAGE_WIDTH - 24, y, small)
        rendered.append(canvas)
    if not rendered:
        rendered.append(Image.new("RGB", (PAGE_WIDTH, CARD_HEIGHT + CAPTION_HEIGHT), BACKGROUND))
    buffer = io.BytesIO()
    rendered[0].save(buffer, format="PDF", save_all=True, append_images=rendered[1:], resolution=DPI)
    return buffer.getvalue()


def _mana_cost(draw: ImageDraw.ImageDraw, cost: str, right: float, y: float, font) -> None:
    """Mana symbols as colored circles, right-aligned at `right`."""
    symbols = _SYMBOL_RE.findall(cost)
    x = right - len(symbols) * (SYMBOL_SIZE + 4)
    for symbol in symbols:
        color = SYMBOL_COLORS.get(symbol[0], GENERIC) if len(symbol) == 1 or "/" in symbol else GENERIC
        box = (x, y - SYMBOL_SIZE / 2, x + SYMBOL_SIZE, y + SYMBOL_SIZE / 2)
        draw.ellipse(box, fill=color)
        label = symbol.replace("/", "")[:2]
        draw.text((x + SYMBOL_SIZE / 2, y), label, fill=(20, 20, 20), font=font, anchor="mm")
        x += SYMBOL_SIZE + 4
