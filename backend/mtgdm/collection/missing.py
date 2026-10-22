"""What a deck needs that the collection does not have (missing = required by the deck,
by oracle id, minus owned real copies of any printing; optionally not counting copies that sit in
other decks' boxes). Proxies are not owned: a proxied card is still missing (to buy), and the report
says how many of its copies a proxy in the deck's box stands in for."""

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
    proxied: int = 0   # of the missing copies, how many proxies in the deck's box stand in for
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
        WHERE ci.kind = 'real'
        GROUP BY x.oracle_id, ci.location_id
        """
    ):
        total, available = owned_by_oracle.get(r["oracle_id"], (0, 0))
        counts = not (exclude_other_decks and r["location_id"] in other_boxes)
        owned_by_oracle[r["oracle_id"]] = (total + r["copies"], available + (r["copies"] if counts else 0))

    proxies_in_box = {
        r[0]: r[1] for r in conn.execute(
            """
            SELECT x.oracle_id, SUM(ci.quantity) FROM collection_items ci JOIN cards x ON x.id = ci.card_id
            WHERE ci.kind = 'proxy' AND ci.location_id = ? GROUP BY x.oracle_id
            """,
            (deck["location_id"],),
        )
    } if deck["location_id"] is not None else {}

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
            proxied=min(missing, proxies_in_box.get(r["oracle_id"], 0)),
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


def render_missing(report: MissingReport, fmt: str, include_proxied: bool = True) -> str:
    """text: '1 Name (SET) 123' (importable back into the app or Arena-style tools);
    cardmarket: '1 Name' per line, any printing (Cardmarket wants list "Add decklist" box);
    csv: one row per card with set, number and prices.
    Without include_proxied, copies a proxy stands in for are left out (only what has no copy at all)."""
    if not include_proxied:
        entries = [e.model_copy(update={"missing": e.missing - e.proxied, "proxied": 0}) for e in report.entries]
        report = report.model_copy(update={"entries": [e for e in entries if e.missing > 0]})
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
    owned: int          # real copies in the collection, any printing, anywhere
    in_box: int | None  # real copies in this deck's box; None when the deck has no box
    in_other_decks: int  # real copies in other decks' boxes
    other_decks: list[str]  # names of those decks
    missing: int        # copies you don't own at all
    proxies: int = 0    # proxies in this deck's box
    # What the deck's copies are (real + proxy + uncovered = needed): real copies you can use (in
    # the box, loose or in a binder), proxies in the box, and the rest (not owned, or only in
    # other decks' boxes).
    real: int = 0
    proxy: int = 0
    uncovered: int = 0
    # Where the copies this deck lacks (beyond its box) have to come from:
    #   "missing"     you don't own enough (proxies included),
    #   "other_deck"  only from another deck's box (loose / binder copies don't cover it),
    #   "proxy"       proxies stand in for what's missing,
    #   "elsewhere"   loose or in a binder (the deck has a box and they aren't in it),
    #   None          nothing to do.
    state: Literal["missing", "other_deck", "proxy", "elsewhere"] | None


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
    proxies: dict[str, int] = {}
    other_names: dict[str, set[str]] = {}
    for r in conn.execute(
        """
        SELECT x.oracle_id, ci.location_id, ci.kind, d.name AS deck_name, SUM(ci.quantity) AS copies
        FROM collection_items ci
        JOIN cards x ON x.id = ci.card_id
        LEFT JOIN decks d ON d.location_id = ci.location_id AND ci.location_id IS NOT NULL
        WHERE x.oracle_id IN (SELECT c.oracle_id FROM deck_cards dc JOIN cards c ON c.id = dc.card_id WHERE dc.deck_id = ?)
        GROUP BY x.oracle_id, ci.location_id, ci.kind
        """,
        (deck_id,),
    ):
        oracle = r["oracle_id"]
        if r["kind"] == "proxy":
            # Only proxies in this deck's box stand in for its cards.
            if box is not None and r["location_id"] == box:
                proxies[oracle] = proxies.get(oracle, 0) + r["copies"]
            continue
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
        real = min(needed, boxed + loose)
        proxy = min(needed - real, proxies.get(oracle, 0))
        uncovered = needed - real - proxy
        if uncovered > 0:
            state = "missing" if have + proxy < needed else "other_deck"
        elif proxy > 0:
            state = "proxy"
        elif box is not None and boxed < needed:
            state = "elsewhere"
        else:
            state = None
        holdings.append(Holding(
            oracle_id=oracle,
            needed=needed,
            owned=have,
            in_box=boxed if box is not None else None,
            in_other_decks=other,
            other_decks=sorted(other_names.get(oracle, ())),
            missing=max(0, needed - have),
            proxies=proxies.get(oracle, 0),
            real=real,
            proxy=proxy,
            uncovered=uncovered,
            state=state,
        ))
    return holdings
