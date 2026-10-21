"""Turn OCR lines of a straightened card into fields.

Bottom-left text by frame:
    2024+:      "R 0141"       / "FDN • EN  ✎ Kai Carpenter"
    2015-2023:  "117/331 U"    / "2X2 • EN  ✎ Christopher Moeller"
    2003-2014:  "✎ Christopher Moeller" / "™ & © 1993-2009 Wizards of the Coast LLC. 146/249"
    1993-2002:  "Illus. Kaja Foglio" / "© 1995 Wizards of the Coast"   (no number, no set code)
"""

import re
from dataclasses import dataclass

from mtgdm.scan.ocr.base import OcrLine

NAME_BAND = 0.13      # name bar: top 13% of the card
BOTTOM_BAND = 0.9     # collector / artist / copyright lines: bottom 10%
LEFT_LIMIT = 0.45     # collector info starts at the left edge
LANGUAGES = {"EN", "DE", "FR", "IT", "ES", "SP", "PT", "JA", "JP", "KO", "RU", "ZHS", "ZHT", "CS", "CT", "PH", "PL"}

_NUMBER_OF_TOTAL = re.compile(r"(?<![\w/])([0-9OoIlSB]{1,4}[a-z]?)\s*/\s*([0-9OoIlSB]{1,4})(?![\w/])")
_RARITY_NUMBER = re.compile(r"^\s*([CURMLSTP])\s*([0-9OoIlSB]{1,4}[a-z]?)\b")
_LANG_RE = "|".join(sorted(LANGUAGES, key=len, reverse=True))
# Code and language need a separator ("FDN • EN", "WHO★EN") or a space: "TOKEN" is not TOK + EN.
# OCR may glue the artist to the language ("WHO★ENDAVID"), so no word boundary after it.
_SET_LANG = re.compile(r"^\s*([A-Z0-9]{2,5})(?:\s*[•·.\-*★☆]\s*|\s+)(" + _LANG_RE + r")")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_ILLUS = re.compile(r"^\s*(?:Illus\.?|Illustrated by)\s+(.+)$", re.I)
_DIGIT_FIXES = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "S": "5", "B": "8"})
_JUNK = re.compile(r"^[^A-Za-z]*$")


@dataclass
class CardText:
    name: str | None = None
    name_confidence: float = 0.0
    type_line: str | None = None
    collector_number: str | None = None
    set_code: str | None = None       # lower case, as printed (usually the Scryfall code)
    language: str | None = None       # lower case
    artist: str | None = None
    year: int | None = None           # latest copyright year printed on the card
    text: str = ""                    # all recognized text, for debugging and fallbacks

    @property
    def has_collector_info(self) -> bool:
        return self.collector_number is not None


def read_card(lines: list[OcrLine]) -> CardText:
    card = CardText(text="\n".join(line.text for line in lines))

    top = [line for line in lines if line.cy < NAME_BAND and _looks_like_name(line.text)]
    if top:
        best = max(top, key=lambda line: (line.w, -line.y))  # widest text in the name bar
        card.name, card.name_confidence = _clean_name(best.text), best.confidence

    type_lines = [line for line in lines if 0.5 < line.cy < 0.66 and ("—" in line.text or " - " in line.text)]
    if type_lines:
        card.type_line = type_lines[0].text

    # Left side only: the power/toughness box ("2/2") sits bottom right.
    bottom = [line for line in lines if line.cy > BOTTOM_BAND and line.x < LEFT_LIMIT]
    for line in bottom:
        text = line.text.strip()
        if card.collector_number is None:
            if m := _RARITY_NUMBER.match(text):
                card.collector_number = _number(m.group(2))
            elif m := _NUMBER_OF_TOTAL.search(text):
                card.collector_number = _number(m.group(1))
        if card.set_code is None and (m := _SET_LANG.search(text.upper())):
            code, lang = m.group(1), m.group(2)
            if not code.isdigit():
                card.set_code, card.language = code.lower(), lang.lower()
                card.artist = card.artist or _artist_after(text, m.end())
        if m := _ILLUS.match(text):
            card.artist = m.group(1).strip()
        if "©" in text or "Wizards" in text:
            years = [int(y) for y in _YEAR.findall(text)]
            if years:
                card.year = max(years)
    return card


def _looks_like_name(text: str) -> bool:
    letters = sum(c.isalpha() for c in text)
    return letters >= 3 and not _JUNK.match(text)


def _clean_name(text: str) -> str:
    # Mana cost symbols read as stray digits / letters at the end of the name bar.
    text = re.sub(r"\s+[0-9WUBRGCX{}()]{1,6}$", "", text.strip())
    return text.strip(" .,:;|")


def _number(raw: str) -> str:
    """'0141' -> '141', 'O14l' -> '141' (OCR letter/digit mix-ups), '61a' keeps its face letter."""
    suffix = ""
    if raw[-1].islower() and raw[-1] not in "ol":
        raw, suffix = raw[:-1], raw[-1]
    digits = raw.translate(_DIGIT_FIXES).lstrip("0") or "0"
    return digits + suffix


def _artist_after(text: str, start: int) -> str | None:
    rest = re.sub(r"^[^A-Za-z]+", "", text[start:]).strip()
    return rest.title() if len(rest) >= 4 else None
