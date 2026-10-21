"""Decklist import: text -> match report (no writes) -> deck."""

import json
import sqlite3
from pathlib import Path
from typing import get_args

from mtgdm.decks import service, versions
from mtgdm.decks.matcher import Matcher, summaries_by_id
from mtgdm.decks.models import (
    DeckCreate,
    DeckDetail,
    DeckFormat,
    ImportCommitRequest,
    ImportCounts,
    ImportLine,
    ImportLineError,
    ImportMeta,
    ImportReport,
    Platform,
    SeedInfo,
)
from mtgdm.decks.textformat import parse_decklist

# '# key: value' comments that are not deck fields end up in the description.
_FIELD_KEYS = {"name", "format", "platform", "preferred-sets"}


def build_report(
    conn: sqlite3.Connection,
    text: str,
    platform: str | None = None,
    preferred_sets: list[str] | None = None,
) -> ImportReport:
    parsed = parse_decklist(text)
    meta = _meta(parsed.meta)
    if platform:
        meta.platform = platform  # type: ignore[assignment]
    if preferred_sets is not None:
        meta.preferred_sets = [s.lower() for s in preferred_sets]

    matcher = Matcher(conn, meta.platform or "paper", meta.preferred_sets)
    matches = [(line, matcher.match(line)) for line in parsed.lines]
    cards = summaries_by_id(conn, [m.card_id for _, m in matches if m.card_id])

    lines = []
    for line, match in matches:
        status = "not_found" if match.card_id is None else ("warning" if match.warnings else "matched")
        lines.append(ImportLine(
            line_no=line.line_no,
            text=line.text,
            quantity=line.quantity,
            name=line.name,
            board=line.board,
            set_code=line.set_code,
            collector_number=line.collector_number,
            foil=line.foil,
            note=line.note,
            status=status,
            card=cards.get(match.card_id) if match.card_id else None,
            warnings=match.warnings,
            suggestions=match.suggestions,
        ))

    return ImportReport(
        meta=meta,
        lines=lines,
        errors=[ImportLineError(line_no=e.line_no, text=e.text, message=e.message) for e in parsed.errors],
        counts=ImportCounts(
            matched=sum(1 for l in lines if l.status == "matched"),
            warning=sum(1 for l in lines if l.status == "warning"),
            not_found=sum(1 for l in lines if l.status == "not_found"),
            cards=sum(l.quantity for l in lines if l.card),
        ),
    )


def commit(conn: sqlite3.Connection, request: ImportCommitRequest) -> DeckDetail:
    """Create a deck from reviewed import entries."""
    deck = service.create_deck(conn, DeckCreate(
        name=request.name, format=request.format, platform=request.platform, description=request.description,
    ))
    try:
        with conn:
            conn.execute(
                "UPDATE decks SET preferred_sets = ? WHERE id = ?",
                (json.dumps([s.lower() for s in request.preferred_sets]) if request.preferred_sets else None, deck.id),
            )
        service.replace_cards(conn, deck.id, request.entries)
        versions.save(conn, deck.id, "Import")
        return service.get_deck(conn, deck.id)
    except Exception:
        # Do not leave an empty deck behind when the entries are invalid.
        service.delete_deck(conn, deck.id)
        raise


def list_seeds(seeds_dir: Path) -> list[SeedInfo]:
    if not seeds_dir.is_dir():
        return []
    seeds = []
    for path in sorted(seeds_dir.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        name = parse_decklist(text).meta.get("name") or path.stem
        seeds.append(SeedInfo(file=path.name, name=name, text=text))
    return seeds


def _meta(raw: dict[str, str]) -> ImportMeta:
    fmt = raw.get("format", "").lower()
    platform = raw.get("platform", "").lower()
    extra = [f"{k}: {v}" for k, v in raw.items() if k not in _FIELD_KEYS]
    return ImportMeta(
        name=raw.get("name") or None,
        format=fmt if fmt in get_args(DeckFormat) else None,
        platform=platform if platform in get_args(Platform) else None,
        preferred_sets=[s.strip().lower() for s in raw.get("preferred-sets", "").split(",") if s.strip()],
        description="\n".join(extra) or None,
    )
