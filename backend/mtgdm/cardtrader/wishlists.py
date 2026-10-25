"""The shopping list as one private CardTrader wishlist, any printing. CardTrader's API can't edit a
wishlist, so each sync creates a new one and then deletes the previous one (its id kept in meta):
changes made to it on CardTrader are overwritten, cards are taken off the shopping list instead.
CardTrader silently leaves out lines it doesn't recognize, so the wishlist is read back (where cards
are named by slug: "teferi-who-slows-the-sunset") and the cards it lacks are reported. With a card
language chosen, a temporary wishlist made from the text tells CardTrader's own names of the cards (no
slug guessing); the wishlist itself is then made of items in that language, and read back to check
CardTrader kept it. The token is kept in the local database only (meta), never in backups."""

import logging
import re
import sqlite3
import unicodedata

from pydantic import BaseModel

from mtgdm.cardtrader.client import CardTraderClient, CardTraderError
from mtgdm.collection.wants import want_list
from mtgdm.decks.export import arena_name
from mtgdm.scryfall.bulk import get_meta, set_meta

log = logging.getLogger(__name__)

TOKEN_KEY = "cardtrader_token"
APP_KEY = "cardtrader_app"  # the name of the token's app, shown in the settings
WISHLIST_KEY = "cardtrader_wishlist_id"  # the wishlist the last sync created
LANGUAGE_KEY = "cardtrader_language"  # cards wanted in this language; none: any
LANGUAGES = ("en", "de", "fr", "it", "es", "pt", "jp", "ko", "ru")  # CardTrader's codes ("jp", not "ja")
NAME_LENGTH = 100


class CardTraderStatus(BaseModel):
    connected: bool
    app_name: str | None = None
    language: str | None = None  # of the cards on the wishlist; None: any


class WishlistResult(BaseModel):
    id: int
    name: str
    cards: int           # cards sent
    copies: int          # copies sent
    not_found: list[str]  # cards CardTrader didn't recognize, so not on the wishlist
    added: int = 0       # copies a deck's missing cards put on the shopping list first
    language: str | None = None  # asked for
    language_ignored: bool = False  # CardTrader didn't keep the language


class NothingToSend(Exception):
    pass


class NothingRecognized(Exception):
    pass


def status(conn: sqlite3.Connection) -> CardTraderStatus:
    return CardTraderStatus(connected=bool(get_meta(conn, TOKEN_KEY)), app_name=get_meta(conn, APP_KEY),
                            language=get_meta(conn, LANGUAGE_KEY))


def set_language(conn: sqlite3.Connection, language: str | None) -> CardTraderStatus:
    with conn:
        if language:
            set_meta(conn, LANGUAGE_KEY, language)
        else:
            conn.execute("DELETE FROM meta WHERE key = ?", (LANGUAGE_KEY,))
    return status(conn)


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
        conn.execute("DELETE FROM meta WHERE key IN (?, ?, ?, ?)", (TOKEN_KEY, APP_KEY, WISHLIST_KEY, LANGUAGE_KEY))


def wants_lines(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    """The shopping list as (copies, MTGA name, full name) lines."""
    return [(w.quantity, arena_name(w.name, w.card.layout), w.name) for w in want_list(conn).entries if w.quantity > 0]


def sync_wishlist(conn: sqlite3.Connection, client: CardTraderClient, name: str) -> WishlistResult:
    """Replace the wishlist with the shopping list; the new one is made first, so a failure leaves the
    previous one. An empty shopping list removes it (and raises NothingToSend)."""
    lines = wants_lines(conn)
    previous = get_meta(conn, WISHLIST_KEY)
    if not lines:
        if previous:
            _delete(client, int(previous))
            with conn:
                conn.execute("DELETE FROM meta WHERE key = ?", (WISHLIST_KEY,))
        raise NothingToSend
    language = get_meta(conn, LANGUAGE_KEY)
    if language:
        result = send_wishlist_in(client, name, lines, language)
    else:
        result = send_wishlist(client, name, lines)
    with conn:
        set_meta(conn, WISHLIST_KEY, str(result.id))
    if previous and int(previous) != result.id:
        _delete(client, int(previous))
    return result


def _delete(client: CardTraderClient, wishlist_id: int) -> None:
    """Already deleted on CardTrader is fine; another failure leaves an old wishlist behind, no more."""
    try:
        client.delete_wishlist(wishlist_id)
    except CardTraderError as exc:
        if exc.status != 404:
            log.warning("could not delete CardTrader wishlist %s: %s", wishlist_id, exc)


def send_wishlist(client: CardTraderClient, name: str, lines: list[tuple[int, str, str]]) -> WishlistResult:
    """Lines: (copies, name in the list, the card's full name)."""
    if not lines:
        raise NothingToSend
    name = name[:NAME_LENGTH]
    created = client.create_wishlist(name, "\n".join(f"{copies} {card}" for copies, card, _ in lines))
    stored = client.wishlist(created["id"])
    found = {_key(item.get("meta_name") or "") for item in stored.get("items") or []}
    return WishlistResult(
        id=created["id"], name=stored.get("name") or name, cards=len(lines),
        copies=sum(copies for copies, _, _ in lines),
        # A multi-face card may come back by its front face or its full name.
        not_found=[card for _, card, full in lines if not {_key(card), _key(full)} & found],
    )


def send_wishlist_in(client: CardTraderClient, name: str, lines: list[tuple[int, str, str]],
                     language: str) -> WishlistResult:
    """Cards in one language: their CardTrader names from a temporary wishlist made of the text (deleted
    at once), then the wishlist of items in that language, read back to check what CardTrader kept."""
    name = name[:NAME_LENGTH]
    text = "\n".join(f"{copies} {card}" for copies, card, _ in lines)
    probe = client.create_wishlist(f"{name[:NAME_LENGTH - 2]} …", text)
    try:
        recognized = client.wishlist(probe["id"]).get("items") or []
    finally:
        _delete(client, probe["id"])
    meta_names = {_key(item["meta_name"]): item["meta_name"] for item in recognized if item.get("meta_name")}
    sent: list[tuple[str, str]] = []  # (card, CardTrader's name)
    not_found = []
    for _, card, full in lines:
        meta_name = meta_names.get(_key(card)) or meta_names.get(_key(full))
        if meta_name:
            sent.append((card, meta_name))
        else:
            not_found.append(card)
    if not sent:
        raise NothingRecognized
    copies_of = {card: copies for copies, card, _ in lines}
    created = client.create_wishlist_items(name, [
        {"meta_name": meta_name, "quantity": copies_of[card], "language": language} for card, meta_name in sent
    ])
    stored = client.wishlist(created["id"]).get("items") or []
    kept = {item.get("meta_name") for item in stored}
    return WishlistResult(
        id=created["id"], name=name, cards=len(lines), copies=sum(copies for copies, _, _ in lines),
        not_found=not_found + [card for card, meta_name in sent if meta_name not in kept],
        language=language, language_ignored=any(item.get("language") != language for item in stored),
    )


def _key(name: str) -> str:
    """Letters and digits only, without accents or case: "Teferi, Who Slows the Sunset" and CardTrader's
    slug "teferi-who-slows-the-sunset" are alike."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", plain.lower())
