"""Products that hold several small decks (a Beginner Box's ten 20-card halves, a Starter Kit's two
decks, Jumpstart packs): grouped from the precon list, each deck previewed with its matched cards,
then imported as decks on their own or combined (two halves = one 40-card deck), optionally owned.

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

from mtgdm.collection.models import CollectionItemCreate
from mtgdm.collection.service import add_deck_to_collection, add_item, get_location
from mtgdm.decks import importer
from mtgdm.decks.models import DeckCardEntry, ImportCommitRequest, ImportLine
from mtgdm.i18n import tr
from mtgdm.mtgjson.client import MtgjsonClient
from mtgdm.mtgjson.precons import COLOR_ORDER, precon_decklist

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


class ProductDeckPlan(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    file_names: list[str] = Field(min_length=1)  # these decks' cards together make the new deck


class ProductImportRequest(BaseModel):
    decks: list[ProductDeckPlan] = Field(min_length=1)
    own: bool = False             # "I own this box": each new deck's cards into its own box location
    add_unused: bool = False      # with own: the decks no plan uses also go into the collection...
    unused_location_id: int | None = None  # ...here (none = no location)


class ProductImportResult(BaseModel):
    deck_ids: list[int]
    added: int         # copies put into the collection
    skipped: int       # copies whose card wasn't found in the card data


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
                   request: ProductImportRequest) -> ProductImportResult:
    """Create one deck per plan; with `own`, put the cards into the collection as well."""
    group = _group(conn, key)
    names = {f: name for f, name, _ in group.decks}
    used: set[str] = set()
    for plan in request.decks:
        for file_name in plan.file_names:
            if file_name not in names:
                raise ProductImportError(tr("product_deck_unknown", name=file_name))
            if file_name in used:  # a box holds each half once
                raise ProductImportError(tr("product_deck_reused", name=names[file_name]))
            used.add(file_name)
    if request.own and request.add_unused and request.unused_location_id is not None:
        get_location(conn, request.unused_location_id)  # checked before anything is created

    with_unused = request.own and request.add_unused
    decks = {f: _deck(conn, client, f, name, True) for f, name, _ in group.decks if f in used or with_unused}
    product = group.summary
    deck_ids, added, skipped = [], 0, 0
    for plan in request.decks:
        parts = [decks[f] for f in plan.file_names]
        lines = [line for part in parts for line in part.lines]
        skipped += sum(line.quantity for line in lines if line.card is None)
        deck = importer.commit(conn, ImportCommitRequest(
            name=plan.name.strip(), format="freeform", platform="paper",
            description=f"{product.name} ({product.code.upper()}): {' + '.join(p.name for p in parts)}\n"
                        f"source: MTGJSON {', '.join(plan.file_names)}",
            entries=[DeckCardEntry(card_id=line.card.id, quantity=line.quantity, board=line.board)
                     for line in lines if line.card],
        ))
        deck_ids.append(deck.id)
        if request.own:
            added += add_deck_to_collection(conn, deck.id).added

    if with_unused:
        for part in decks.values():
            if part.file_name in used:
                continue
            for line in part.lines:
                if line.card is None:
                    skipped += line.quantity
                    continue
                add_item(conn, CollectionItemCreate(
                    card_id=line.card.id, quantity=line.quantity, location_id=request.unused_location_id,
                ), source="import")
                added += line.quantity
    return ProductImportResult(deck_ids=deck_ids, added=added, skipped=skipped)


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

