"""Proxy and calibration pages as PDF (reportlab). All geometry comes from mtgdm.printing.layout;
this module only converts millimetres from the top-left corner into PDF points."""

import os
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import BinaryIO

from reportlab.lib.colors import Color
from reportlab.pdfbase.pdfmetrics import registerFont, stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from mtgdm.i18n import tr
from mtgdm.printing.layout import COLUMNS, NO_CORRECTION, PER_PAGE, Correction, Line, PageLayout, Rect

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
    text = text.replace("ł", "l").replace("Ł", "L")
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

    def image(self, path: Path, r: Rect) -> None:
        # Transparent corners stay transparent (white paper); the aspect ratio is never changed.
        self.c.drawImage(str(path), r.x * PT_PER_MM, (self.height - r.bottom) * PT_PER_MM, r.w * PT_PER_MM,
                         r.h * PT_PER_MM, mask="auto", preserveAspectRatio=True, anchor="c")

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
) -> int:
    """Write the proxy pages to `out` (3 x 3 cards per page); returns the number of pages.
    `image(slot)` returns a local image file, or None: a frame with the card's name instead."""
    canvas = _canvas(out, layout, title)
    pages = max(1, -(-len(slots) // PER_PAGE))
    frames = layout.frames()
    for number in range(pages):
        page = _Page(canvas, layout)
        for slot, frame in zip(slots[number * PER_PAGE:(number + 1) * PER_PAGE], frames, strict=False):
            path = image(slot)
            if path is not None:
                page.image(path, correction.image_rect(frame))
            else:
                box = correction.rect(frame)
                page.rect(box)
                page.text(slot.name, box.x + box.w / 2, box.y + box.h / 2, size=9, bold=True, max_width=box.w - 6)
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
