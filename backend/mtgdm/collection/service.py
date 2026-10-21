"""Physical collection: copies of printings, optionally stored in a location (deck box, binder...)."""

import json
import sqlite3

from mtgdm.cards.search import card_summaries
from mtgdm.collection.models import (
    CollectionItem,
    CollectionItemCreate,
    CollectionItemUpdate,
    CollectionStats,
    DeckToCollectionResult,
    Location,
    LocationCreate,
    LocationUpdate,
)
from mtgdm.decks.service import CardNotFound, DeckNotFound

# Boards whose cards physically sit in the deck box.
DECK_BOX_BOARDS = ("commander", "companion", "main", "sideboard")


class ItemNotFound(LookupError):
    pass


class LocationNotFound(LookupError):
    pass


class LocationNotEmpty(Exception):
    pass


# --- locations ----------------------------------------------------------------


def list_locations(conn: sqlite3.Connection) -> list[Location]:
    rows = conn.execute(
        """
        SELECT l.id, l.name, l.kind, COALESCE(SUM(ci.quantity), 0) AS card_count
        FROM locations l LEFT JOIN collection_items ci ON ci.location_id = l.id
        GROUP BY l.id ORDER BY l.kind, l.name COLLATE NOCASE
        """
    ).fetchall()
    return [Location(**dict(r)) for r in rows]


def get_location(conn: sqlite3.Connection, location_id: int) -> Location:
    row = conn.execute(
        """
        SELECT l.id, l.name, l.kind,
               (SELECT COALESCE(SUM(quantity), 0) FROM collection_items WHERE location_id = l.id) AS card_count
        FROM locations l WHERE l.id = ?
        """,
        (location_id,),
    ).fetchone()
    if row is None:
        raise LocationNotFound(location_id)
    return Location(**dict(row))


def create_location(conn: sqlite3.Connection, data: LocationCreate) -> Location:
    with conn:
        location_id = conn.execute(
            "INSERT INTO locations(name, kind) VALUES (?, ?)", (data.name.strip(), data.kind)
        ).lastrowid
    return get_location(conn, location_id)


def update_location(conn: sqlite3.Connection, location_id: int, data: LocationUpdate) -> Location:
    get_location(conn, location_id)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if changes:
        with conn:
            conn.execute(
                f"UPDATE locations SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                [*changes.values(), location_id],
            )
    return get_location(conn, location_id)


def delete_location(conn: sqlite3.Connection, location_id: int) -> None:
    """Delete a location; its cards stay in the collection without a location."""
    with conn:
        if conn.execute("DELETE FROM locations WHERE id = ?", (location_id,)).rowcount == 0:
            raise LocationNotFound(location_id)


# --- items --------------------------------------------------------------------


def list_items(
    conn: sqlite3.Connection,
    *,
    card_id: str | None = None,
    oracle_id: str | None = None,
    location_id: int | None = None,
    unassigned: bool = False,
    q: str | None = None,
) -> list[CollectionItem]:
    where, params = [], []
    if card_id:
        where.append("ci.card_id = ?")
        params.append(card_id)
    if oracle_id:
        where.append("c.oracle_id = ?")
        params.append(oracle_id)
    if location_id is not None:
        where.append("ci.location_id = ?")
        params.append(location_id)
    if unassigned:
        where.append("ci.location_id IS NULL")
    if q:
        where.append("c.name LIKE ?")
        params.append(f"%{q.strip()}%")
    rows = conn.execute(
        f"""
        SELECT ci.* FROM collection_items ci JOIN cards c ON c.id = ci.card_id
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY c.name COLLATE NOCASE, c.released_at DESC, ci.id
        """,
        params,
    ).fetchall()
    return _items(conn, rows)


def get_item(conn: sqlite3.Connection, item_id: int) -> CollectionItem:
    row = conn.execute("SELECT * FROM collection_items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise ItemNotFound(item_id)
    return _items(conn, [row])[0]


def add_item(conn: sqlite3.Connection, data: CollectionItemCreate, source: str = "manual") -> CollectionItem:
    """Add copies; merges into an existing identical entry (same printing, finish, language,
    condition and location)."""
    card = conn.execute("SELECT lang, finishes FROM cards WHERE id = ?", (data.card_id,)).fetchone()
    if card is None:
        raise CardNotFound(data.card_id)
    if data.location_id is not None:
        get_location(conn, data.location_id)
    finishes = json.loads(card["finishes"] or '["nonfoil"]')
    finish = data.finish or ("nonfoil" if "nonfoil" in finishes or not finishes else finishes[0])
    language = data.language or card["lang"]

    with conn:
        existing = conn.execute(
            """
            SELECT id FROM collection_items
            WHERE card_id = ? AND finish = ? AND language = ? AND condition = ? AND location_id IS ?
            """,
            (data.card_id, finish, language, data.condition, data.location_id),
        ).fetchone()
        if existing:
            item_id = existing["id"]
            conn.execute(
                "UPDATE collection_items SET quantity = quantity + ?, updated_at = datetime('now') WHERE id = ?",
                (data.quantity, item_id),
            )
        else:
            item_id = conn.execute(
                """
                INSERT INTO collection_items(card_id, quantity, finish, language, condition, location_id, source, note)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (data.card_id, data.quantity, finish, language, data.condition, data.location_id, source, data.note),
            ).lastrowid
    return get_item(conn, item_id)


def update_item(conn: sqlite3.Connection, item_id: int, data: CollectionItemUpdate) -> CollectionItem:
    get_item(conn, item_id)
    changes = data.model_dump(exclude_unset=True)
    # location_id and note may be cleared with null; other fields ignore null.
    changes = {k: v for k, v in changes.items() if v is not None or k in ("location_id", "note")}
    if changes.get("location_id") is not None:
        get_location(conn, changes["location_id"])
    if changes:
        with conn:
            conn.execute(
                f"UPDATE collection_items SET {', '.join(f'{k} = ?' for k in changes)}, updated_at = datetime('now')"
                " WHERE id = ?",
                [*changes.values(), item_id],
            )
    return get_item(conn, item_id)


def remove_item(conn: sqlite3.Connection, item_id: int, quantity: int | None = None) -> CollectionItem | None:
    """Remove `quantity` copies (all when None). Returns the remaining entry, or None if gone."""
    item = get_item(conn, item_id)
    with conn:
        if quantity is None or quantity >= item.quantity:
            conn.execute("DELETE FROM collection_items WHERE id = ?", (item_id,))
            return None
        conn.execute(
            "UPDATE collection_items SET quantity = quantity - ?, updated_at = datetime('now') WHERE id = ?",
            (quantity, item_id),
        )
    return get_item(conn, item_id)


def stats(conn: sqlite3.Connection) -> CollectionStats:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(ci.quantity), 0), COUNT(DISTINCT ci.card_id), COUNT(DISTINCT c.oracle_id)
        FROM collection_items ci JOIN cards c ON c.id = ci.card_id
        """
    ).fetchone()
    return CollectionStats(copies=row[0], printings=row[1], cards=row[2])


def add_deck_to_collection(conn: sqlite3.Connection, deck_id: int, replace: bool = False) -> DeckToCollectionResult:
    """'I own this deck': put its cards into the collection, in the deck's own box location.
    With replace, the box is emptied first (re-sync after the decklist changed)."""
    deck = conn.execute("SELECT id, name, location_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if deck is None:
        raise DeckNotFound(deck_id)
    location_id = deck["location_id"]
    with conn:
        if location_id is None:
            location_id = conn.execute(
                "INSERT INTO locations(name, kind) VALUES (?, 'deck')", (deck["name"],)
            ).lastrowid
            conn.execute("UPDATE decks SET location_id = ? WHERE id = ?", (location_id, deck_id))
        has_items = conn.execute(
            "SELECT 1 FROM collection_items WHERE location_id = ? LIMIT 1", (location_id,)
        ).fetchone()
        if has_items and not replace:
            raise LocationNotEmpty(location_id)
        if replace:
            conn.execute("DELETE FROM collection_items WHERE location_id = ?", (location_id,))

    entries = conn.execute(
        f"""
        SELECT card_id, SUM(quantity) AS quantity FROM deck_cards
        WHERE deck_id = ? AND board IN ({", ".join("?" * len(DECK_BOX_BOARDS))})
        GROUP BY card_id ORDER BY MIN(rowid)
        """,
        (deck_id, *DECK_BOX_BOARDS),
    ).fetchall()
    added = 0
    for entry in entries:
        add_item(
            conn,
            CollectionItemCreate(card_id=entry["card_id"], quantity=entry["quantity"], location_id=location_id),
            source="import",
        )
        added += entry["quantity"]
    return DeckToCollectionResult(location=get_location(conn, location_id), added=added)


def _items(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[CollectionItem]:
    cards = {c.id: c for c in card_summaries(conn, list({r["card_id"] for r in rows}))}
    locations = {loc.id: loc for loc in list_locations(conn)} if any(r["location_id"] for r in rows) else {}
    return [
        CollectionItem(
            id=r["id"],
            card=cards[r["card_id"]],
            quantity=r["quantity"],
            finish=r["finish"],
            language=r["language"],
            condition=r["condition"],
            location=locations.get(r["location_id"]),
            source=r["source"],
            note=r["note"],
        )
        for r in rows
        if r["card_id"] in cards
    ]
