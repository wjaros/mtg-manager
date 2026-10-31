"""Deck storage. deck_cards is the source of truth; decks.commander/partner/companion_card_id
are derived from the 'commander' and 'companion' boards after every change."""

import json
import sqlite3
from collections.abc import Iterable

from mtgdm.cards.search import card_summaries
from mtgdm.decks import versions
from mtgdm.decks.models import (
    Board,
    DeckCard,
    DeckCardEntry,
    DeckChanges,
    DeckCounts,
    DeckCreate,
    DeckDetail,
    DeckSummary,
    DeckUpdate,
)

COLOR_ORDER = "WUBRG"


class DeckNotFound(LookupError):
    pass


class CardNotFound(LookupError):
    pass


def list_decks(conn: sqlite3.Connection) -> list[DeckSummary]:
    rows = conn.execute("SELECT id FROM decks ORDER BY updated_at DESC, id DESC").fetchall()
    return [_summary(conn, r["id"]) for r in rows]


def get_summary(conn: sqlite3.Connection, deck_id: int) -> DeckSummary:
    return _summary(conn, deck_id)


def get_deck(conn: sqlite3.Connection, deck_id: int) -> DeckDetail:
    _require_deck(conn, deck_id)
    changes = versions.unsaved_changes(conn, deck_id)
    summary = _summary(conn, deck_id, changes)
    rows = conn.execute(
        "SELECT card_id, quantity, board, category FROM deck_cards WHERE deck_id = ? ORDER BY rowid",
        (deck_id,),
    ).fetchall()
    cards = {c.id: c for c in card_summaries(conn, list({r["card_id"] for r in rows}))}
    return DeckDetail(
        **summary.model_dump(),
        cards=[
            DeckCard(card=cards[r["card_id"]], quantity=r["quantity"], board=r["board"], category=r["category"])
            for r in rows
            if r["card_id"] in cards
        ],
        changes=changes,
    )


def create_deck(conn: sqlite3.Connection, data: DeckCreate) -> DeckDetail:
    with conn:
        deck_id = conn.execute(
            "INSERT INTO decks(name, format, platform, description) VALUES (?, ?, ?, ?)",
            (data.name.strip(), data.format, data.platform, data.description),
        ).lastrowid
    return get_deck(conn, deck_id)


def update_deck(conn: sqlite3.Connection, deck_id: int, data: DeckUpdate) -> DeckDetail:
    _require_deck(conn, deck_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is not None:
        changes["name"] = changes["name"].strip()
    changes = {k: v for k, v in changes.items() if v is not None or k == "description"}
    if changes:
        with conn:
            assignments = ", ".join(f"{k} = ?" for k in changes)
            conn.execute(
                f"UPDATE decks SET {assignments}, updated_at = datetime('now') WHERE id = ?",
                [*changes.values(), deck_id],
            )
    return get_deck(conn, deck_id)


def delete_deck(conn: sqlite3.Connection, deck_id: int, with_cards: bool = False) -> None:
    """Delete a deck; its box location and the copies in it stay in the collection, unless
    with_cards: then the box's copies (real and proxies) go too, and the box itself
    (kept when another deck uses the same location)."""
    with conn:
        row = conn.execute("SELECT location_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
        if row is None:
            raise DeckNotFound(deck_id)
        conn.execute("DELETE FROM decks WHERE id = ?", (deck_id,))
        location_id = row["location_id"]
        if with_cards and location_id is not None:
            conn.execute("DELETE FROM collection_items WHERE location_id = ?", (location_id,))
            if not conn.execute("SELECT 1 FROM decks WHERE location_id = ?", (location_id,)).fetchone():
                conn.execute("DELETE FROM locations WHERE id = ?", (location_id,))


def add_card(conn: sqlite3.Connection, deck_id: int, card_id: str, quantity: int, board: Board) -> DeckDetail:
    _require_deck(conn, deck_id)
    _require_cards(conn, [card_id])
    with conn:
        conn.execute(
            """
            INSERT INTO deck_cards(deck_id, card_id, quantity, board) VALUES (?, ?, ?, ?)
            ON CONFLICT(deck_id, card_id, board) DO UPDATE SET quantity = quantity + excluded.quantity
            """,
            (deck_id, card_id, quantity, board),
        )
        _after_change(conn, deck_id)
    return get_deck(conn, deck_id)


def remove_card(
    conn: sqlite3.Connection, deck_id: int, card_id: str, board: Board, quantity: int | None
) -> DeckDetail:
    """Remove `quantity` copies (all copies when None)."""
    _require_deck(conn, deck_id)
    with conn:
        row = conn.execute(
            "SELECT quantity FROM deck_cards WHERE deck_id = ? AND card_id = ? AND board = ?",
            (deck_id, card_id, board),
        ).fetchone()
        if row is None:
            raise CardNotFound(card_id)
        if quantity is None or quantity >= row["quantity"]:
            conn.execute(
                "DELETE FROM deck_cards WHERE deck_id = ? AND card_id = ? AND board = ?", (deck_id, card_id, board)
            )
        else:
            conn.execute(
                "UPDATE deck_cards SET quantity = quantity - ? WHERE deck_id = ? AND card_id = ? AND board = ?",
                (quantity, deck_id, card_id, board),
            )
        _after_change(conn, deck_id)
    return get_deck(conn, deck_id)


def update_card(
    conn: sqlite3.Connection,
    deck_id: int,
    card_id: str,
    board: Board,
    *,
    new_board: Board | None = None,
    quantity: int | None = None,
    new_card_id: str | None = None,
    category: str | None = None,
) -> DeckDetail:
    """Move an entry to another board, change its quantity or swap it for another printing.
    If the target entry already exists, quantities are merged."""
    _require_deck(conn, deck_id)
    if new_card_id:
        _require_cards(conn, [new_card_id])
    with conn:
        row = conn.execute(
            "SELECT quantity, category FROM deck_cards WHERE deck_id = ? AND card_id = ? AND board = ?",
            (deck_id, card_id, board),
        ).fetchone()
        if row is None:
            raise CardNotFound(card_id)
        target_card = new_card_id or card_id
        target_board = new_board or board
        target_qty = quantity or row["quantity"]
        if category is not None:
            conn.execute(
                "UPDATE deck_cards SET category = ? WHERE deck_id = ? AND card_id = ? AND board = ?",
                (category.strip() or None, deck_id, card_id, board),
            )
            row = conn.execute(
                "SELECT quantity, category FROM deck_cards WHERE deck_id = ? AND card_id = ? AND board = ?",
                (deck_id, card_id, board),
            ).fetchone()
        if (target_card, target_board) == (card_id, board):
            conn.execute(
                "UPDATE deck_cards SET quantity = ? WHERE deck_id = ? AND card_id = ? AND board = ?",
                (target_qty, deck_id, card_id, board),
            )
        else:
            conn.execute(
                "DELETE FROM deck_cards WHERE deck_id = ? AND card_id = ? AND board = ?", (deck_id, card_id, board)
            )
            conn.execute(
                """
                INSERT INTO deck_cards(deck_id, card_id, quantity, board, category) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(deck_id, card_id, board) DO UPDATE SET quantity = quantity + excluded.quantity
                """,
                (deck_id, target_card, target_qty, target_board, row["category"]),
            )
        _after_change(conn, deck_id)
    return get_deck(conn, deck_id)


def replace_cards(conn: sqlite3.Connection, deck_id: int, entries: Iterable[DeckCardEntry]) -> DeckDetail:
    """Bulk replace the deck's contents (entries for the same card and board are summed)."""
    _require_deck(conn, deck_id)
    merged: dict[tuple[str, str], DeckCardEntry] = {}
    for e in entries:
        key = (e.card_id, e.board)
        if key in merged:
            merged[key] = merged[key].model_copy(update={"quantity": merged[key].quantity + e.quantity})
        else:
            merged[key] = e
    _require_cards(conn, [e.card_id for e in merged.values()])
    with conn:
        conn.execute("DELETE FROM deck_cards WHERE deck_id = ?", (deck_id,))
        conn.executemany(
            "INSERT INTO deck_cards(deck_id, card_id, quantity, board, category) VALUES (?, ?, ?, ?, ?)",
            [(deck_id, e.card_id, e.quantity, e.board, e.category) for e in merged.values()],
        )
        _after_change(conn, deck_id)
    return get_deck(conn, deck_id)


def restore_version(conn: sqlite3.Connection, deck_id: int, version_id: int) -> DeckDetail:
    """Make a saved version the working copy again (cards, format, platform). Not saved as a new
    version: the difference to the latest version shows as unsaved changes."""
    _require_deck(conn, deck_id)
    row, entries = versions.snapshot(conn, deck_id, version_id)
    with conn:
        conn.execute("UPDATE decks SET format = ?, platform = ? WHERE id = ?", (row["format"], row["platform"], deck_id))
    existing = {r[0] for r in conn.execute(
        f"SELECT id FROM cards WHERE id IN ({', '.join('?' * len(entries))})", [e["card_id"] for e in entries]
    )} if entries else set()
    return replace_cards(conn, deck_id, [DeckCardEntry(**e) for e in entries if e["card_id"] in existing])


def _after_change(conn: sqlite3.Connection, deck_id: int) -> None:
    commanders = [r[0] for r in conn.execute(
        "SELECT card_id FROM deck_cards WHERE deck_id = ? AND board = 'commander' ORDER BY rowid LIMIT 2",
        (deck_id,),
    )]
    companion = conn.execute(
        "SELECT card_id FROM deck_cards WHERE deck_id = ? AND board = 'companion' ORDER BY rowid LIMIT 1",
        (deck_id,),
    ).fetchone()
    conn.execute(
        """
        UPDATE decks SET commander_card_id = ?, partner_card_id = ?, companion_card_id = ?,
                         updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            commanders[0] if commanders else None,
            commanders[1] if len(commanders) > 1 else None,
            companion[0] if companion else None,
            deck_id,
        ),
    )


def _summary(conn: sqlite3.Connection, deck_id: int, changes: DeckChanges | None = None) -> DeckSummary:
    deck = conn.execute(
        "SELECT d.*, b.name AS box_name FROM decks d LEFT JOIN boxes b ON b.id = d.box_id WHERE d.id = ?", (deck_id,)
    ).fetchone()
    if deck is None:
        raise DeckNotFound(deck_id)
    changes = changes or versions.unsaved_changes(conn, deck_id)
    counts = {b: 0 for b in ("main", "commander", "companion", "sideboard", "maybe")}
    for r in conn.execute(
        "SELECT board, SUM(quantity) FROM deck_cards WHERE deck_id = ? GROUP BY board", (deck_id,)
    ):
        counts[r[0]] = r[1]

    identity: set[str] = set()
    names = []
    for commander_id in (deck["commander_card_id"], deck["partner_card_id"]):
        row = commander_id and conn.execute(
            "SELECT name, color_identity FROM cards WHERE id = ?", (commander_id,)
        ).fetchone()
        if row:
            names.append(row["name"])
            identity.update(json.loads(row["color_identity"] or "[]"))
    if not names:
        for row in conn.execute(
            "SELECT DISTINCT c.color_identity FROM deck_cards dc JOIN cards c ON c.id = dc.card_id "
            "WHERE dc.deck_id = ? AND dc.board = 'main'",
            (deck_id,),
        ):
            identity.update(json.loads(row[0] or "[]"))

    return DeckSummary(
        id=deck["id"],
        name=deck["name"],
        format=deck["format"],
        platform=deck["platform"],
        description=deck["description"],
        commander_card_id=deck["commander_card_id"],
        partner_card_id=deck["partner_card_id"],
        companion_card_id=deck["companion_card_id"],
        commander_name=" & ".join(names) or None,
        cover_card_id=deck["commander_card_id"] or deck["companion_card_id"] or _cover_card(conn, deck_id),
        color_identity=[c for c in COLOR_ORDER if c in identity],
        location_id=deck["location_id"],
        box_id=deck["box_id"],
        box_role=deck["box_role"],
        box_name=deck["box_name"],
        counts=DeckCounts(**counts, total=counts["main"] + counts["commander"]),
        unsaved_changes=len(changes.cards) + bool(changes.format_before) + bool(changes.platform_before),
        created_at=deck["created_at"],
        updated_at=deck["updated_at"],
    )


def _cover_card(conn: sqlite3.Connection, deck_id: int) -> str | None:
    """The deck's face without a commander: a legendary creature or planeswalker if there is one,
    then the costliest creature / planeswalker, then the costliest other nonland card."""
    row = conn.execute(
        """
        SELECT dc.card_id FROM deck_cards dc JOIN cards c ON c.id = dc.card_id
        WHERE dc.deck_id = ? AND dc.board = 'main'
        ORDER BY c.type_line LIKE '%Land%' AND c.type_line NOT LIKE '%Creature%',
                 c.type_line LIKE '%Legendary%' AND (c.type_line LIKE '%Creature%' OR c.type_line LIKE '%Planeswalker%') DESC,
                 c.type_line LIKE '%Creature%' OR c.type_line LIKE '%Planeswalker%' DESC,
                 c.cmc DESC, dc.quantity DESC, dc.rowid
        LIMIT 1
        """,
        (deck_id,),
    ).fetchone()
    return row[0] if row else None


def _require_deck(conn: sqlite3.Connection, deck_id: int) -> None:
    if conn.execute("SELECT 1 FROM decks WHERE id = ?", (deck_id,)).fetchone() is None:
        raise DeckNotFound(deck_id)


def _require_cards(conn: sqlite3.Connection, card_ids: list[str]) -> None:
    if not card_ids:
        return
    found = {r[0] for r in conn.execute(
        f"SELECT id FROM cards WHERE id IN ({', '.join('?' * len(card_ids))})", card_ids
    )}
    missing = set(card_ids) - found
    if missing:
        raise CardNotFound(", ".join(sorted(missing)))
