"""Proxy and calibration pages as PDF (reportlab). All geometry comes from mtgdm.printing.layout;
this module only converts millimetres from the top-left corner into PDF points."""

import os
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import BinaryIO, Literal

from reportlab.lib.colors import Color
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import registerFont, stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from mtgdm.i18n import tr
from mtgdm.printing.layout import COLUMNS, NO_CORRECTION, PER_PAGE, ROWS, Correction, Line, PageLayout, Rect
from mtgdm.printing.text_cards import CardText

PT_PER_MM = 72 / 25.4
# The PDF standard fonts have no Polish letters (ł, ś, ...): a system font with them, embedded
# (subset); without one, Helvetica and letters without diacritics.
_WINDOWS_FONTS = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
SYSTEM_FONTS = [
    (Path("/System/Library/Fonts/Supplemental/Arial.ttf"), Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")),
    (_WINDOWS_FONTS / "arial.ttf", _WINDOWS_FONTS / "arialbd.ttf"),
    (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    (Path("/usr/share/fonts/TTF/DejaVuSans.ttf"), Path("/usr/share/fonts/TTF/DejaVuSans-Bold.ttf")),
]
MARK_COLOR = Color(0, 0, 0)
FRAME_COLOR = Color(0.55, 0.55, 0.55)
TEXT_COLOR = Color(0.25, 0.25, 0.25)
LINE_WIDTH_MM = 0.1
# The app's card back (packaging/icon.svg colours): a dark card with two cards and a gold circle.
BACK_TOP, BACK_BOTTOM = Color(0x26 / 255, 0x2C / 255, 0x38 / 255), Color(0x0F / 255, 0x12 / 255, 0x18 / 255)
BACK_CARD = Color(0x1F / 255, 0x24 / 255, 0x30 / 255)
BACK_GREY = Color(0x8B / 255, 0x93 / 255, 0xA6 / 255)
GOLD_LIGHT, GOLD_DARK = Color(0xF0 / 255, 0xC9 / 255, 0x68 / 255), Color(0xB8 / 255, 0x86 / 255, 0x2C / 255)
CORNER_RADIUS_MM = 3.0  # Magic cards have ~3 mm round corners
Duplex = Literal["off", "long", "short"]


@dataclass(frozen=True)
class Slot:
    """One printed card: a face of a printing."""

    card_id: str
    face: int
    name: str


@cache
def _fonts() -> tuple[str, str, bool]:
    """(regular, bold, unicode): registered TrueType fonts, or Helvetica."""
    for regular, bold in SYSTEM_FONTS:
        if regular.is_file() and bold.is_file():
            try:
                registerFont(TTFont("MtgdmSans", str(regular)))
                registerFont(TTFont("MtgdmSans-Bold", str(bold)))
                return "MtgdmSans", "MtgdmSans-Bold", True
            except Exception:  # broken font file: try the next one
                continue
    return "Helvetica", "Helvetica-Bold", False


def _plain(text: str) -> str:
    """Text Helvetica can show: Latin letters without diacritics (ł has no decomposition)."""
    text = text.replace("ł", "l").replace("Ł", "L").replace("−", "-").replace("›", ">")
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return text.encode("cp1252", "replace").decode("cp1252")


class _Page:
    """Drawing in millimetres from the paper's top-left corner."""

    def __init__(self, canvas: Canvas, layout: PageLayout):
        self.c = canvas
        self.layout = layout
        self.height = layout.paper_size[1]

    def line(self, line: Line, color: Color = MARK_COLOR, width: float = LINE_WIDTH_MM) -> None:
        self.c.setStrokeColor(color)
        self.c.setLineWidth(width * PT_PER_MM)
        self.c.line(line.x1 * PT_PER_MM, (self.height - line.y1) * PT_PER_MM,
                    line.x2 * PT_PER_MM, (self.height - line.y2) * PT_PER_MM)

    def rect(self, r: Rect, color: Color = FRAME_COLOR, width: float = LINE_WIDTH_MM) -> None:
        self.c.setStrokeColor(color)
        self.c.setLineWidth(width * PT_PER_MM)
        self.c.rect(r.x * PT_PER_MM, (self.height - r.bottom) * PT_PER_MM, r.w * PT_PER_MM, r.h * PT_PER_MM)

    def image(self, path: Path, r: Rect, upside_down: bool = False) -> None:
        # Transparent corners stay transparent (white paper); the aspect ratio is never changed.
        c = self.c
        c.saveState()
        c.translate((r.x + r.w / 2) * PT_PER_MM, (self.height - r.y - r.h / 2) * PT_PER_MM)
        if upside_down:
            c.rotate(180)
        w, h = r.w * PT_PER_MM, r.h * PT_PER_MM
        c.drawImage(str(path), -w / 2, -h / 2, w, h, mask="auto", preserveAspectRatio=True, anchor="c")
        c.restoreState()

    def _font(self, bold: bool) -> str:
        return _fonts()[1 if bold else 0]

    def _str(self, text: str) -> str:
        return text if _fonts()[2] else _plain(text)

    def text_card(self, r: Rect, card: CardText, upside_down: bool = False) -> None:
        """A low-ink proxy: outlines and text only. Laid out for a 63 x 88 mm card, scaled to the frame."""
        c = self.c
        c.saveState()
        if upside_down:
            cx, cy = (r.x + r.w / 2) * PT_PER_MM, (self.height - r.y - r.h / 2) * PT_PER_MM
            c.translate(cx, cy)
            c.rotate(180)
            c.translate(-cx, -cy)
        # Card coordinates: millimetres from the card's top-left corner, y down.
        sx, sy = r.w / 63 * PT_PER_MM, r.h / 88 * PT_PER_MM
        c.translate(r.x * PT_PER_MM, (self.height - r.y) * PT_PER_MM)
        c.scale(sx, -sy)
        c.setStrokeColor(MARK_COLOR)
        c.setLineWidth(0.3)
        c.roundRect(0, 0, 63, 88, CORNER_RADIUS_MM, stroke=1, fill=0)
        c.setLineWidth(0.15)
        c.setStrokeColor(FRAME_COLOR)
        for y in (9.5, 37.5, 43.5, 79.5):
            c.line(3, y, 60, y)
        c.rect(3, 10.5, 57, 26, stroke=1, fill=0)  # where the art would be
        _logo_outline(c, 31.5, 23.5, 0.55)

        def write(text: str, x: float, y: float, size: float, bold: bool = False, align: str = "left",
                  width: float | None = None) -> None:
            text = self._str(text)
            font = self._font(bold)
            c.saveState()
            c.translate(x, y)
            c.scale(1, -1)  # text upright in the flipped card coordinates
            c.setFillColor(MARK_COLOR)
            size_mm = size / PT_PER_MM
            c.setFont(font, size_mm)
            if width is not None and stringWidth(text, font, size_mm) > width:
                while text and stringWidth(text + "…", font, size_mm) > width:
                    text = text[:-1]
                text += "…"
            {"left": c.drawString, "right": c.drawRightString, "center": c.drawCentredString}[align](0, 0, text)
            c.restoreState()

        # Title bar: mana symbols right, the name in the rest.
        symbols = _symbols(card.mana_cost)
        cost_width = len(symbols) * 3.9
        for i, symbol in enumerate(reversed(symbols)):
            cx = 58.2 - i * 3.9
            c.setStrokeColor(MARK_COLOR)
            c.setLineWidth(0.2)
            c.circle(cx, 6.1, 1.75, stroke=1, fill=0)
            write(symbol, cx, 6.1 + 0.85, 5.5 if len(symbol) < 2 else 4, bold=True, align="center")
        write(card.name, 3.5, 7.4, 8.5, bold=True, width=55.5 - cost_width)
        write(card.type_line, 3.5, 41.6, 7, bold=True, width=56)

        # Rules text: the largest size that fits the box.
        box_w, box_top, box_bottom = 56.0, 45.0, 78.5
        font = self._font(False)
        for size in (8.5, 8, 7.5, 7, 6.5, 6, 5.5, 5, 4.5, 4):
            size_mm = size / PT_PER_MM
            lines = []
            for paragraph in self._str(card.oracle_text).split("\n"):
                lines += simpleSplit(paragraph, font, size_mm, box_w) or [""]
            leading = size_mm * 1.2
            if len(lines) * leading <= box_bottom - box_top:
                break
        y = box_top + size_mm
        c.setFont(font, size_mm)
        for line in lines:
            c.saveState()
            c.translate(3.5, y)
            c.scale(1, -1)
            c.setFillColor(MARK_COLOR)
            c.drawString(0, 0, line)
            c.restoreState()
            y += leading

        # Bottom: price and printing left, power/toughness or loyalty right.
        write(" · ".join(p for p in (card.price, card.printing) if p), 3.5, 84.5, 5.5)
        write(tr("print_proxy_mark"), 3.5, 86.8, 4.5)
        if card.stats:
            c.setLineWidth(0.2)
            c.setStrokeColor(MARK_COLOR)
            c.roundRect(49, 81, 11, 5, 1, stroke=1, fill=0)
            write(card.stats, 54.5, 84.6, 8, bold=True, align="center")
        c.restoreState()

    def card_back_outline(self, r: Rect) -> None:
        """The app's card back as outlines only (text proxies: no ink-heavy fill)."""
        c = self.c
        c.saveState()
        c.translate(r.x * PT_PER_MM, (self.height - r.y) * PT_PER_MM)
        c.scale(r.w / 63 * PT_PER_MM, -r.h / 88 * PT_PER_MM)
        c.setStrokeColor(MARK_COLOR)
        c.setLineWidth(0.3)
        c.roundRect(0, 0, 63, 88, CORNER_RADIUS_MM, stroke=1, fill=0)
        _logo_outline(c, 31.5, 40, 1.0)
        c.translate(31.5, 72)
        c.scale(1, -1)
        c.setFillColor(GOLD_DARK)
        c.setFont(self._font(True), 4.2)
        c.drawCentredString(0, 0, "MTG Deck Manager")
        c.restoreState()

    def card_back(self, r: Rect) -> None:
        """The app's own card back, drawn as vectors (no Scryfall image, no Wizards card back)."""
        c = self.c
        x, y, w, h = r.x * PT_PER_MM, (self.height - r.bottom) * PT_PER_MM, r.w * PT_PER_MM, r.h * PT_PER_MM
        radius = CORNER_RADIUS_MM * PT_PER_MM
        c.saveState()
        path = c.beginPath()
        path.roundRect(x, y, w, h, radius)
        c.clipPath(path, stroke=0, fill=0)
        c.linearGradient(x, y + h, x, y, (BACK_TOP, BACK_BOTTOM), extend=True)
        # The icon's motif, scaled to the card: a tilted grey card behind a gold-edged one and a gold circle.
        unit = w / 63  # points per mm of the nominal card width
        cx, cy = x + w / 2, y + h / 2 + 4 * unit
        c.setLineWidth(0.9 * unit)
        c.saveState()
        c.translate(cx - 4 * unit, cy + 1 * unit)
        c.rotate(10)
        c.setFillColor(BACK_CARD)
        c.setStrokeColor(BACK_GREY)
        c.roundRect(-11 * unit, -15.5 * unit, 22 * unit, 31 * unit, 2.2 * unit, stroke=1, fill=1)
        c.restoreState()
        c.setFillColor(BACK_CARD)
        c.setStrokeColor(GOLD_DARK)
        c.setLineWidth(1.3 * unit)
        c.roundRect(cx - 9 * unit, cy - 19 * unit, 23 * unit, 32 * unit, 2.4 * unit, stroke=1, fill=1)
        c.setFillColor(GOLD_LIGHT)
        c.circle(cx + 2.5 * unit, cy - 3 * unit, 5.8 * unit, stroke=0, fill=1)
        c.setFont(_fonts()[1], 4.2 * unit)
        c.setFillColor(GOLD_LIGHT)
        c.drawCentredString(cx, y + h * 0.16, "MTG Deck Manager")
        c.restoreState()

    def text(self, text: str, x: float, y: float, size: float = 6, bold: bool = False, max_width: float | None = None,
             align: str = "center") -> None:
        """Text with its baseline at y; shortened with an ellipsis to fit max_width (mm)."""
        regular, heavy, unicode = _fonts()
        font = heavy if bold else regular
        if not unicode:
            text = _plain(text)
        if max_width is not None:
            limit = max_width * PT_PER_MM
            if stringWidth(text, font, size) > limit:
                while text and stringWidth(text + "…", font, size) > limit:
                    text = text[:-1]
                text += "…"
        self.c.setFillColor(TEXT_COLOR)
        self.c.setFont(font, size)
        draw = {"center": self.c.drawCentredString, "left": self.c.drawString, "right": self.c.drawRightString}[align]
        draw(x * PT_PER_MM, (self.height - y) * PT_PER_MM, text)

    def margin_texts(self, texts: list[str], top: bool, correction: Correction) -> None:
        """Up to three short texts in the top or bottom margin, one per card column, between the
        crop marks (they share the margin band)."""
        layout, grid = self.layout, self.layout.grid
        band = layout.mark_gap + layout.mark_length / 2
        y = correction.y(grid.y - band) + 0.8 if top else correction.y(grid.bottom + band) + 0.8
        for col, text in enumerate(texts[:COLUMNS]):
            x = grid.x + col * (layout.card_w + layout.gap) + layout.card_w / 2
            self.text(text, correction.x(x), y, max_width=layout.card_w * correction.scale_x - 4)


def back_position(index: int, duplex: Duplex) -> int:
    """Where a card's back goes on the back page: the sheet turns over its long edge (columns swap
    sides) or its short edge (rows swap; the images are then upside down on the page, so a cut card
    flipped sideways shows its back upright)."""
    row, col = divmod(index, COLUMNS)
    if duplex == "long":
        col = COLUMNS - 1 - col
    elif duplex == "short":
        row = ROWS - 1 - row
    return row * COLUMNS + col


def render_proxies(
    out: BinaryIO,
    slots: list[Slot],
    image: Callable[[Slot], Path | None],
    layout: PageLayout,
    correction: Correction = NO_CORRECTION,
    cut_marks: bool = True,
    title: str = "",
    profile_label: str | None = None,
    progress: Callable[[int], None] | None = None,
    backs: list[Slot | None] | None = None,
    duplex: Duplex = "off",
    back_shift: tuple[float, float] = (0.0, 0.0),
    texts: Callable[[Slot], CardText | None] | None = None,
) -> int:
    """Write the proxy pages to `out` (3 x 3 cards per page); returns the number of pages.
    `image(slot)` returns a local image file, or None: a frame with the card's name instead.
    With duplex, every page of fronts is followed by a page of backs: `backs[i]` (a double-faced
    card's other face) or the app's card back.
    With `texts`, text proxies (rules text, outlines only) instead of images."""
    canvas = _canvas(out, layout, title)
    sheets = max(1, -(-len(slots) // PER_PAGE))
    pages = sheets * (2 if duplex != "off" else 1)
    frames = layout.frames()

    def draw(page: _Page, slot: Slot, frame: Rect, upside_down: bool = False, shift=(0.0, 0.0)) -> None:
        text = texts(slot) if texts else None
        if text is not None:
            page.text_card(_shifted(correction.rect(frame), shift), text, upside_down)
            return
        path = image(slot) if not texts else None
        if path is not None:
            page.image(path, _shifted(correction.image_rect(frame), shift), upside_down)
        else:
            box = _shifted(correction.rect(frame), shift)
            page.rect(box)
            page.text(slot.name, box.x + box.w / 2, box.y + box.h / 2, size=9, bold=True, max_width=box.w - 6)

    for sheet in range(sheets):
        number = sheet * (2 if duplex != "off" else 1)
        page = _Page(canvas, layout)
        start = sheet * PER_PAGE
        for slot, frame in zip(slots[start:start + PER_PAGE], frames, strict=False):
            draw(page, slot, frame)
            if progress:
                progress(1)
        if cut_marks:
            for mark in layout.crop_marks():
                page.line(correction.line(mark))
            for cut in layout.cut_lines():
                page.line(correction.line(cut), FRAME_COLOR)
        page.margin_texts([
            tr("print_footer_page", title=title, page=number + 1, pages=pages),
            profile_label or tr("print_uncalibrated"),
            tr("print_actual_size"),
        ], top=False, correction=correction)
        canvas.showPage()

        if duplex != "off":
            # No marks or footer on the back: duplex printers don't line both sides up exactly.
            page = _Page(canvas, layout)
            for i, slot in enumerate(slots[start:start + PER_PAGE]):
                frame = frames[back_position(i, duplex)]
                back = backs[start + i] if backs else None
                if back is not None:
                    draw(page, back, frame, upside_down=duplex == "short", shift=back_shift)
                elif texts:
                    page.card_back_outline(_shifted(correction.rect(frame), back_shift))
                else:
                    page.card_back(_shifted(correction.rect(frame), back_shift))
            canvas.showPage()
    canvas.save()
    return pages


def render_calibration(out: BinaryIO, layout: PageLayout, correction: Correction = NO_CORRECTION,
                       profile_label: str | None = None) -> None:
    """3 x 3 card frames without a gap; measure A (grid width), B (grid height) and optionally the
    distances from the left and top paper edges. With a profile's correction: the verification page."""
    canvas = _canvas(out, layout, tr("print_calibration_title"))
    page = _Page(canvas, layout)
    grid = layout.grid
    size = tr("print_card_size", w=layout.card_w, h=layout.card_h)
    for frame in layout.frames():
        box = correction.rect(frame)
        page.rect(box, MARK_COLOR, 0.15)
        page.text(size, box.x + box.w / 2, box.bottom - 4, size=7)
    for mark in layout.crop_marks():
        page.line(correction.line(mark))

    # A: across the first row; B: down the first column, left of the frame labels.
    a_y = grid.y + layout.card_h * 0.35
    _dimension(page, correction.line(Line(grid.x, a_y, grid.right, a_y)), horizontal=True)
    page.text(tr("print_measure_a", mm=grid.w), correction.x(grid.x + grid.w / 2), correction.y(a_y) - 1.5, size=9,
              bold=True)
    b_x = grid.x + layout.card_w * 0.2
    _dimension(page, correction.line(Line(b_x, grid.y, b_x, grid.bottom)), horizontal=False)
    page.text(tr("print_measure_b", mm=grid.h), correction.x(b_x) + 2, correction.y(grid.y + layout.card_h * 1.5),
              size=9, bold=True, align="left")

    # Offsets (optional): from the paper edges to the grid's top-left corner; in the top-right card.
    x = correction.x(grid.x + 2 * (layout.card_w + layout.gap)) + 3
    for i, text in enumerate((tr("print_measure_left", mm=grid.x), tr("print_measure_top", mm=grid.y))):
        page.text(text, x, correction.y(grid.y + layout.card_h * 0.6) + i * 3.5, size=6.5, align="left",
                  max_width=layout.card_w - 6)

    # Instructions in the middle row's second and third cards.
    x = correction.x(grid.x + layout.card_w + layout.gap) + 3
    y = correction.y(grid.y + layout.card_h + 10)
    lines = [tr("print_verification") if profile_label else tr("print_calibration_title")]
    lines += tr("print_calibration_steps").split("\n")
    for i, text in enumerate(lines):
        page.text(text, x, y + i * 3.6, size=7 if i else 9, bold=i == 0, align="left",
                  max_width=2 * layout.card_w - 6)

    page.margin_texts([
        tr("print_verification") if profile_label else tr("print_uncalibrated"),
        profile_label or "",
        tr("print_actual_size"),
    ], top=False, correction=correction)
    canvas.showPage()
    canvas.save()


def render_duplex_test(out: BinaryIO, layout: PageLayout, duplex: Literal["long", "short"],
                       correction: Correction = NO_CORRECTION, back_shift: tuple[float, float] = (0.0, 0.0),
                       profile_label: str | None = None) -> None:
    """Two pages: the front has scales (0.5 mm ticks) around the page centre, the back a line across
    each scale. Seen against the light from the front, where a back line crosses its scale is how
    far the printer puts the back off: X (+ right), Y (+ down)."""
    canvas = _canvas(out, layout, tr("print_duplex_title"))
    paper_w, paper_h = layout.paper_size
    cx, cy = paper_w / 2, paper_h / 2
    reach = 6.0  # scale from -6 to +6 mm
    x_scale_y, y_scale_x = cy - 12, cx + 12  # where the two scales sit (nominal)

    page = _Page(canvas, layout)
    for i in range(int(-reach * 2), int(reach * 2) + 1):
        d = i / 2
        length = 4.0 if i % 4 == 0 else 2.5 if i % 2 == 0 else 1.5
        page.line(correction.line(Line(cx + d, x_scale_y - length, cx + d, x_scale_y)))
        page.line(correction.line(Line(y_scale_x, cy + d, y_scale_x + length, cy + d)))
        if i % 4 == 0:
            label = f"{d:.0f}".replace("-", "−")  # the direction is in the scale's title
            page.text(label, correction.x(cx + d), correction.y(x_scale_y - 5), size=5)
            page.text(label, correction.x(y_scale_x + 5), correction.y(cy + d) + 0.6, size=5, align="left")
    page.text(tr("print_duplex_x"), correction.x(cx), correction.y(x_scale_y - 13), size=7, bold=True)
    page.text(tr("print_duplex_y"), correction.x(y_scale_x + 10), correction.y(cy) + 1, size=7, bold=True, align="left")
    mode = tr("print_duplex_long") if duplex == "long" else tr("print_duplex_short")
    lines = [tr("print_duplex_title") + f" – {mode}"] + tr("print_duplex_steps", mode=mode).split("\n")
    for i, text in enumerate(lines):
        page.text(text, correction.x(layout.grid.x), correction.y(layout.grid.y + 10) + i * 4, size=7 if i else 10,
                  bold=i == 0, align="left", max_width=paper_w - 2 * layout.grid.x)
    page.margin_texts([profile_label or tr("print_uncalibrated"), "", tr("print_actual_size")], top=False,
                      correction=correction)
    canvas.showPage()

    # The back: a line across each scale, at the mirrored position.
    def mirror(x: float, y: float) -> tuple[float, float]:
        x, y = (paper_w - x, y) if duplex == "long" else (x, paper_h - y)
        return correction.x(x) + back_shift[0], correction.y(y) + back_shift[1]

    page = _Page(canvas, layout)
    for (x1, y1), (x2, y2) in (((cx, x_scale_y - 10), (cx, x_scale_y + 6)),
                               ((y_scale_x - 6, cy), (y_scale_x + 10, cy))):
        (a, b), (c, d) = mirror(x1, y1), mirror(x2, y2)
        page.line(Line(a, b, c, d), MARK_COLOR, 0.25)
    canvas.showPage()
    canvas.save()


def _symbols(mana_cost: str) -> list[str]:
    """{2}{W/U}{G} -> ["2", "W/U", "G"]; the halves of a split cost (" // ") are not on the title bar."""
    return [s for s in mana_cost.replace("{", " ").replace("}", " ").split() if s != "//"]


def _logo_outline(c: Canvas, cx: float, cy: float, scale: float) -> None:
    """The icon's motif as outlines, centred at (cx, cy) in y-down millimetres."""
    c.saveState()
    c.translate(cx, cy)
    c.scale(scale, scale)
    c.setLineWidth(0.6)
    c.saveState()
    c.translate(-4, -1)
    c.rotate(-10)
    c.setStrokeColor(BACK_GREY)
    c.roundRect(-11, -15.5, 22, 31, 2.2, stroke=1, fill=0)
    c.restoreState()
    c.setStrokeColor(GOLD_DARK)
    c.setLineWidth(0.9)
    c.roundRect(-9, -13, 23, 32, 2.4, stroke=1, fill=0)
    c.circle(2.5, 3, 5.8, stroke=1, fill=0)
    c.restoreState()


def _shifted(r: Rect, shift: tuple[float, float]) -> Rect:
    return Rect(r.x + shift[0], r.y + shift[1], r.w, r.h)


def _dimension(page: _Page, line: Line, horizontal: bool) -> None:
    """A measuring line with end ticks across it."""
    page.line(line, MARK_COLOR, 0.2)
    tick = 2.5
    for x, y in ((line.x1, line.y1), (line.x2, line.y2)):
        if horizontal:
            page.line(Line(x, y - tick, x, y + tick), MARK_COLOR, 0.2)
        else:
            page.line(Line(x - tick, y, x + tick, y), MARK_COLOR, 0.2)


def _canvas(out: BinaryIO, layout: PageLayout, title: str) -> Canvas:
    w, h = layout.paper_size
    canvas = Canvas(out, pagesize=(w * PT_PER_MM, h * PT_PER_MM), pageCompression=1)
    canvas.setTitle(title)
    canvas.setCreator("MTG Deck Manager")
    return canvas
