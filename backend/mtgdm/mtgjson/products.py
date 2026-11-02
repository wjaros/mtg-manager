"""Products that hold several small decks (a Beginner Box's ten 20-card halves, a Starter Kit's two
decks, Jumpstart packs): grouped from the precon list, each deck previewed with its matched cards,
then imported as a box (`decks/boxes.py`) holding the chosen decks, optionally owned; combining them
into bigger decks happens in the box, any time later.

MTGJSON has no product grouping in DeckList.json (a deck file's `sealedProductUuids` would need every
file fetched), so products are guessed: decks of one set and type sharing a "Product - Deck" name
prefix (the Beginner Boxes are "Box Set" decks named "Beginner Box - Aang Tutorial"), or all decks of a
set of a type that comes several to a box or as packs (GROUP_TYPES). A product of up to EAGER_DECKS
decks is fetched whole when opened; the decks of bigger ones (Jumpstart: 121 packs) one by one."""

import re
import sqlite3
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from pydantic import BaseModel, Field

from mtgdm.decks import importer
from mtgdm.decks.boxes import BoxDetail, BoxPart, create_box
from mtgdm.decks.models import DeckCardEntry, ImportLine
from mtgdm.i18n import tr
from mtgdm.mtgjson.client import MtgjsonClient
from mtgdm.mtgjson.precons import COLOR_ORDER, _deck_stats, _owned_by_oracle, precon_decklist

GROUP_TYPES = ("Starter Kit", "Arena Starter Kit", "Spellslinger Starter Kit", "Jumpstart", "Halfdeck",
               "Game Night Deck", "Duel Deck", "Clash Pack")
# "Showcase: Kaldheim - X" are drops, not decks of one box.
NOT_PRODUCTS = ("Secret Lair Drop", "MTGO Redemption")
EAGER_DECKS = 12
GENERIC_WORDS = {"starter", "kit", "beginner", "box", "deck", "decks", "set", "pack", "packs"}
_PREFIX_SEP = " - "


class ProductNotFound(LookupError):
    pass


class ProductImportError(ValueError):
    """A plan the product can't fill (unknown or reused deck); the message is for the UI."""


class ProductSummary(BaseModel):
    key: str           # e.g. "tla-beginner-box"
    name: str          # "Beginner Box", or the deck type ("Starter Kit")
    code: str          # set code (lower case)
    set_name: str | None
    type: str
    release_date: str | None
    decks: int


class ProductOverview(BaseModel):
    product: ProductSummary
    loaded: bool         # all its decks are stored; else the numbers below are 0 (big pools: open one)
    colors: list[str]    # of all its cards, WUBRG order
    cards: int           # copies in all its decks
    owned: int           # of those, how many your real copies cover (any printing)
    price_eur: float     # the cards' value at single-card prices (not the product's price)
    box_id: int | None   # the latest box imported from it (Decks)


class ProductDeck(BaseModel):
    file_name: str
    name: str          # without the product prefix ("Aang Tutorial")
    loaded: bool       # False: not fetched yet (big products), no cards below
    cards: int         # copies in the main deck (and commander)
    colors: list[str]  # of its matched cards, WUBRG order
    lines: list[ImportLine]


class ProductDetail(BaseModel):
    product: ProductSummary
    decks: list[ProductDeck]


class ProductImportRequest(BaseModel):
    file_names: list[str] = Field(min_length=1)  # the decks to put into the box
    name: str | None = Field(default=None, max_length=200)  # default: "Beginner Box (TLA)"
    own: bool = True    # its cards go into the collection, in the box's location


@dataclass
class _Group:
    summary: ProductSummary
    decks: list[tuple[str, str, bool]] = field(default_factory=list)  # (file_name, short name, loaded)


def search_products(conn: sqlite3.Connection, q: str = "", limit: int = 50) -> list[ProductSummary]:
    """By product, set or deck name (words matched from their start, longer ones also with a typo:
    "begginer"), or set code; newest first. Words for a kind of box ("starter kit") don't rule a
    product out when the query names something else too: people call a Beginner Box a starter kit."""
    words = q.lower().split()
    specific = [w for w in words if w not in GENERIC_WORDS] or words
    found = []
    for group in _groups(conn).values():
        s = group.summary
        text = " ".join([s.name, s.set_name or "", s.type, *(name for _, name, _ in group.decks)]).lower()
        matched = {w for w in words if w == s.code or _matches(w, text)}
        if all(w in matched for w in specific):
            found.append((len(matched), s))
    # Ties: boxes before Jumpstart pools (those are boosters), then the newest.
    found.sort(key=lambda x: (x[0], x[1].type != "Jumpstart", x[1].release_date or "", x[1].name), reverse=True)
    return [s for _, s in found[:limit]]


def browse_products(conn: sqlite3.Connection) -> list[ProductOverview]:
    """Every product with what you own of it and its cards' value, newest first."""
    groups = _groups(conn)
    stats = _deck_stats(conn, None)
    owned = _owned_by_oracle(conn)
    counts = dict(conn.execute("SELECT file_name, card_count FROM precons WHERE loaded_at IS NOT NULL").fetchall())
    boxes = dict(conn.execute("SELECT product_key, MAX(id) FROM boxes GROUP BY product_key").fetchall())
    result = []
    for key, group in groups.items():
        loaded = all(is_loaded for _, _, is_loaded in group.decks)
        need: dict[str, int] = {}
        colors: set[str] = set()
        price = 0.0
        cards = 0
        if loaded:
            for file_name, _, _ in group.decks:
                s = stats.get(file_name)
                cards += counts.get(file_name) or 0
                if s is None:
                    continue
                for oracle, n in s["need"].items():
                    need[oracle] = need.get(oracle, 0) + n
                colors |= s["card_colors"]
                price += s["price"]
        result.append(ProductOverview(
            product=group.summary, loaded=loaded, colors=[c for c in COLOR_ORDER if c in colors], cards=cards,
            owned=sum(min(n, owned.get(oracle, 0)) for oracle, n in need.items()), price_eur=round(price, 2),
            box_id=boxes.get(key),
        ))
    result.sort(key=lambda o: (o.product.release_date or "", o.product.name), reverse=True)
    return result


def small_product_files(conn: sqlite3.Connection) -> list[str]:
    """Decks not stored yet of the products opened whole (up to EAGER_DECKS decks): fetched at sync, so
    the box list shows their value and what you own."""
    return [f for group in _groups(conn).values() if len(group.decks) <= EAGER_DECKS
            for f, _, is_loaded in group.decks if not is_loaded]


def get_product(conn: sqlite3.Connection, client: MtgjsonClient | None, key: str) -> ProductDetail:
    """The product's decks with their cards matched like an import. A small product's missing decks are
    fetched from MTGJSON; a big one's stay unloaded until asked for (get_product_deck)."""
    group = _group(conn, key)
    fetch = len(group.decks) <= EAGER_DECKS
    return ProductDetail(
        product=group.summary,
        decks=[_deck(conn, client, file_name, name, loaded or fetch) for file_name, name, loaded in group.decks],
    )


def get_product_deck(conn: sqlite3.Connection, client: MtgjsonClient | None, key: str,
                     file_name: str) -> ProductDeck:
    """One deck of the product, fetched when not stored yet."""
    for f, name, _ in _group(conn, key).decks:
        if f == file_name:
            return _deck(conn, client, f, name, True)
    raise ProductNotFound(file_name)


def import_product(conn: sqlite3.Connection, client: MtgjsonClient | None, key: str,
                   request: ProductImportRequest) -> BoxDetail:
    """A box with these decks of the product (cards not found in the card data are left out)."""
    group = _group(conn, key)
    names = {f: name for f, name, _ in group.decks}
    file_names = list(dict.fromkeys(request.file_names))
    for file_name in file_names:
        if file_name not in names:
            raise ProductImportError(tr("product_deck_unknown", name=file_name))
    product = group.summary
    parts = []
    for file_name in file_names:
        deck = _deck(conn, client, file_name, names[file_name], True)
        parts.append(BoxPart(
            name=deck.name, description=f"{product.name} ({product.code.upper()})\nsource: MTGJSON {file_name}",
            entries=[DeckCardEntry(card_id=line.card.id, quantity=line.quantity, board=line.board)
                     for line in deck.lines if line.card],
        ))
    name = (request.name or "").strip() or f"{product.name} ({product.set_name or product.code.upper()})"
    return create_box(conn, name, parts, set_code=product.code, product_key=key, own=request.own)


def _deck(conn: sqlite3.Connection, client: MtgjsonClient | None, file_name: str, name: str,
          fetch: bool) -> ProductDeck:
    if not fetch:
        return ProductDeck(file_name=file_name, name=name, loaded=False, cards=0, colors=[], lines=[])
    report = importer.build_report(conn, precon_decklist(conn, client, file_name).text, "paper")
    colors = {c for line in report.lines if line.card for c in line.card.colors}
    return ProductDeck(
        file_name=file_name, name=name, loaded=True,
        cards=sum(line.quantity for line in report.lines if line.board in ("main", "commander")),
        colors=[c for c in COLOR_ORDER if c in colors], lines=report.lines,
    )


def _group(conn: sqlite3.Connection, key: str) -> _Group:
    group = _groups(conn).get(key)
    if group is None:
        raise ProductNotFound(key)
    return group


def _groups(conn: sqlite3.Connection) -> dict[str, _Group]:
    rows = conn.execute(
        "SELECT p.file_name, p.code, p.name, p.type, p.release_date, p.loaded_at, s.name AS set_name"
        " FROM precons p LEFT JOIN sets s ON s.code = lower(p.code) ORDER BY p.name"
    ).fetchall()
    by_prefix: dict[tuple[str, str, str], list[sqlite3.Row]] = {}
    for r in rows:
        if _PREFIX_SEP in r["name"] and r["type"] not in NOT_PRODUCTS:
            by_prefix.setdefault((r["code"], r["type"], r["name"].split(_PREFIX_SEP, 1)[0]), []).append(r)
    candidates: list[tuple[str, list[tuple[sqlite3.Row, str]]]] = []
    grouped: set[str] = set()
    for (_, _, prefix), members in by_prefix.items():
        if len(members) >= 2:
            candidates.append((prefix, [(r, r["name"][len(prefix) + len(_PREFIX_SEP):]) for r in members]))
            grouped.update(r["file_name"] for r in members)
    by_type: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for r in rows:
        if r["type"] in GROUP_TYPES and r["file_name"] not in grouped:
            by_type.setdefault((r["code"], r["type"]), []).append(r)
    for (_, deck_type), members in by_type.items():
        if len(members) >= 2:
            candidates.append((deck_type, [(r, r["name"]) for r in members]))

    groups: dict[str, _Group] = {}
    for name, members in candidates:
        first = members[0][0]
        key = _slug(f"{first['code']} {name}")
        if key in groups:
            key = _slug(f"{first['code']} {name} {first['type']}")
        groups[key] = _Group(
            summary=ProductSummary(
                key=key, name=name, code=first["code"].lower(), set_name=first["set_name"], type=first["type"],
                release_date=max((r["release_date"] or "" for r, _ in members), default="") or None,
                decks=len(members),
            ),
            decks=[(r["file_name"], short, r["loaded_at"] is not None) for r, short in members],
        )
    return groups


def _matches(word: str, text: str) -> bool:
    if re.search(rf"(?<![a-z0-9]){re.escape(word)}", text):
        return True
    return len(word) >= 5 and any(
        abs(len(t) - len(word)) <= 2 and SequenceMatcher(None, word, t).ratio() >= 0.8
        for t in re.findall(r"[a-z0-9']+", text)
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

