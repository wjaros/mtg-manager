"""Official preconstructed decks from MTGJSON: kept in sync, searched by deck or commander name,
and turned into a decklist for the normal import (exact printings by set and number).

A sync stores the list of every product deck (DeckList.json, ~650 KB) and fetches the cards of the
Commander decks it doesn't have yet (~200 files, once); other decks are fetched when imported."""

import json
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import BaseModel

from mtgdm.mtgjson.client import MtgjsonClient, MtgjsonError

log = logging.getLogger(__name__)

# Fetched at every sync (their commanders make them findable by commander name).
EAGER_TYPES = ("Commander Deck",)
BOARDS = (("commander", "commander"), ("mainBoard", "main"), ("sideBoard", "sideboard"))
Progress = Callable[[str, int, int], None]


class PreconNotFound(LookupError):
    pass


class PreconSummary(BaseModel):
    file_name: str
    name: str
    code: str        # set code (lower case, Scryfall style)
    set_name: str | None
    type: str
    release_date: str | None
    commanders: list[str]
    card_count: int | None
    loaded: bool     # its cards are stored (no download needed to import it)


class PreconDecklist(BaseModel):
    precon: PreconSummary
    text: str        # for the import: header lines, then sections, "1 Name (SET) 123"


def sync_precons(conn: sqlite3.Connection, client: MtgjsonClient, on_progress: Progress | None = None) -> int:
    """Store the deck list and fetch new Commander decks. Returns how many decks were fetched."""
    if on_progress:
        on_progress("precons", 0, 0)
    decks = client.get_json("DeckList.json")["data"]
    with conn:
        conn.executemany(
            """
            INSERT INTO precons(file_name, code, name, type, release_date) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(file_name) DO UPDATE SET code = excluded.code, name = excluded.name, type = excluded.type,
                release_date = excluded.release_date
            """,
            [(d["fileName"], d["code"], d["name"], d["type"], d.get("releaseDate")) for d in decks],
        )
    todo = [r[0] for r in conn.execute(
        f"SELECT file_name FROM precons WHERE loaded_at IS NULL AND type IN ({', '.join('?' * len(EAGER_TYPES))})"
        " ORDER BY release_date DESC",
        EAGER_TYPES,
    )]
    fetched = 0
    for i, file_name in enumerate(todo):
        if on_progress:
            on_progress("precons", i, len(todo))
        try:
            load_precon(conn, client, file_name)
            fetched += 1
        except MtgjsonError:  # one missing file shouldn't stop the rest; tried again next sync
            log.warning("precon %s not loaded", file_name, exc_info=True)
    if on_progress:
        on_progress("precons", len(todo), len(todo))
    return fetched


def load_precon(conn: sqlite3.Connection, client: MtgjsonClient, file_name: str) -> None:
    """Fetch and store one deck's cards."""
    if conn.execute("SELECT 1 FROM precons WHERE file_name = ?", (file_name,)).fetchone() is None:
        raise PreconNotFound(file_name)
    deck = client.get_json(f"decks/{file_name}.json")["data"]
    rows = []
    for key, board in BOARDS:
        for card in deck.get(key) or []:
            ids = card.get("identifiers") or {}
            rows.append((file_name, board, ids.get("scryfallId"), card["name"], (card.get("setCode") or "").lower(),
                         card.get("number"), int(card.get("count") or 1)))
    commanders = [c["name"] for c in deck.get("commander") or []]
    with conn:
        conn.execute("DELETE FROM precon_cards WHERE file_name = ?", (file_name,))
        conn.executemany(
            "INSERT INTO precon_cards(file_name, board, card_id, name, set_code, number, quantity)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.execute(
            "UPDATE precons SET commanders = ?, card_count = ?, loaded_at = ? WHERE file_name = ?",
            (json.dumps(commanders), sum(r[-1] for r in rows if r[1] != "sideboard"),
             datetime.now(UTC).isoformat(timespec="seconds"), file_name),
        )


def search_precons(conn: sqlite3.Connection, q: str = "", types: list[str] | None = None,
                   limit: int = 50) -> list[PreconSummary]:
    """By deck name or commander name; Commander decks and newer products first."""
    where, params = [], []
    for word in q.split():
        where.append("(p.name LIKE ? OR p.commanders LIKE ? OR p.code LIKE ?)")
        params += [f"%{word}%", f"%{word}%", word]
    if types:
        where.append(f"p.type IN ({', '.join('?' * len(types))})")
        params += types
    rows = conn.execute(
        f"""
        SELECT p.*, s.name AS set_name FROM precons p LEFT JOIN sets s ON s.code = lower(p.code)
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY p.type = 'Commander Deck' DESC, p.release_date DESC, p.name
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    return [_summary(r) for r in rows]


def get_precon(conn: sqlite3.Connection, file_name: str) -> PreconSummary:
    row = conn.execute(
        "SELECT p.*, s.name AS set_name FROM precons p LEFT JOIN sets s ON s.code = lower(p.code)"
        " WHERE p.file_name = ?",
        (file_name,),
    ).fetchone()
    if row is None:
        raise PreconNotFound(file_name)
    return _summary(row)


def precon_decklist(conn: sqlite3.Connection, client: MtgjsonClient | None, file_name: str) -> PreconDecklist:
    """The deck as import text, fetching its cards first when they aren't stored."""
    precon = get_precon(conn, file_name)
    if not precon.loaded:
        if client is None:
            raise PreconNotFound(file_name)
        load_precon(conn, client, file_name)
        precon = get_precon(conn, file_name)
    rows = conn.execute(
        """
        SELECT pc.board, pc.quantity, pc.name, COALESCE(c.set_code, pc.set_code) AS set_code,
               COALESCE(c.collector_number, pc.number) AS number
        FROM precon_cards pc LEFT JOIN cards c ON c.id = pc.card_id
        WHERE pc.file_name = ? ORDER BY pc.rowid
        """,
        (file_name,),
    ).fetchall()
    commander = precon.type == "Commander Deck"
    lines = [
        f"# name: {precon.name} ({precon.code.upper()} precon)",
        f"# format: {'commander' if commander else 'freeform'}",
        "# platform: paper",
        f"# source: MTGJSON {precon.file_name}",
    ]
    for board, title in (("commander", "Commander"), ("main", "Deck"), ("sideboard", "Sideboard")):
        section = [r for r in rows if r["board"] == board]
        if section:
            lines += ["", title]
            lines += [_line(r) for r in section]
    return PreconDecklist(precon=precon, text="\n".join(lines) + "\n")


def _line(row: sqlite3.Row) -> str:
    printing = f" ({row['set_code'].upper()}) {row['number']}" if row["set_code"] and row["number"] else ""
    return f"{row['quantity']} {row['name']}{printing}"


def _summary(row: sqlite3.Row) -> PreconSummary:
    return PreconSummary(
        file_name=row["file_name"], name=row["name"], code=row["code"].lower(), set_name=row["set_name"],
        type=row["type"], release_date=row["release_date"],
        commanders=json.loads(row["commanders"]) if row["commanders"] else [],
        card_count=row["card_count"], loaded=row["loaded_at"] is not None,
    )

