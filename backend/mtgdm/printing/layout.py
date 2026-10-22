"""Geometry of proxy pages, in millimetres from the paper's top-left corner (no PDF here).

Printers scale a page slightly (often differently across and along the paper) and shift it. A
printer profile measures that once (calibration page) and pre-compensates every frame, crop mark
and cut line per axis, so the printed grid has the nominal size. Card images are scaled by one
factor (the mean of both axes) and centred in their compensated frame: Scryfall's image rules
forbid stretching, and the residual difference is a fraction of a millimetre.
"""

from dataclasses import dataclass

PAPER_MM: dict[str, tuple[float, float]] = {"a4": (210.0, 297.0), "letter": (215.9, 279.4)}
COLUMNS = ROWS = 3
PER_PAGE = COLUMNS * ROWS
DEFAULT_CARD_MM = (63.0, 88.0)
# Most printers can't print closer than this to the paper edge.
PRINTABLE_MARGIN_MM = 3.0
MARK_GAP_MM = 1.0       # crop marks start this far from the grid ...
MARK_LENGTH_MM = 5.0    # ... and are at most this long (shorter in narrow margins, e.g. Letter)
MIN_MARK_LENGTH_MM = 1.5
SCALE_LIMITS = (0.90, 1.10)


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass(frozen=True)
class Line:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class Correction:
    """A printer profile's pre-compensation: page = nominal * scale + offset, per axis."""

    scale_x: float = 1.0
    scale_y: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0

    @property
    def image_scale(self) -> float:
        return (self.scale_x + self.scale_y) / 2

    def x(self, x: float) -> float:
        return x * self.scale_x + self.offset_x

    def y(self, y: float) -> float:
        return y * self.scale_y + self.offset_y

    def rect(self, r: Rect) -> Rect:
        return Rect(self.x(r.x), self.y(r.y), r.w * self.scale_x, r.h * self.scale_y)

    def line(self, line: Line) -> Line:
        return Line(self.x(line.x1), self.y(line.y1), self.x(line.x2), self.y(line.y2))

    def image_rect(self, frame: Rect) -> Rect:
        """Where the card image goes: uniformly scaled, centred in the compensated frame."""
        page = self.rect(frame)
        w, h = frame.w * self.image_scale, frame.h * self.image_scale
        return Rect(page.x + (page.w - w) / 2, page.y + (page.h - h) / 2, w, h)


NO_CORRECTION = Correction()


@dataclass(frozen=True)
class PageLayout:
    paper: str
    card_w: float
    card_h: float
    gap: float = 0.0

    @property
    def paper_size(self) -> tuple[float, float]:
        return PAPER_MM[self.paper]

    @property
    def grid(self) -> Rect:
        """The 3 x 3 card grid, centred on the paper (nominal)."""
        paper_w, paper_h = self.paper_size
        w = COLUMNS * self.card_w + (COLUMNS - 1) * self.gap
        h = ROWS * self.card_h + (ROWS - 1) * self.gap
        return Rect((paper_w - w) / 2, (paper_h - h) / 2, w, h)

    @property
    def mark_gap(self) -> float:
        return MARK_GAP_MM

    @property
    def mark_length(self) -> float:
        """Crop marks end inside the printable area where the margin allows it."""
        g = self.grid
        room = min(g.x, g.y) - PRINTABLE_MARGIN_MM - MARK_GAP_MM
        return max(MIN_MARK_LENGTH_MM, min(MARK_LENGTH_MM, room))

    def frames(self) -> list[Rect]:
        """Card frames row by row, left to right (nominal)."""
        g = self.grid
        return [
            Rect(g.x + col * (self.card_w + self.gap), g.y + row * (self.card_h + self.gap), self.card_w, self.card_h)
            for row in range(ROWS)
            for col in range(COLUMNS)
        ]

    def edges(self) -> tuple[list[float], list[float]]:
        """x positions of every vertical card edge and y positions of every horizontal one."""
        g = self.grid
        xs = sorted({round(g.x + col * (self.card_w + self.gap) + d, 6)
                     for col in range(COLUMNS) for d in (0.0, self.card_w)})
        ys = sorted({round(g.y + row * (self.card_h + self.gap) + d, 6)
                     for row in range(ROWS) for d in (0.0, self.card_h)})
        return xs, ys

    def crop_marks(self) -> list[Line]:
        """Short marks in the margins, in line with every card edge, never over a card."""
        g = self.grid
        xs, ys = self.edges()
        start, end = self.mark_gap, self.mark_gap + self.mark_length
        marks = []
        for x in xs:
            marks.append(Line(x, g.y - end, x, g.y - start))
            marks.append(Line(x, g.bottom + start, x, g.bottom + end))
        for y in ys:
            marks.append(Line(g.x - end, y, g.x - start, y))
            marks.append(Line(g.right + start, y, g.right + end, y))
        return marks

    def cut_lines(self) -> list[Line]:
        """Full lines through the gaps between cards (only when there are gaps)."""
        if self.gap <= 0:
            return []
        g = self.grid
        xs, ys = self.edges()
        return [Line(x, g.y, x, g.bottom) for x in xs] + [Line(g.x, y, g.right, y) for y in ys]

    def overflow(self, correction: Correction = NO_CORRECTION) -> bool:
        """Does the compensated grid (with its crop marks) leave the printable area?"""
        paper_w, paper_h = self.paper_size
        g = self.grid
        reach = self.mark_gap + self.mark_length
        left, top = correction.x(g.x - reach), correction.y(g.y - reach)
        right, bottom = correction.x(g.right + reach), correction.y(g.bottom + reach)
        m = PRINTABLE_MARGIN_MM
        return left < m or top < m or right > paper_w - m or bottom > paper_h - m


def pages_needed(slots: int) -> int:
    return max(1, -(-slots // PER_PAGE))


# --- calibration ---------------------------------------------------------------------


@dataclass(frozen=True)
class Calibration:
    correction: Correction
    nominal_a: float
    nominal_b: float
    # Printed size vs nominal per axis, in percent (e.g. -1.2 = the printer shrinks by 1.2%).
    difference_x_pct: float
    difference_y_pct: float
    out_of_range: bool  # a factor outside SCALE_LIMITS: likely a wrong measurement or "Fit to page"


def calibrate(
    paper: str,
    card_w: float,
    card_h: float,
    measured_a: float,
    measured_b: float,
    measured_left: float | None = None,
    measured_top: float | None = None,
) -> Calibration:
    """Factors from a calibration page printed without correction (3 x 3 cards, no gap).

    The printer maps a drawn position p to k * p + o. With A and B measured, k = measured / nominal
    and scale = 1 / k. A measured edge distance gives o; pre-compensating with
    offset = nominal_left - measured_left * scale puts the grid where it belongs.
    """
    layout = PageLayout(paper, card_w, card_h)
    grid = layout.grid
    nominal_a, nominal_b = grid.w, grid.h
    scale_x, scale_y = nominal_a / measured_a, nominal_b / measured_b
    offset_x = grid.x - measured_left * scale_x if measured_left is not None else 0.0
    offset_y = grid.y - measured_top * scale_y if measured_top is not None else 0.0
    low, high = SCALE_LIMITS
    return Calibration(
        correction=Correction(scale_x, scale_y, offset_x, offset_y),
        nominal_a=nominal_a,
        nominal_b=nominal_b,
        difference_x_pct=(measured_a / nominal_a - 1) * 100,
        difference_y_pct=(measured_b / nominal_b - 1) * 100,
        out_of_range=not (low <= scale_x <= high and low <= scale_y <= high),
    )
