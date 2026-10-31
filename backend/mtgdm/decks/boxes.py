"""Boxes of small decks (a Beginner Box's ten 20-card decks, Jumpstart packs): a container in the decks
list holding its own decks ("parts", imported from the product and kept as they are) and the decks
combined from them at any time (two halves = a 40-card deck). A combined deck is a copy of its parts'
cards, edited on its own; the parts stay. When owned, all the box's cards sit in the box's location
(kind 'box'): its decks have no location of their own, so the copies count once and "I own this
deck" doesn't apply to them (it would add the cards a second time)."""

import json
import sqlite3
from collections.abc import Iterable

from pydantic import BaseModel, Field

from mtgdm.collection.models import CollectionItemCreate
from mtgdm.collection.service import add_item
from mtgdm.decks import importer, service
from mtgdm.decks.models import DeckCardEntry, DeckSummary, ImportCommitRequest
from mtgdm.i18n import tr


class BoxNotFound(LookupError):
    pass


class BoxError(ValueError):
    """A request the box can't fill; the message is for the UI."""


class BoxSummary(BaseModel):
    id: int
    name: str
    set_code: str | None
    product_key: str | None
    location_id: int | None   # where its cards are in the collection (owned)
    created_at: str
    parts: int
    combined: int
    cover_card_id: str | None  # of its first part
    color_identity: list[str]  # of all its parts


class CombinedDeck(BaseModel):
    deck: DeckSummary
    part_ids: list[int]        # the parts it was made from (some may have been deleted since)


class BoxDetail(BaseModel):
    box: BoxSummary
    parts: list[DeckSummary]
    combined: list[CombinedDeck]


class BoxPart(BaseModel):
    """One of the box's own decks, for create_box."""
    name: str
    description: str | None = None
    entries: list[DeckCardEntry]


class BoxCombineRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    deck_ids: list[int] = Field(min_length=1)  # parts of the box


class BoxUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def create_box(conn: sqlite3.Connection, name: str, parts: Iterable[BoxPart], *, set_code: str | None = None,
               product_key: str | None = None, own: bool = False) -> BoxDetail:
    """A box with its parts as decks; with own, all their cards go into a new location of the box."""
    parts = list(parts)
    with conn:
        box_id = conn.execute(
            "INSERT INTO boxes(name, set_code, product_key) VALUES (?, ?, ?)", (name, set_code, product_key)
        ).lastrowid
    for part in parts:
        deck = importer.commit(conn, ImportCommitRequest(
            name=part.name, format="freeform", platform="paper", description=part.description,
            entries=part.entries,
        ))
        with conn:
            conn.execute("UPDATE decks SET box_id = ?, box_role = 'part' WHERE id = ?", (box_id, deck.id))
    if own:
        with conn:
            location_id = conn.execute("INSERT INTO locations(name, kind) VALUES (?, 'box')", (name,)).lastrowid
            conn.execute("UPDATE boxes SET location_id = ? WHERE id = ?", (location_id, box_id))
        for part in parts:
            for entry in part.entries:
                add_item(conn, CollectionItemCreate(
                    card_id=entry.card_id, quantity=entry.quantity, location_id=location_id,
                ), source="import")
    return get_box(conn, box_id)


def list_boxes(conn: sqlite3.Connection) -> list[BoxSummary]:
    rows = conn.execute("SELECT id FROM boxes ORDER BY created_at DESC, id DESC").fetchall()
    return [_summary(conn, r["id"]) for r in rows]


def get_box(conn: sqlite3.Connection, box_id: int) -> BoxDetail:
    box = _summary(conn, box_id)
    parts, combined = [], []
    for r in conn.execute(
        "SELECT id, box_role, box_parts FROM decks WHERE box_id = ? ORDER BY box_role = 'combined', id", (box_id,)
    ):
        summary = service.get_summary(conn, r["id"])
        if r["box_role"] == "combined":
            combined.append(CombinedDeck(deck=summary, part_ids=json.loads(r["box_parts"] or "[]")))
        else:
            parts.append(summary)
    return BoxDetail(box=box, parts=parts, combined=combined)


def combine(conn: sqlite3.Connection, box_id: int, request: BoxCombineRequest) -> int:
    """A new deck in the box with the cards of these parts as they are now. Returns its id."""
    _require(conn, box_id)
    ids = list(dict.fromkeys(request.deck_ids))
    rows = {r["id"]: r for r in conn.execute(
        f"SELECT id, name, box_id, box_role FROM decks WHERE id IN ({', '.join('?' * len(ids))})", ids
    )}
    for deck_id in ids:
        row = rows.get(deck_id)
        if row is None or row["box_id"] != box_id or row["box_role"] != "part":
            raise BoxError(tr("box_not_a_part"))
    entries = [
        DeckCardEntry(card_id=r["card_id"], quantity=r["quantity"], board=r["board"], category=r["category"])
        for deck_id in ids
        for r in conn.execute(
            "SELECT card_id, quantity, board, category FROM deck_cards WHERE deck_id = ? ORDER BY rowid", (deck_id,)
        )
    ]
    deck = importer.commit(conn, ImportCommitRequest(
        name=request.name.strip(), format="freeform", platform="paper",
        description=" + ".join(rows[i]["name"] for i in ids), entries=entries,
    ))
    with conn:
        conn.execute(
            "UPDATE decks SET box_id = ?, box_role = 'combined', box_parts = ? WHERE id = ?",
            (box_id, json.dumps(ids), deck.id),
        )
    return deck.id


def rename_box(conn: sqlite3.Connection, box_id: int, data: BoxUpdate) -> BoxSummary:
    _require(conn, box_id)
    with conn:
        conn.execute("UPDATE boxes SET name = ? WHERE id = ?", (data.name.strip(), box_id))
    return _summary(conn, box_id)


def delete_box(conn: sqlite3.Connection, box_id: int, with_cards: bool = False) -> None:
    """The box and all its decks; its location and cards stay in the collection unless with_cards."""
    box = _require(conn, box_id)
    with conn:
        conn.execute("DELETE FROM decks WHERE box_id = ?", (box_id,))
        conn.execute("DELETE FROM boxes WHERE id = ?", (box_id,))
        if with_cards and box["location_id"] is not None:
            conn.execute("DELETE FROM collection_items WHERE location_id = ?", (box["location_id"],))
            conn.execute("DELETE FROM locations WHERE id = ?", (box["location_id"],))


def _require(conn: sqlite3.Connection, box_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM boxes WHERE id = ?", (box_id,)).fetchone()
    if row is None:
        raise BoxNotFound(box_id)
    return row


def _summary(conn: sqlite3.Connection, box_id: int) -> BoxSummary:
    box = _require(conn, box_id)
    counts = dict(conn.execute(
        "SELECT box_role, COUNT(*) FROM decks WHERE box_id = ? GROUP BY box_role", (box_id,)
    ).fetchall())
    first = conn.execute(
        "SELECT id FROM decks WHERE box_id = ? AND box_role = 'part' ORDER BY id LIMIT 1", (box_id,)
    ).fetchone()
    identity: set[str] = set()
    for (colors,) in conn.execute(
        "SELECT DISTINCT c.color_identity FROM decks d JOIN deck_cards dc ON dc.deck_id = d.id"
        " JOIN cards c ON c.id = dc.card_id WHERE d.box_id = ? AND d.box_role = 'part' AND dc.board = 'main'",
        (box_id,),
    ):
        identity.update(json.loads(colors or "[]"))
    return BoxSummary(
        id=box["id"], name=box["name"], set_code=box["set_code"], product_key=box["product_key"],
        location_id=box["location_id"], created_at=box["created_at"],
        parts=counts.get("part", 0), combined=counts.get("combined", 0),
        cover_card_id=service.get_summary(conn, first["id"]).cover_card_id if first else None,
        color_identity=[c for c in "WUBRG" if c in identity],
    )
