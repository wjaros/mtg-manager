"""What a deck needs that the collection does not have (missing = required by the deck,
by oracle id, minus owned copies of any printing; optionally not counting copies that sit in
other decks' boxes)."""

import csv
import io
import json
import sqlite3
from typing import Literal

from pydantic import BaseModel

from mtgdm.cards.models import CardSummary
from mtgdm.cards.search import card_summaries
from mtgdm.collection.service import DECK_BOX_BOARDS
from mtgdm.decks.service import DeckNotFound
from mtgdm.scryfall.bulk import META_UPDATED_AT, get_meta


class MissingEntry(BaseModel):
    oracle_id: str
    name: str
    card: CardSummary  # the printing used in the deck
    needed: int
    owned: int         # all copies in the collection
    available: int     # copies that count for this deck
    missing: int
    price_eur: float | None  # per copy, of the deck's printing
    price_usd: float | None


class MissingReport(BaseModel):
    deck_id: int
    exclude_other_decks: bool
    entries: list[MissingEntry]  # only cards with missing > 0
    missing_copies: int
    missing_cards: int
    total_eur: float
    total_usd: float
    prices_as_of: str | None


def missing_report(conn: sqlite3.Connection, deck_id: int, exclude_other_decks: bool = False) -> MissingReport:
    deck = conn.execute("SELECT id, location_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if deck is None:
        raise DeckNotFound(deck_id)

    rows = conn.execute(
        f"""
        SELECT c.oracle_id, MIN(c.name) AS name, SUM(dc.quantity) AS needed,
               -- the deck's first printing of the card represents it in the report
               (SELECT dc2.card_id FROM deck_cards dc2 JOIN cards c2 ON c2.id = dc2.card_id
                WHERE dc2.deck_id = dc.deck_id AND c2.oracle_id = c.oracle_id ORDER BY dc2.rowid LIMIT 1) AS card_id
        FROM deck_cards dc JOIN cards c ON c.id = dc.card_id
        WHERE dc.deck_id = ? AND dc.board IN ({", ".join("?" * len(DECK_BOX_BOARDS))})
        GROUP BY c.oracle_id
        """,
        (deck_id, *DECK_BOX_BOARDS),
    ).fetchall()

    # Copies stored in another deck's box are already used by that deck.
    other_boxes = {
        r[0] for r in conn.execute(
            "SELECT location_id FROM decks WHERE id != ? AND location_id IS NOT NULL", (deck_id,)
        )
    }
    owned_by_oracle: dict[str, tuple[int, int]] = {}
    for r in conn.execute(
        """
        SELECT x.oracle_id, ci.location_id, SUM(ci.quantity) AS copies
        FROM collection_items ci JOIN cards x ON x.id = ci.card_id
        GROUP BY x.oracle_id, ci.location_id
        """
    ):
        total, available = owned_by_oracle.get(r["oracle_id"], (0, 0))
        counts = not (exclude_other_decks and r["location_id"] in other_boxes)
        owned_by_oracle[r["oracle_id"]] = (total + r["copies"], available + (r["copies"] if counts else 0))

    short = []
    for r in rows:
        owned, available = owned_by_oracle.get(r["oracle_id"], (0, 0))
        missing = max(0, r["needed"] - available)
        if missing:
            short.append((r, owned, available, missing))

    summaries = {c.id: c for c in card_summaries(conn, [r["card_id"] for r, *_ in short])}
    prices = {
        row["id"]: json.loads(row["prices"] or "{}")
        for row in conn.execute(
            f"SELECT id, prices FROM card_details WHERE id IN ({', '.join('?' * len(summaries))})", list(summaries)
        )
    } if summaries else {}

    entries = []
    for r, owned, available, missing in short:
        p = prices.get(r["card_id"], {})
        entries.append(MissingEntry(
            oracle_id=r["oracle_id"],
            name=r["name"],
            card=summaries[r["card_id"]],
            needed=r["needed"],
            owned=owned,
            available=available,
            missing=missing,
            price_eur=_price(p, "eur"),
            price_usd=_price(p, "usd"),
        ))
    entries.sort(key=lambda e: e.name.lower())

    return MissingReport(
        deck_id=deck_id,
        exclude_other_decks=exclude_other_decks,
        entries=entries,
        missing_copies=sum(e.missing for e in entries),
        missing_cards=len(entries),
        total_eur=round(sum((e.price_eur or 0) * e.missing for e in entries), 2),
        total_usd=round(sum((e.price_usd or 0) * e.missing for e in entries), 2),
        prices_as_of=get_meta(conn, META_UPDATED_AT),
    )


def render_missing(report: MissingReport, fmt: str) -> str:
    """text: '1 Name (SET) 123' (importable back into the app or Arena-style tools);
    cardmarket: '1 Name' per line, any printing (Cardmarket wants list "Add decklist" box);
    csv: one row per card with set, number and prices."""
    if fmt == "cardmarket":
        return "".join(f"{e.missing} {e.name}\n" for e in report.entries)
    if fmt == "text":
        return "".join(
            f"{e.missing} {e.name} ({e.card.set_code.upper()}) {e.card.collector_number}\n" for e in report.entries
        )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["quantity", "name", "set_code", "set_name", "collector_number", "price_eur", "price_usd",
                     "scryfall_id"])
    for e in report.entries:
        writer.writerow([e.missing, e.name, e.card.set_code, e.card.set_name, e.card.collector_number,
                         e.price_eur if e.price_eur is not None else "", e.price_usd if e.price_usd is not None else "",
                         e.card.id])
    return out.getvalue()


def _price(prices: dict, currency: str) -> float | None:
    value = prices.get(currency) or prices.get(f"{currency}_foil")
    try:
        return float(value) if value else None
    except ValueError:
        return None


# --- physical availability per card (deck view) ---------------------------------------


class Holding(BaseModel):
    oracle_id: str
    needed: int         # copies in the deck (commander, companion, main, sideboard)
    owned: int          # copies in the collection, any printing, anywhere
    in_box: int | None  # copies in this deck's box; None when the deck has no box
    in_other_decks: int  # copies in other decks' boxes
    other_decks: list[str]  # names of those decks
    missing: int        # copies you don't own at all
    # Where the copies this deck lacks (beyond its box) have to come from:
    #   "missing"     you don't own enough,
    #   "other_deck"  only from another deck's box (loose / binder copies don't cover it),
    #   "elsewhere"   loose or in a binder (the deck has a box and they aren't in it),
    #   None          nothing to do.
    state: Literal["missing", "other_deck", "elsewhere"] | None


def deck_holdings(conn: sqlite3.Connection, deck_id: int) -> list[Holding]:
    """For every card of a paper deck: do you have it, and where are the copies?"""
    deck = conn.execute("SELECT location_id FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if deck is None:
        raise DeckNotFound(deck_id)
    box = deck["location_id"]
    rows = conn.execute(
        f"""
        SELECT c.oracle_id, SUM(dc.quantity) AS needed
        FROM deck_cards dc JOIN cards c ON c.id = dc.card_id
        WHERE dc.deck_id = ? AND dc.board IN ({", ".join("?" * len(DECK_BOX_BOARDS))})
        GROUP BY c.oracle_id
        """,
        (deck_id, *DECK_BOX_BOARDS),
    ).fetchall()
    # Copies per card and place: this deck's box, another deck's box (with its name), anywhere else.
    owned: dict[str, int] = {}
    in_box: dict[str, int] = {}
    in_other: dict[str, int] = {}
    other_names: dict[str, set[str]] = {}
    for r in conn.execute(
        """
        SELECT x.oracle_id, ci.location_id, d.name AS deck_name, SUM(ci.quantity) AS copies
        FROM collection_items ci
        JOIN cards x ON x.id = ci.card_id
        LEFT JOIN decks d ON d.location_id = ci.location_id AND ci.location_id IS NOT NULL
        WHERE x.oracle_id IN (SELECT c.oracle_id FROM deck_cards dc JOIN cards c ON c.id = dc.card_id WHERE dc.deck_id = ?)
        GROUP BY x.oracle_id, ci.location_id
        """,
        (deck_id,),
    ):
        oracle = r["oracle_id"]
        owned[oracle] = owned.get(oracle, 0) + r["copies"]
        if box is not None and r["location_id"] == box:
            in_box[oracle] = in_box.get(oracle, 0) + r["copies"]
        elif r["deck_name"] is not None:
            in_other[oracle] = in_other.get(oracle, 0) + r["copies"]
            other_names.setdefault(oracle, set()).add(r["deck_name"])

    holdings = []
    for r in rows:
        oracle, needed = r["oracle_id"], r["needed"]
        have, boxed, other = owned.get(oracle, 0), in_box.get(oracle, 0), in_other.get(oracle, 0)
        loose = have - boxed - other
        outside = needed - boxed  # copies to bring into the deck (all of them without a box)
        if have < needed:
            state = "missing"
        elif outside <= 0:
            state = None
        elif loose < outside:
            state = "other_deck"
        else:
            state = "elsewhere" if box is not None else None
        holdings.append(Holding(
            oracle_id=oracle,
            needed=needed,
            owned=have,
            in_box=boxed if box is not None else None,
            in_other_decks=other,
            other_decks=sorted(other_names.get(oracle, ())),
            missing=max(0, needed - have),
            state=state,
        ))
    return holdings
