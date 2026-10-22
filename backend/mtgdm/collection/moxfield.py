"""Moxfield collection CSV: export for Moxfield's collection import, and import of
Moxfield's export into our collection (report first, then commit).

Format per Moxfield's help ("Importing a Collection"): exact headers, any order; Edition is the
Scryfall set code; Condition and Language in short or long form; Foil blank / foil / etched."""

import csv
import io
import json
import sqlite3

from pydantic import BaseModel, Field

from mtgdm.cards.models import CardSummary
from mtgdm.cards.search import card_summaries
from mtgdm.collection import service
from mtgdm.collection.models import CollectionItemCreate, Condition, Finish
from mtgdm.decks.matcher import Matcher
from mtgdm.decks.textformat import ParsedLine
from mtgdm.i18n import tr

HEADER = ["Count", "Name", "Edition", "Condition", "Language", "Foil", "Collector Number", "Alter",
          "Playtest Card", "Purchase Price"]

# Our conditions use the Cardmarket scale; Moxfield uses the US one.
CONDITION_TO_MOXFIELD: dict[str, str] = {"M": "M", "NM": "NM", "EX": "LP", "GD": "MP", "LP": "MP", "PL": "HP", "PO": "D"}
CONDITION_FROM_MOXFIELD: dict[str, Condition] = {
    "m": "M", "mint": "M",
    "nm": "NM", "near mint": "NM",
    "lp": "EX", "lightly played": "EX",
    "mp": "GD", "played": "GD", "moderately played": "GD",
    "hp": "PL", "heavily played": "PL",
    "d": "PO", "dm": "PO", "damaged": "PO",
}
# Moxfield language: Scryfall code, printed code, English name.
LANGUAGES = [
    ("en", "en", "English"), ("es", "sp", "Spanish"), ("fr", "fr", "French"), ("de", "de", "German"),
    ("it", "it", "Italian"), ("pt", "pt", "Portuguese"), ("ja", "jp", "Japanese"), ("ko", "kr", "Korean"),
    ("ru", "ru", "Russian"), ("zhs", "cs", "Simplified Chinese"), ("zht", "ct", "Traditional Chinese"),
    ("he", "he", "Hebrew"), ("la", "la", "Latin"), ("grc", "grc", "Ancient Greek"), ("ar", "ar", "Arabic"),
    ("sa", "sa", "Sanskrit"), ("ph", "ph", "Phyrexian"),
]
LANGUAGE_FROM_MOXFIELD = {alias.lower(): code for code, printed, name in LANGUAGES for alias in (code, printed, name)}
MOXFIELD_LANGUAGES = {code for code, _, _ in LANGUAGES}


# --- export ------------------------------------------------------------------


def export_moxfield(conn: sqlite3.Connection, location_id: int | None = None, unassigned: bool = False) -> str:
    """One row per collection entry. Languages Moxfield doesn't know (e.g. Polish) export as English."""
    where, params = ["ci.kind = 'real'"], []  # proxies are not part of what you own
    if location_id is not None:
        where.append("ci.location_id = ?")
        params.append(location_id)
    if unassigned:
        where.append("ci.location_id IS NULL")
    rows = conn.execute(
        f"""
        SELECT ci.quantity, ci.finish, ci.language, ci.condition, c.name, c.set_code, c.collector_number
        FROM collection_items ci JOIN cards c ON c.id = ci.card_id
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY c.name, c.set_code, c.collector_number, ci.id
        """,
        params,
    ).fetchall()
    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(HEADER)
    for r in rows:
        writer.writerow([
            r["quantity"], r["name"], r["set_code"], CONDITION_TO_MOXFIELD.get(r["condition"], "NM"),
            r["language"] if r["language"] in MOXFIELD_LANGUAGES else "en",
            "" if r["finish"] == "nonfoil" else r["finish"], r["collector_number"], "FALSE", "FALSE", "",
        ])
    return out.getvalue()


# --- import ------------------------------------------------------------------


class CollectionImportLine(BaseModel):
    row: int                  # line number in the file (header = 1)
    quantity: int
    name: str
    set_code: str | None
    collector_number: str | None
    finish: Finish
    condition: Condition
    language: str
    note: str | None
    status: str               # matched | warning | not_found
    card: CardSummary | None
    warnings: list[str]
    suggestions: list[str]


class CollectionImportError(BaseModel):
    row: int
    message: str


class CollectionImportCounts(BaseModel):
    matched: int
    warning: int
    not_found: int
    copies: int


class CollectionImportReport(BaseModel):
    lines: list[CollectionImportLine]
    errors: list[CollectionImportError]
    counts: CollectionImportCounts


class CollectionImportRequest(BaseModel):
    text: str = Field(max_length=5_000_000)


class CollectionImportEntry(BaseModel):
    card_id: str
    quantity: int = Field(ge=1, le=999)
    finish: Finish = "nonfoil"
    condition: Condition = "NM"
    language: str = "en"
    note: str | None = None


class CollectionImportCommit(BaseModel):
    entries: list[CollectionImportEntry]
    location_id: int | None = None


class CollectionImportResult(BaseModel):
    added: int
    entries: int


def parse_moxfield(conn: sqlite3.Connection, text: str) -> CollectionImportReport:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames or "Name" not in reader.fieldnames:
        return CollectionImportReport(
            lines=[], errors=[CollectionImportError(row=1, message=tr("moxfield_no_header"))],
            counts=CollectionImportCounts(matched=0, warning=0, not_found=0, copies=0),
        )
    matcher = Matcher(conn)
    lines: list[CollectionImportLine] = []
    card_ids: list[str | None] = []
    errors: list[CollectionImportError] = []
    for index, row in enumerate(reader, start=2):
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        warnings: list[str] = []
        try:
            quantity = int((row.get("Count") or "1").strip() or 1)
            if quantity < 1:
                raise ValueError
        except ValueError:
            errors.append(CollectionImportError(row=index, message=tr("bad_quantity")))
            continue
        set_code = (row.get("Edition") or "").strip().lower() or None
        number = (row.get("Collector Number") or "").strip() or None

        condition_raw = (row.get("Condition") or "").strip()
        condition = CONDITION_FROM_MOXFIELD.get(condition_raw.lower(), "NM")
        if condition_raw and condition_raw.lower() not in CONDITION_FROM_MOXFIELD:
            warnings.append(tr("moxfield_unknown_condition", value=condition_raw))
        language_raw = (row.get("Language") or "").strip()
        language = LANGUAGE_FROM_MOXFIELD.get(language_raw.lower(), "en")
        if language_raw and language_raw.lower() not in LANGUAGE_FROM_MOXFIELD:
            warnings.append(tr("moxfield_unknown_language", value=language_raw))
        foil_raw = (row.get("Foil") or "").strip().lower()
        finish: Finish = "etched" if foil_raw == "etched" else "foil" if foil_raw == "foil" else "nonfoil"
        flags = [label for column, label in (("Alter", "alter"), ("Playtest Card", "playtest"))
                 if (row.get(column) or "").strip().upper() == "TRUE"]

        match = matcher.match(ParsedLine(line_no=index, text=name, quantity=quantity, name=name, board="main",
                                         set_code=set_code, collector_number=number))
        warnings += match.warnings
        if match.card_id:
            finishes = json.loads(
                conn.execute("SELECT finishes FROM cards WHERE id = ?", (match.card_id,)).fetchone()[0] or "[]"
            )
            if finishes and finish not in finishes:
                warnings.append(tr("moxfield_finish", finish=finish))
        card_ids.append(match.card_id)
        lines.append(CollectionImportLine(
            row=index, quantity=quantity, name=name, set_code=set_code, collector_number=number, finish=finish,
            condition=condition, language=language, note=", ".join(flags) or None,
            status="not_found" if not match.card_id else "warning" if warnings else "matched",
            card=None, warnings=warnings, suggestions=match.suggestions,
        ))
    cards = {c.id: c for c in card_summaries(conn, list({i for i in card_ids if i}))}
    for line, card_id in zip(lines, card_ids):
        line.card = cards.get(card_id) if card_id else None
    return CollectionImportReport(
        lines=lines,
        errors=errors,
        counts=CollectionImportCounts(
            matched=sum(1 for l in lines if l.status == "matched"),
            warning=sum(1 for l in lines if l.status == "warning"),
            not_found=sum(1 for l in lines if l.status == "not_found"),
            copies=sum(l.quantity for l in lines if l.status != "not_found"),
        ),
    )


def commit_moxfield(conn: sqlite3.Connection, request: CollectionImportCommit) -> CollectionImportResult:
    """Adds the entries (merging with identical existing ones), like Moxfield does: never replaces."""
    added = 0
    for e in request.entries:
        service.add_item(conn, CollectionItemCreate(
            card_id=e.card_id, quantity=e.quantity, finish=e.finish, language=e.language, condition=e.condition,
            location_id=request.location_id, note=e.note,
        ), source="import")
        added += e.quantity
    return CollectionImportResult(added=added, entries=len(request.entries))
