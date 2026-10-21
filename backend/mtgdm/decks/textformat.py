"""Arena-compatible decklist text format.

    # name: Giada            <- '#' comments; 'key: value' ones are metadata
    Commander                <- section headers (any case)
    1 Calix, Guided by Fate (MAT) 26
    Deck
    11 Forest (SOS) 281
    2x Seal Away *F*         <- 'Nx' quantity, optional foil marker (*F*; Moxfield also *E* = etched)
    7 Plains (TLA) 282 # x   <- trailing comment: a note for the line (collection imports keep it)
"""

import re
from dataclasses import dataclass, field

from mtgdm.decks.models import Board
from mtgdm.i18n import tr

SECTIONS: dict[str, Board] = {
    "commander": "commander",
    "companion": "companion",
    "deck": "main",
    "main": "main",
    "mainboard": "main",
    "sideboard": "sideboard",
    "maybeboard": "maybe",
    "maybe": "maybe",
}
# Arena exports start with an "About" block ("Name <deck name>") that is not part of the list.
ABOUT_SECTION = "about"

_LINE_RE = re.compile(
    r"""^(?P<qty>\d+)x?\s+
        (?P<name>.+?)
        (?:\s+\((?P<set>[A-Za-z0-9_]{2,8})\)(?:\s+(?P<number>[^\s*]+))?)?
        (?P<foil>\s+\*[FE]\*)?
        (?:\s+\#\s*(?P<note>.*?))?
        \s*$""",
    re.VERBOSE,
)
_META_RE = re.compile(r"^#\s*([\w-]+)\s*:\s*(.*)$")


@dataclass
class ParsedLine:
    line_no: int
    text: str
    quantity: int
    name: str
    board: Board
    set_code: str | None = None
    collector_number: str | None = None
    foil: bool = False
    note: str | None = None


@dataclass
class ParseError:
    line_no: int
    text: str
    message: str


@dataclass
class ParsedDeck:
    meta: dict[str, str] = field(default_factory=dict)
    lines: list[ParsedLine] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)


def parse_decklist(text: str) -> ParsedDeck:
    result = ParsedDeck()
    board: Board = "main"
    in_about = False

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip().replace("’", "'")  # typographic apostrophes from web pages
        if not line:
            continue
        if line.startswith("#"):
            if m := _META_RE.match(line):
                result.meta[m.group(1).lower()] = m.group(2).strip()
            continue

        header = line.rstrip(":").strip().lower()
        if header in SECTIONS:
            board = SECTIONS[header]
            in_about = False
            continue
        if header == ABOUT_SECTION:
            in_about = True
            continue
        if in_about:
            if line.lower().startswith("name "):
                result.meta.setdefault("name", line[5:].strip())
            continue

        m = _LINE_RE.match(line)
        if not m:
            result.errors.append(ParseError(line_no, raw, tr("bad_line")))
            continue
        quantity = int(m.group("qty"))
        if quantity < 1:
            result.errors.append(ParseError(line_no, raw, tr("bad_quantity")))
            continue
        result.lines.append(ParsedLine(
            line_no=line_no,
            text=raw,
            quantity=quantity,
            name=m.group("name").strip(),
            board=board,
            set_code=m.group("set").lower() if m.group("set") else None,
            collector_number=m.group("number"),
            foil=bool(m.group("foil")),
            note=m.group("note") or None,
        ))
    return result
