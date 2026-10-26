"""A deck's shopping list: the cards it lacks (no copy at all, or only a proxy in its box: still to buy),
with search links per source, a "done" tick (bought or ordered) kept per deck, and the offers the user
noted down at sellers (one of them chosen per card) for the basket planner."""

import sqlite3
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel

from mtgdm.cards.models import CardSummary
from mtgdm.collection.missing import missing_report
from mtgdm.decks.service import DeckNotFound
from mtgdm.purchase.settings import PurchaseSettings, get_settings
from mtgdm.purchase.sources import PurchaseLink, PurchaseSource, links, list_sources


class Offer(BaseModel):
    id: int
    oracle_id: str
    source_id: int | None
    seller_name: str
    price: float  # per copy, in the settings' currency
    qty_available: int | None
    url: str | None
    note: str | None
    chosen: bool


class ShoppingRow(BaseModel):
    oracle_id: str
    name: str
    card: CardSummary  # the deck's printing
    qty: int           # copies to buy
    proxied: int       # of them, copies a proxy in the deck's box stands in for
    reason: Literal["missing", "proxy"]  # proxy: every copy to buy has a proxy for now
    done: bool
    links: list[PurchaseLink]
    offers: list[Offer]  # cheapest first
    price_eur: float | None  # Scryfall's estimate per copy


class ShoppingList(BaseModel):
    deck_id: int
    deck_name: str
    rows: list[ShoppingRow]
    sources: list[PurchaseSource]  # enabled, in order
    sellers: list[str]             # sellers named before (offers, sources), for autocomplete
    settings: PurchaseSettings
    prices_as_of: str | None


class OfferNotFound(Exception):
    pass


class InvalidOfferUrl(ValueError):
    pass


def _offers(conn: sqlite3.Connection, deck_id: int) -> dict[str, list[Offer]]:
    out: dict[str, list[Offer]] = {}
    for r in conn.execute("SELECT * FROM offer_notes WHERE deck_id = ? ORDER BY price, id", (deck_id,)):
        out.setdefault(r["oracle_id"], []).append(_offer(r))
    return out


def _offer(r: sqlite3.Row) -> Offer:
    return Offer(id=r["id"], oracle_id=r["oracle_id"], source_id=r["source_id"], seller_name=r["seller_name"],
                 price=r["price"], qty_available=r["qty_available"], url=r["url"], note=r["note"],
                 chosen=bool(r["chosen"]))


def shopping_list(conn: sqlite3.Connection, deck_id: int) -> ShoppingList:
    deck = conn.execute("SELECT name FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if deck is None:
        raise DeckNotFound(deck_id)
    report = missing_report(conn, deck_id)
    done = {r[0] for r in conn.execute("SELECT oracle_id FROM shopping_done WHERE deck_id = ?", (deck_id,))}
    offers = _offers(conn, deck_id)
    sources = list_sources(conn, enabled_only=True)
    rows = [
        ShoppingRow(
            oracle_id=e.oracle_id, name=e.name, card=e.card, qty=e.missing, proxied=e.proxied,
            reason="proxy" if e.proxied >= e.missing else "missing", done=e.oracle_id in done,
            links=links(sources, e.name, e.card.layout, e.card.set_name), offers=offers.get(e.oracle_id, []),
            price_eur=e.price_eur,
        )
        for e in report.entries
    ]
    return ShoppingList(deck_id=deck_id, deck_name=deck["name"], rows=rows, sources=sources,
                        sellers=known_sellers(conn), settings=get_settings(conn), prices_as_of=report.prices_as_of)


def known_sellers(conn: sqlite3.Connection) -> list[str]:
    names: dict[str, str] = {}
    for (name,) in conn.execute(
        "SELECT name FROM purchase_sources WHERE enabled = 1 UNION ALL "
        "SELECT seller_name FROM (SELECT seller_name, MAX(updated_at) AS used FROM offer_notes "
        "GROUP BY seller_name ORDER BY used DESC)"
    ):
        names.setdefault(seller_key(name), name)
    return list(names.values())


def seller_key(name: str) -> str:
    return " ".join(name.split()).casefold()


# --- done ticks --------------------------------------------------------------------------


def _check_deck(conn: sqlite3.Connection, deck_id: int) -> None:
    if conn.execute("SELECT 1 FROM decks WHERE id = ?", (deck_id,)).fetchone() is None:
        raise DeckNotFound(deck_id)


def set_done(conn: sqlite3.Connection, deck_id: int, oracle_id: str, done: bool) -> None:
    _check_deck(conn, deck_id)
    with conn:
        if done:
            conn.execute("INSERT OR IGNORE INTO shopping_done(deck_id, oracle_id) VALUES (?, ?)", (deck_id, oracle_id))
        else:
            conn.execute("DELETE FROM shopping_done WHERE deck_id = ? AND oracle_id = ?", (deck_id, oracle_id))


def reset_done(conn: sqlite3.Connection, deck_id: int) -> None:
    _check_deck(conn, deck_id)
    with conn:
        conn.execute("DELETE FROM shopping_done WHERE deck_id = ?", (deck_id,))


# --- offers ------------------------------------------------------------------------------


def _clean_url(url: str | None) -> str | None:
    url = (url or "").strip()
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise InvalidOfferUrl(url)
    return url


def add_offer(conn: sqlite3.Connection, deck_id: int, oracle_id: str, *, price: float, seller_name: str | None = None,
              source_id: int | None = None, qty_available: int | None = None, url: str | None = None,
              note: str | None = None) -> Offer:
    """An offer seen at a seller; without a seller's name, the source's (a source that is one seller)."""
    _check_deck(conn, deck_id)
    if source_id is not None:
        source = conn.execute("SELECT name FROM purchase_sources WHERE id = ?", (source_id,)).fetchone()
        if source is None:
            source_id = None
        elif not (seller_name or "").strip():
            seller_name = source["name"]
    seller_name = " ".join((seller_name or "").split())
    if not seller_name:
        raise ValueError("seller_name")
    with conn:
        offer_id = conn.execute(
            """INSERT INTO offer_notes(deck_id, oracle_id, source_id, seller_name, price, qty_available, url, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (deck_id, oracle_id, source_id, seller_name, round(price, 2), qty_available, _clean_url(url), note),
        ).lastrowid
    return get_offer(conn, offer_id)


def get_offer(conn: sqlite3.Connection, offer_id: int) -> Offer:
    row = conn.execute("SELECT * FROM offer_notes WHERE id = ?", (offer_id,)).fetchone()
    if row is None:
        raise OfferNotFound(offer_id)
    return _offer(row)


OFFER_FIELDS = ("seller_name", "price", "qty_available", "url", "note", "source_id")


def update_offer(conn: sqlite3.Connection, offer_id: int, values: dict) -> Offer:
    get_offer(conn, offer_id)
    values = {k: v for k, v in values.items() if k in OFFER_FIELDS}
    if "url" in values:
        values["url"] = _clean_url(values["url"])
    if "seller_name" in values:
        values["seller_name"] = " ".join((values["seller_name"] or "").split())
        if not values["seller_name"]:
            raise ValueError("seller_name")
    if "price" in values:
        values["price"] = round(values["price"], 2)
    if values:
        with conn:
            conn.execute(
                f"UPDATE offer_notes SET {', '.join(f'{k} = ?' for k in values)}, updated_at = datetime('now')"
                " WHERE id = ?", [*values.values(), offer_id],
            )
    return get_offer(conn, offer_id)


def delete_offer(conn: sqlite3.Connection, offer_id: int) -> None:
    get_offer(conn, offer_id)
    with conn:
        conn.execute("DELETE FROM offer_notes WHERE id = ?", (offer_id,))


def choose_offer(conn: sqlite3.Connection, offer_id: int | None, deck_id: int | None = None,
                 oracle_id: str | None = None) -> None:
    """The offer the card is bought from (the card's other offers unchosen); None with the deck and card:
    none chosen. No transaction of its own when called with an open one."""
    if offer_id is not None:
        offer = conn.execute("SELECT deck_id, oracle_id FROM offer_notes WHERE id = ?", (offer_id,)).fetchone()
        if offer is None:
            raise OfferNotFound(offer_id)
        deck_id, oracle_id = offer["deck_id"], offer["oracle_id"]
    conn.execute("UPDATE offer_notes SET chosen = 0 WHERE deck_id = ? AND oracle_id = ? AND chosen = 1",
                 (deck_id, oracle_id))
    if offer_id is not None:
        conn.execute("UPDATE offer_notes SET chosen = 1 WHERE id = ?", (offer_id,))


def apply_choices(conn: sqlite3.Connection, deck_id: int, choices: dict[str, int | None]) -> None:
    """Choices per card (oracle id -> offer id, None: none), in one go (an accepted basket suggestion)."""
    _check_deck(conn, deck_id)
    with conn:
        for oracle_id, offer_id in choices.items():
            if offer_id is not None:
                row = conn.execute("SELECT 1 FROM offer_notes WHERE id = ? AND deck_id = ? AND oracle_id = ?",
                                   (offer_id, deck_id, oracle_id)).fetchone()
                if row is None:
                    raise OfferNotFound(offer_id)
            choose_offer(conn, offer_id, deck_id, oracle_id)


def usable(offer: Offer, qty: int) -> bool:
    """The seller has the copies needed (or didn't say how many)."""
    return offer.qty_available is None or offer.qty_available >= qty


def pick_cheapest(conn: sqlite3.Connection, deck_id: int, oracle_id: str | None = None) -> int:
    """Choose the cheapest offer (with enough copies) for one card or, without one, for every card still to
    buy; returns the cards whose choice changed. A card's current choice stays when it's as cheap."""
    shopping = shopping_list(conn, deck_id)
    choices: dict[str, int | None] = {}
    for row in shopping.rows:
        if row.done or (oracle_id is not None and row.oracle_id != oracle_id):
            continue
        candidates = [o for o in row.offers if usable(o, row.qty)]
        if not candidates:
            continue
        best = min(candidates, key=lambda o: (o.price, not o.chosen))
        if not best.chosen:
            choices[row.oracle_id] = best.id
    apply_choices(conn, deck_id, choices)
    return len(choices)


# --- backup ------------------------------------------------------------------------------


def backup_deck_shopping(conn: sqlite3.Connection, deck_id: int) -> dict:
    """Done ticks and offers of a deck; offers name their source (ids differ after a restore)."""
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM purchase_sources")}
    return {
        "done": [r[0] for r in conn.execute("SELECT oracle_id FROM shopping_done WHERE deck_id = ?", (deck_id,))],
        "offers": [
            {"oracle_id": r["oracle_id"], "source": names.get(r["source_id"]), "seller_name": r["seller_name"],
             "price": r["price"], "qty_available": r["qty_available"], "url": r["url"], "note": r["note"],
             "chosen": bool(r["chosen"])}
            for r in conn.execute("SELECT * FROM offer_notes WHERE deck_id = ? ORDER BY id", (deck_id,))
        ],
    }


def restore_deck_shopping(conn: sqlite3.Connection, deck_id: int, data: dict, source_ids: dict[str, int]) -> None:
    """No transaction of its own."""
    for oracle_id in data.get("done") or []:
        conn.execute("INSERT OR IGNORE INTO shopping_done(deck_id, oracle_id) VALUES (?, ?)", (deck_id, oracle_id))
    for o in data.get("offers") or []:
        conn.execute(
            """INSERT INTO offer_notes(deck_id, oracle_id, source_id, seller_name, price, qty_available, url, note,
                                       chosen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (deck_id, o["oracle_id"], source_ids.get(o.get("source")), o["seller_name"], o["price"],
             o.get("qty_available"), o.get("url"), o.get("note"), int(bool(o.get("chosen")))),
        )
