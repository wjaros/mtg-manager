"""Cards to buy sent to CardTrader as a (private) wishlist: a deck's missing cards or the shopping
list, any printing. CardTrader silently leaves out lines it doesn't recognize, so the wishlist is read
back and the cards it lacks are reported. The token is kept in the local database only (meta), never
in backups."""

import sqlite3

from pydantic import BaseModel

from mtgdm.cardtrader.client import CardTraderClient
from mtgdm.collection.missing import missing_report
from mtgdm.collection.wants import want_list
from mtgdm.decks.export import arena_name
from mtgdm.decks.service import DeckNotFound
from mtgdm.scryfall.bulk import get_meta, set_meta

TOKEN_KEY = "cardtrader_token"
APP_KEY = "cardtrader_app"  # the name of the token's app, shown in the settings
NAME_LENGTH = 100


class CardTraderStatus(BaseModel):
    connected: bool
    app_name: str | None = None


class WishlistResult(BaseModel):
    id: int
    name: str
    cards: int           # cards sent
    copies: int          # copies sent
    not_found: list[str]  # cards CardTrader didn't recognize, so not on the wishlist


class NothingToSend(Exception):
    pass


def status(conn: sqlite3.Connection) -> CardTraderStatus:
    return CardTraderStatus(connected=bool(get_meta(conn, TOKEN_KEY)), app_name=get_meta(conn, APP_KEY))


def token(conn: sqlite3.Connection) -> str | None:
    return get_meta(conn, TOKEN_KEY)


def save_token(conn: sqlite3.Connection, client: CardTraderClient, value: str) -> CardTraderStatus:
    """Keep a token once CardTrader accepts it."""
    app = client.info()
    with conn:
        set_meta(conn, TOKEN_KEY, value)
        set_meta(conn, APP_KEY, str(app.get("name") or ""))
    return status(conn)


def forget_token(conn: sqlite3.Connection) -> None:
    with conn:
        conn.execute("DELETE FROM meta WHERE key IN (?, ?)", (TOKEN_KEY, APP_KEY))


def deck_lines(conn: sqlite3.Connection, deck_id: int, exclude_other_decks: bool = False,
               include_proxied: bool = True) -> tuple[str, list[tuple[int, str]]]:
    """The deck's name and its missing cards as (copies, name) lines."""
    deck = conn.execute("SELECT name FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if deck is None:
        raise DeckNotFound(deck_id)
    lines = []
    for e in missing_report(conn, deck_id, exclude_other_decks).entries:
        copies = e.missing if include_proxied else e.missing - e.proxied
        if copies > 0:
            lines.append((copies, arena_name(e.name, e.card.layout)))
    return deck["name"], lines


def wants_lines(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    return [(w.quantity, arena_name(w.name, w.card.layout)) for w in want_list(conn).entries if w.quantity > 0]


def send_wishlist(client: CardTraderClient, name: str, lines: list[tuple[int, str]]) -> WishlistResult:
    if not lines:
        raise NothingToSend
    name = name[:NAME_LENGTH]
    created = client.create_wishlist(name, "\n".join(f"{copies} {card}" for copies, card in lines))
    stored = client.wishlist(created["id"])
    found = {_key(item.get("meta_name") or "") for item in stored.get("items") or []}
    return WishlistResult(
        id=created["id"], name=stored.get("name") or name, cards=len(lines),
        copies=sum(copies for copies, _ in lines),
        not_found=[card for _, card in lines if _key(card) not in found],
    )


def _key(name: str) -> str:
    """Names compared in any case, a multi-face card by its front face (CardTrader may use either)."""
    return name.split(" // ")[0].strip().casefold()
