"""Printed proxy PDFs (print_jobs) and marking their cards as proxies in a deck's box.

A print from a deck marks, per card of the deck, at most the copies the deck still lacks (not
covered by real copies or proxies already in its box); tokens and cards that aren't in the deck are
left out. A print without a deck marks everything it printed into the location you choose."""

import json
import sqlite3

from pydantic import BaseModel

from mtgdm.collection.missing import deck_holdings
from mtgdm.collection.models import CollectionItemCreate, Location
from mtgdm.collection.service import add_item, deck_box, get_location


class HistoryNotFound(LookupError):
    pass


class NoLocation(ValueError):
    """A print without a deck needs a location to mark its cards in."""


class PrintedCard(BaseModel):
    card_id: str
    name: str
    printing: str  # "DOM #31"
    qty: int
    faces: str     # "both" / "front"


class PrintHistory(BaseModel):
    id: int
    deck_id: int | None
    deck_name: str | None
    title: str
    paper: str
    style: str
    duplex: str
    card_count: int
    page_count: int | None
    created_at: str
    marked_at: str | None
    proxies: int  # proxies in the collection that came from this print
    items: list[PrintedCard]


class MarkRequest(BaseModel):
    location_id: int | None = None  # prints without a deck: where the proxies go
    dry_run: bool = False


class MarkResult(BaseModel):
    location: Location | None
    cards: list[PrintedCard]  # what is (or would be) marked
    count: int


def record_print(conn: sqlite3.Connection, *, deck_id: int | None, profile_id: int | None, title: str, paper: str,
                 style: str, duplex: str, items: list[dict]) -> int:
    with conn:
        return conn.execute(
            """
            INSERT INTO print_jobs(deck_id, profile_id, title, paper, style, duplex, items, card_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (deck_id, profile_id, title, paper, style, duplex, json.dumps(items), sum(i["qty"] for i in items)),
        ).lastrowid


def set_page_count(conn: sqlite3.Connection, history_id: int, pages: int) -> None:
    with conn:
        conn.execute("UPDATE print_jobs SET page_count = ? WHERE id = ?", (pages, history_id))


def list_history(conn: sqlite3.Connection, limit: int = 50) -> list[PrintHistory]:
    rows = conn.execute(
        """
        SELECT p.*, d.name AS deck_name,
               (SELECT COALESCE(SUM(quantity), 0) FROM collection_items WHERE print_job_id = p.id) AS proxies
        FROM print_jobs p LEFT JOIN decks d ON d.id = p.deck_id
        ORDER BY p.id DESC LIMIT ?
        """,
        (limit,),
    ).fetchall()
    names = _names(conn, [i["card_id"] for r in rows for i in json.loads(r["items"])])
    return [_history(r, names) for r in rows]


def get_history(conn: sqlite3.Connection, history_id: int) -> PrintHistory:
    row = conn.execute(
        """
        SELECT p.*, d.name AS deck_name,
               (SELECT COALESCE(SUM(quantity), 0) FROM collection_items WHERE print_job_id = p.id) AS proxies
        FROM print_jobs p LEFT JOIN decks d ON d.id = p.deck_id WHERE p.id = ?
        """,
        (history_id,),
    ).fetchone()
    if row is None:
        raise HistoryNotFound(history_id)
    return _history(row, _names(conn, [i["card_id"] for i in json.loads(row["items"])]))


def mark_proxies(conn: sqlite3.Connection, history_id: int, body: MarkRequest) -> MarkResult:
    """Record the printed cards as proxies: in the deck's box (only what the deck still lacks), or for
    a print without a deck in the given location."""
    history = get_history(conn, history_id)
    if history.deck_id is not None and body.location_id is None:
        holdings = {h.oracle_id: h for h in deck_holdings(conn, history.deck_id)}
        oracle_of = dict(conn.execute(
            f"SELECT id, oracle_id FROM cards WHERE id IN ({', '.join('?' * len(history.items))})",
            [i.card_id for i in history.items],
        )) if history.items else {}
        lacking = {oracle: h.uncovered for oracle, h in holdings.items()}
        cards = []
        for item in history.items:
            oracle = oracle_of.get(item.card_id)
            n = min(item.qty, lacking.get(oracle, 0))
            if n > 0:
                lacking[oracle] -= n
                cards.append(item.model_copy(update={"qty": n}))
        # The deck's box; created only when something is actually marked.
        location_id = (deck_box(conn, history.deck_id) if cards and not body.dry_run
                       else _existing_box(conn, history.deck_id))
    elif body.location_id is not None:
        location_id = get_location(conn, body.location_id).id
        cards = list(history.items)
    else:
        raise NoLocation(history_id)

    if not body.dry_run:
        for card in cards:
            add_item(conn, CollectionItemCreate(card_id=card.card_id, quantity=card.qty, location_id=location_id,
                                                kind="proxy"), print_job_id=history_id)
        with conn:
            conn.execute("UPDATE print_jobs SET marked_at = datetime('now') WHERE id = ?", (history_id,))
    return MarkResult(
        location=get_location(conn, location_id) if location_id is not None else None,
        cards=cards,
        count=sum(c.qty for c in cards),
    )


def _existing_box(conn: sqlite3.Connection, deck_id: int) -> int | None:
    row = conn.execute("SELECT location_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    return row["location_id"] if row else None


def _names(conn: sqlite3.Connection, card_ids: list[str]) -> dict[str, tuple[str, str]]:
    ids = sorted(set(card_ids))
    if not ids:
        return {}
    return {
        r["id"]: (r["name"], f"{(r['set_code'] or '').upper()} #{r['collector_number']}")
        for r in conn.execute(
            f"SELECT id, name, set_code, collector_number FROM cards WHERE id IN ({', '.join('?' * len(ids))})", ids
        )
    }


def _history(row: sqlite3.Row, names: dict[str, tuple[str, str]]) -> PrintHistory:
    items = [
        PrintedCard(card_id=i["card_id"], name=names.get(i["card_id"], ("?", ""))[0],
                    printing=names.get(i["card_id"], ("", ""))[1], qty=i["qty"], faces=i.get("faces", "both"))
        for i in json.loads(row["items"])
    ]
    return PrintHistory(
        id=row["id"], deck_id=row["deck_id"], deck_name=row["deck_name"], title=row["title"], paper=row["paper"],
        style=row["style"], duplex=row["duplex"], card_count=row["card_count"], page_count=row["page_count"],
        created_at=row["created_at"], marked_at=row["marked_at"], proxies=row["proxies"], items=items,
    )
