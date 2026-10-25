"""Cards to buy: a shopping list across decks, exported for Cardmarket's wants (whose Shopping Wizard
then finds sellers). Per card (oracle id, any printing): copies added by hand plus decks' missing copies.
Real copies added to the collection after a card was put on the list count as bought, so the list
shrinks as purchases are entered; proxies never count."""

import csv
import io
import json
import sqlite3
from typing import Literal

from pydantic import BaseModel

from mtgdm.cards.models import CardSummary
from mtgdm.cards.search import card_summaries
from mtgdm.collection.missing import _price, missing_report
from mtgdm.decks.service import CardNotFound
from mtgdm.scryfall.bulk import META_UPDATED_AT, get_meta

WantsFormat = Literal["cardmarket", "csv"]


class WantSource(BaseModel):
    deck_id: int | None  # None: added by hand
    deck_name: str | None
    quantity: int


class Want(BaseModel):
    oracle_id: str
    name: str
    card: CardSummary  # the card's default printing (image, price)
    quantity: int      # copies still to buy
    wanted: int        # copies asked for, all sources together
    owned: int         # real copies in the collection now
    sources: list[WantSource]
    price_eur: float | None  # per copy, of the default printing
    price_usd: float | None


class WantList(BaseModel):
    entries: list[Want]  # only cards still to buy, by name
    copies: int
    total_eur: float
    total_usd: float
    prices_as_of: str | None


def _owned(conn: sqlite3.Connection, oracle_ids: list[str]) -> dict[str, int]:
    if not oracle_ids:
        return {}
    return {
        r[0]: r[1] for r in conn.execute(
            f"""
            SELECT c.oracle_id, SUM(ci.quantity) FROM collection_items ci JOIN cards c ON c.id = ci.card_id
            WHERE ci.kind = 'real' AND c.oracle_id IN ({", ".join("?" * len(oracle_ids))}) GROUP BY c.oracle_id
            """,
            oracle_ids,
        )
    }


def _remaining(rows: list[sqlite3.Row], owned: int) -> int:
    # Copies added since the earliest row of the card was set are bought (owned can also go down: never negative).
    bought = max(0, owned - min(r["owned_at_add"] for r in rows))
    return max(0, sum(r["quantity"] for r in rows) - bought)


def _rows_by_card(conn: sqlite3.Connection, oracle_id: str | None = None) -> dict[str, list[sqlite3.Row]]:
    by_card: dict[str, list[sqlite3.Row]] = {}
    for r in conn.execute(
        """
        SELECT w.*, d.name AS deck_name FROM wants w LEFT JOIN decks d ON d.id = w.deck_id
        WHERE ? IS NULL OR w.oracle_id = ? ORDER BY w.deck_id IS NOT NULL, d.name COLLATE NOCASE
        """,
        (oracle_id, oracle_id),
    ):
        by_card.setdefault(r["oracle_id"], []).append(r)
    return by_card


def _drop_if_bought(conn: sqlite3.Connection, oracle_id: str) -> None:
    """A card already bought starts over when it's wanted again (its old rows would count those copies)."""
    rows = _rows_by_card(conn, oracle_id).get(oracle_id)
    if rows and _remaining(rows, _owned(conn, [oracle_id]).get(oracle_id, 0)) == 0:
        conn.execute("DELETE FROM wants WHERE oracle_id = ?", (oracle_id,))


def want_list(conn: sqlite3.Connection) -> WantList:
    by_card = _rows_by_card(conn)
    owned = _owned(conn, list(by_card))
    oracle = {
        r["oracle_id"]: r for r in conn.execute(
            f"SELECT oracle_id, name, default_card_id FROM oracle_cards WHERE oracle_id IN ({', '.join('?' * len(by_card))})",
            list(by_card),
        )
    } if by_card else {}
    pending = [
        (oracle_id, rows, _remaining(rows, owned.get(oracle_id, 0)))
        for oracle_id, rows in by_card.items() if oracle_id in oracle
    ]
    pending = [p for p in pending if p[2] > 0]

    card_ids = [oracle[o]["default_card_id"] for o, *_ in pending]
    summaries = {c.id: c for c in card_summaries(conn, card_ids)}
    prices = {
        r["id"]: json.loads(r["prices"] or "{}")
        for r in conn.execute(f"SELECT id, prices FROM card_details WHERE id IN ({', '.join('?' * len(card_ids))})", card_ids)
    } if card_ids else {}

    entries = []
    for oracle_id, rows, remaining in pending:
        card_id = oracle[oracle_id]["default_card_id"]
        if card_id not in summaries:
            continue
        p = prices.get(card_id, {})
        entries.append(Want(
            oracle_id=oracle_id,
            name=oracle[oracle_id]["name"],
            card=summaries[card_id],
            quantity=remaining,
            wanted=sum(r["quantity"] for r in rows),
            owned=owned.get(oracle_id, 0),
            sources=[WantSource(deck_id=r["deck_id"], deck_name=r["deck_name"], quantity=r["quantity"]) for r in rows],
            price_eur=_price(p, "eur"),
            price_usd=_price(p, "usd"),
        ))
    entries.sort(key=lambda e: e.name.lower())
    return WantList(
        entries=entries,
        copies=sum(e.quantity for e in entries),
        total_eur=round(sum((e.price_eur or 0) * e.quantity for e in entries), 2),
        total_usd=round(sum((e.price_usd or 0) * e.quantity for e in entries), 2),
        prices_as_of=get_meta(conn, META_UPDATED_AT),
    )


def add_want(conn: sqlite3.Connection, card_id: str, quantity: int = 1) -> None:
    """Want more copies of a card (any printing), by hand."""
    row = conn.execute("SELECT oracle_id FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None or row["oracle_id"] is None:
        raise CardNotFound(card_id)
    oracle_id = row["oracle_id"]
    with conn:
        _drop_if_bought(conn, oracle_id)
        updated = conn.execute(
            "UPDATE wants SET quantity = quantity + ? WHERE oracle_id = ? AND deck_id IS NULL", (quantity, oracle_id)
        ).rowcount
        if not updated:
            conn.execute(
                "INSERT INTO wants(oracle_id, quantity, owned_at_add) VALUES (?, ?, ?)",
                (oracle_id, quantity, _owned(conn, [oracle_id]).get(oracle_id, 0)),
            )


def reduce_want(conn: sqlite3.Connection, oracle_id: str, quantity: int = 1) -> None:
    """Want fewer copies: taken from the copies added by hand first, then from the decks'."""
    with conn:
        for r in _rows_by_card(conn, oracle_id).get(oracle_id, []):
            if quantity <= 0:
                break
            take = min(quantity, r["quantity"])
            if take == r["quantity"]:
                conn.execute("DELETE FROM wants WHERE id = ?", (r["id"],))
            else:
                conn.execute("UPDATE wants SET quantity = quantity - ? WHERE id = ?", (take, r["id"]))
            quantity -= take


def remove_want(conn: sqlite3.Connection, oracle_id: str | None = None) -> None:
    """Take a card off the list (all its copies); without an oracle id, empty the list."""
    with conn:
        conn.execute("DELETE FROM wants WHERE ? IS NULL OR oracle_id = ?", (oracle_id, oracle_id))


def add_deck_missing(
    conn: sqlite3.Connection, deck_id: int, exclude_other_decks: bool = False, include_proxied: bool = True
) -> int:
    """Put a deck's missing cards on the list (replacing what the deck added before); returns the copies."""
    report = missing_report(conn, deck_id, exclude_other_decks)
    copies = 0
    with conn:
        conn.execute("DELETE FROM wants WHERE deck_id = ?", (deck_id,))
        for e in report.entries:
            quantity = e.missing if include_proxied else e.missing - e.proxied
            if quantity <= 0:
                continue
            _drop_if_bought(conn, e.oracle_id)
            conn.execute(
                "INSERT INTO wants(oracle_id, deck_id, quantity, owned_at_add) VALUES (?, ?, ?, ?)",
                (e.oracle_id, deck_id, quantity, e.owned),
            )
            copies += quantity
    return copies


def render_wants(wants: WantList, fmt: WantsFormat) -> str:
    """cardmarket: '1 Name' per line (Cardmarket wants list "Add decklist" box); csv: one row per card."""
    if fmt == "cardmarket":
        return "".join(f"{e.quantity} {e.name}\n" for e in wants.entries)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["quantity", "name", "decks", "price_eur", "price_usd", "scryfall_id"])
    for e in wants.entries:
        writer.writerow([e.quantity, e.name, "; ".join(s.deck_name for s in e.sources if s.deck_name),
                         e.price_eur if e.price_eur is not None else "", e.price_usd if e.price_usd is not None else "",
                         e.card.id])
    return out.getvalue()


# --- backup ------------------------------------------------------------------------------


def backup_wants(conn: sqlite3.Connection) -> dict[int | None, list[dict]]:
    """Copies still to buy per source (None: by hand), as {oracle_id, name, quantity}: copies bought
    are taken off the hand-added ones first, so a restored list wants what this one still does."""
    by_card = _rows_by_card(conn)
    owned = _owned(conn, list(by_card))
    names = {r[0]: r[1] for r in conn.execute("SELECT oracle_id, name FROM oracle_cards WHERE oracle_id IN "
                                              f"({', '.join('?' * len(by_card))})", list(by_card))} if by_card else {}
    out: dict[int | None, list[dict]] = {}
    for oracle_id, rows in by_card.items():
        bought = max(0, owned.get(oracle_id, 0) - min(r["owned_at_add"] for r in rows))
        for r in rows:
            quantity = r["quantity"] - min(bought, r["quantity"])
            bought -= r["quantity"] - quantity
            if quantity > 0:
                out.setdefault(r["deck_id"], []).append(
                    {"oracle_id": oracle_id, "name": names.get(oracle_id), "quantity": quantity}
                )
    return out


def restore_wants(conn: sqlite3.Connection, entries: list[dict], deck_id: int | None) -> list[str]:
    """Add backed-up wants (by oracle id, else by name); returns the names not found. No transaction of its own."""
    missing = []
    for e in entries:
        row = conn.execute("SELECT oracle_id FROM oracle_cards WHERE oracle_id = ?", (e.get("oracle_id"),)).fetchone() \
            or conn.execute("SELECT oracle_id FROM oracle_cards WHERE name = ?", (e.get("name"),)).fetchone()
        if row is None:
            missing.append(e.get("name") or str(e.get("oracle_id")))
            continue
        oracle_id = row[0]
        updated = conn.execute(
            "UPDATE wants SET quantity = quantity + ? WHERE oracle_id = ? AND deck_id IS ?",
            (e["quantity"], oracle_id, deck_id),
        ).rowcount
        if not updated:
            conn.execute(
                "INSERT INTO wants(oracle_id, deck_id, quantity, owned_at_add) VALUES (?, ?, ?, ?)",
                (oracle_id, deck_id, e["quantity"], _owned(conn, [oracle_id]).get(oracle_id, 0)),
            )
    return missing
