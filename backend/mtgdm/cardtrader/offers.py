"""The cheapest CardTrader Zero offers for a deck's shopping list, to compare with the sellers' basket.
Our printings map to CardTrader's blueprints by Scryfall id (an expansion's blueprints, by set code);
each blueprint's cheapest 25 offers are read, those of sellers shipping through CardTrader Zero kept
(not graded, not on vacation, single cards; in the chosen card language when one is set). Expansions and
blueprints are cached in memory for a day; the offers found are stored per deck (`cardtrader_quotes`).
"Send to cart" puts those offers into the user's CardTrader cart: buying stays theirs to do."""

import json
import sqlite3
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from mtgdm.cardtrader.client import MAGIC, CardTraderClient, CardTraderError
from mtgdm.cardtrader.wishlists import LANGUAGE_KEY
from mtgdm.purchase.shopping import shopping_list
from mtgdm.scryfall.bulk import get_meta

CACHE_TTL = 24 * 3600
MAX_PRINTINGS = 8  # per card: the deck's printing, then the newest paper ones

_expansions: tuple[float, dict[str, int]] | None = None   # set code -> expansion id
_blueprints: dict[int, tuple[float, dict[str, int]]] = {}  # expansion id -> scryfall id -> blueprint id


class QuoteResult(BaseModel):
    cards: int     # cards looked up
    found: int     # with enough CardTrader Zero copies
    requests: int  # offer lookups made


class CartResult(BaseModel):
    added: int           # copies put into the cart
    failed: list[str]    # cards CardTrader refused (sold out since, ...)


def clear_cache() -> None:
    global _expansions
    _expansions = None
    _blueprints.clear()


def _expansion_ids(client: CardTraderClient) -> dict[str, int]:
    global _expansions
    if _expansions is None or time.time() - _expansions[0] > CACHE_TTL:
        _expansions = (time.time(), {
            str(e["code"]).lower(): e["id"] for e in client.expansions() if e.get("game_id") == MAGIC and e.get("code")
        })
    return _expansions[1]


def _blueprint_ids(client: CardTraderClient, expansion_id: int) -> dict[str, int]:
    cached = _blueprints.get(expansion_id)
    if cached is None or time.time() - cached[0] > CACHE_TTL:
        cached = (time.time(), {b["scryfall_id"]: b["id"] for b in client.blueprints(expansion_id) if b.get("scryfall_id")})
        _blueprints[expansion_id] = cached
    return cached[1]


def _printings(conn: sqlite3.Connection, oracle_id: str, deck_card_id: str) -> list[tuple[str, str]]:
    """(scryfall id, set code) of the card's paper printings, the deck's first, then the newest."""
    rows = conn.execute(
        """SELECT id, set_code FROM cards WHERE oracle_id = ? AND digital = 0
           ORDER BY id = ? DESC, released_at DESC LIMIT ?""",
        (oracle_id, deck_card_id, MAX_PRINTINGS),
    ).fetchall()
    return [(r["id"], r["set_code"]) for r in rows]


def zero_offer(product: dict[str, Any], language: str | None) -> bool:
    user = product.get("user") or {}
    props = product.get("properties_hash") or {}
    return (bool(user.get("can_sell_via_hub")) and not product.get("graded") and not product.get("on_vacation")
            and (product.get("bundle_size") or 1) == 1 and (product.get("quantity") or 0) > 0
            and (language is None or props.get("mtg_language") == language))


def fetch_quotes(conn: sqlite3.Connection, client: CardTraderClient, deck_id: int,
                 progress: Callable[[int, int], None] = lambda done, total: None) -> QuoteResult:
    """Look up every card still to buy (not ticked done) and store its cheapest CardTrader Zero offers."""
    language = get_meta(conn, LANGUAGE_KEY)
    rows = [r for r in shopping_list(conn, deck_id).rows if not r.done]
    expansions = _expansion_ids(client) if rows else {}
    requests = found = 0
    for index, row in enumerate(rows):
        progress(index, len(rows))
        offers: list[dict[str, Any]] = []
        currency = None
        for scryfall_id, set_code in _printings(conn, row.oracle_id, row.card.id):
            expansion = expansions.get(set_code.lower())
            if expansion is None:
                continue
            blueprint = _blueprint_ids(client, expansion).get(scryfall_id)
            if blueprint is None:
                continue
            requests += 1
            for p in client.marketplace_products(blueprint, language):
                if not zero_offer(p, language):
                    continue
                price = p.get("price") or {}
                cents = price.get("cents") if isinstance(price, dict) else p.get("price_cents")
                if cents is None:
                    continue
                currency = currency or (price.get("currency") if isinstance(price, dict) else None) \
                    or p.get("price_currency")
                offers.append({"product_id": p["id"], "blueprint_id": blueprint, "quantity": p["quantity"],
                               "price_cents": int(cents), "seller": (p.get("user") or {}).get("username"),
                               "set_code": set_code})
        offers.sort(key=lambda o: o["price_cents"])
        kept, copies = [], 0
        for o in offers:
            if copies >= row.qty:
                break
            kept.append(o)
            copies += o["quantity"]
        found += copies >= row.qty
        with conn:
            conn.execute(
                """INSERT INTO cardtrader_quotes(deck_id, oracle_id, offers, currency) VALUES (?, ?, ?, ?)
                   ON CONFLICT(deck_id, oracle_id) DO UPDATE SET offers = excluded.offers,
                   currency = excluded.currency, fetched_at = datetime('now')""",
                (deck_id, row.oracle_id, json.dumps(kept), currency),
            )
    progress(len(rows), len(rows))
    return QuoteResult(cards=len(rows), found=found, requests=requests)


def send_to_cart(conn: sqlite3.Connection, client: CardTraderClient, deck_id: int, oracle_ids: list[str]) -> CartResult:
    """Put the stored offers of these cards into the CardTrader cart (via CardTrader Zero), the copies needed."""
    rows = {r.oracle_id: r for r in shopping_list(conn, deck_id).rows if not r.done}
    quotes = {r[0]: json.loads(r[1]) for r in conn.execute(
        "SELECT oracle_id, offers FROM cardtrader_quotes WHERE deck_id = ?", (deck_id,))}
    added, failed = 0, []
    for oracle_id in oracle_ids:
        row = rows.get(oracle_id)
        if row is None:
            continue
        left = row.qty
        try:
            for o in quotes.get(oracle_id, []):
                if left <= 0:
                    break
                take = min(left, o["quantity"])
                client.add_to_cart(o["product_id"], take)
                added += take
                left -= take
        except CardTraderError as exc:
            if exc.status == 401:
                raise
            failed.append(row.name)
            continue
        if left > 0:
            failed.append(row.name)
    return CartResult(added=added, failed=failed)


class QuoteJob(BaseModel):
    deck_id: int
    running: bool
    done: int = 0
    total: int = 0
    result: QuoteResult | None = None
    error: str | None = None
