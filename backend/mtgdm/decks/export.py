"""Deck export: MTG Arena import format and the app's own text format."""

import json
import sqlite3
from typing import Literal

from mtgdm.decks import service
from mtgdm.decks.models import ExportResult
from mtgdm.i18n import tr

# Arena lists split cards by their full name and every other multi-face card by its front face.
FULL_NAME_LAYOUTS = {"split"}
COMMANDER_FORMATS = {"brawl", "standardbrawl", "commander"}

_SECTIONS = [
    ("commander", "Commander"),
    ("companion", "Companion"),
    ("main", "Deck"),
    ("sideboard", "Sideboard"),
    ("maybe", "Maybeboard"),
]


def export_deck(conn: sqlite3.Connection, deck_id: int, target: Literal["arena", "text"]) -> ExportResult:
    deck = service.get_deck(conn, deck_id)
    if target == "text":
        return _export_text(conn, deck)
    return _export_arena(conn, deck)


def _export_arena(conn: sqlite3.Connection, deck) -> ExportResult:
    warnings: list[str] = []
    unavailable: list[str] = []
    boards = ["commander", "companion", "main"]
    if deck.format not in COMMANDER_FORMATS:
        boards.append("sideboard")  # Brawl has no sideboard on Arena

    sections: dict[str, dict[str, int]] = {}
    for entry in deck.cards:
        if entry.board not in boards:
            continue
        card = entry.card
        printing = _printing(conn, card.id)
        if "arena" not in printing["games"]:
            arena = conn.execute(
                "SELECT arena_card_id FROM oracle_cards WHERE oracle_id = ?", (card.oracle_id,)
            ).fetchone()
            if arena is None or arena["arena_card_id"] is None:
                unavailable.append(card.name)
                continue
            replacement = _printing(conn, arena["arena_card_id"])
            warnings.append(tr(
                "export_swapped", name=card.name, printing=f"{card.set_code.upper()} #{card.collector_number}",
                set=replacement["set_label"], number=replacement["collector_number"],
            ))
            printing = replacement
        line = f"{_arena_name(printing)} ({printing['set_label']}) {printing['collector_number']}"
        # Two printings may map to the same Arena printing: merge their quantities.
        board_lines = sections.setdefault(entry.board, {})
        board_lines[line] = board_lines.get(line, 0) + entry.quantity

    text = _render(sections, header=[])
    return ExportResult(target="arena", text=text, warnings=warnings, unavailable=unavailable)


def _export_text(conn: sqlite3.Connection, deck) -> ExportResult:
    sections: dict[str, dict[str, int]] = {}
    for entry in deck.cards:
        card = entry.card
        line = f"{card.name} ({card.set_code.upper()}) {card.collector_number}"
        board_lines = sections.setdefault(entry.board, {})
        board_lines[line] = board_lines.get(line, 0) + entry.quantity
    preferred = conn.execute("SELECT preferred_sets FROM decks WHERE id = ?", (deck.id,)).fetchone()[0]
    header = [f"# name: {deck.name}", f"# format: {deck.format}", f"# platform: {deck.platform}"]
    if preferred:
        header.append(f"# preferred-sets: {', '.join(json.loads(preferred))}")
    return ExportResult(target="text", text=_render(sections, header), warnings=[], unavailable=[])


def _render(sections: dict[str, dict[str, int]], header: list[str]) -> str:
    blocks = ["\n".join(header)] if header else []
    for board, title in _SECTIONS:
        lines = sections.get(board)
        if lines:
            blocks.append("\n".join([title, *(f"{qty} {line}" for line, qty in lines.items())]))
    return "\n\n".join(blocks) + "\n"


def _printing(conn: sqlite3.Connection, card_id: str) -> dict:
    row = conn.execute(
        """
        SELECT c.name, c.layout, c.games, c.collector_number,
               UPPER(COALESCE(s.arena_code, c.set_code)) AS set_label
        FROM cards c LEFT JOIN sets s ON s.code = c.set_code
        WHERE c.id = ?
        """,
        (card_id,),
    ).fetchone()
    return {**dict(row), "games": json.loads(row["games"] or "[]")}


def _arena_name(printing: dict) -> str:
    name = printing["name"]
    if printing["layout"] in FULL_NAME_LAYOUTS:
        return name
    return name.split(" // ")[0]
