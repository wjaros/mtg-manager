"""Two decks side by side, card by card. Cards are compared by name (oracle id), so a paper printing
and an Arena one are alike; the commander, main deck and companion count, the sideboard and
maybeboard don't. For each card and each deck: whether the card could go into that deck (legal in its
format, within its commander's color identity, on its platform) and how many copies the other deck
has that it could take, within the format's copy limit."""

import json
import sqlite3

from pydantic import BaseModel

from mtgdm.cards.models import CardSummary
from mtgdm.cards.search import card_summaries, owned_printings
from mtgdm.collection.missing import _price
from mtgdm.decks.service import DeckNotFound
from mtgdm.decks.validation import Entry, allowed_copies, load_entries
from mtgdm.scryfall.bulk import META_UPDATED_AT, get_meta

COUNTED = ("commander", "main", "companion")


class DeckSide(BaseModel):
    id: int
    name: str
    format: str
    platform: str
    color_identity: list[str] | None  # the commander's; None without a commander


class CardFit(BaseModel):
    """A card as seen from one deck."""

    legal: bool        # in the deck's format
    in_identity: bool  # within the commander's color identity (always, without a commander)
    on_platform: bool  # Arena decks: the card is on Arena
    addable: int       # copies of the other deck's that could be added here
    card_id: str | None  # the printing to add: Arena's for an Arena deck, else the one owned most, else default


class CompareRow(BaseModel):
    oracle_id: str
    name: str
    card: CardSummary  # for the preview: the first deck's printing, else the second's
    a: int  # copies in the first deck
    b: int
    price_eur: float | None  # per copy: that printing's, else the card's default printing's
    fit_a: CardFit
    fit_b: CardFit


class DeckComparison(BaseModel):
    a: DeckSide
    b: DeckSide
    rows: list[CompareRow]  # every card of either deck
    prices_as_of: str | None


def compare_decks(conn: sqlite3.Connection, deck_a: int, deck_b: int) -> DeckComparison:
    side_a, entries_a = _side(conn, deck_a)
    side_b, entries_b = _side(conn, deck_b)
    copies_a, copies_b = _copies(entries_a), _copies(entries_b)
    first: dict[str, Entry] = {}  # oracle id -> an entry (A's first): the card's data and printing
    for e in [*entries_a, *entries_b]:
        if e.board in COUNTED:
            first.setdefault(e.oracle_id, e)
    oracle_ids = list(first)
    if not oracle_ids:
        return DeckComparison(a=side_a, b=side_b, rows=[], prices_as_of=get_meta(conn, META_UPDATED_AT))

    marks = ", ".join("?" * len(oracle_ids))
    oracle = {r["oracle_id"]: r for r in conn.execute(
        f"""SELECT o.oracle_id, o.default_card_id, o.arena_card_id,
                   EXISTS (SELECT 1 FROM cards p WHERE p.oracle_id = o.oracle_id
                           AND EXISTS (SELECT 1 FROM json_each(p.games) WHERE value = 'paper')) AS on_paper
            FROM oracle_cards o WHERE o.oracle_id IN ({marks})""", oracle_ids)}
    defaults = [oracle[o]["default_card_id"] for o in oracle_ids if o in oracle]
    owned_pick = dict(zip(defaults, owned_printings(conn, defaults), strict=True))
    shown = [first[o].card_id for o in oracle_ids]
    prices = _prices(conn, [*shown, *defaults])
    summaries = {s.id: s for s in card_summaries(conn, shown)}

    rows = []
    for oracle_id in oracle_ids:
        e = first[oracle_id]
        info = oracle.get(oracle_id)
        default = info["default_card_id"] if info else None
        a, b = copies_a.get(oracle_id, 0), copies_b.get(oracle_id, 0)

        def fit(side: DeckSide, have: int, other: int) -> CardFit:
            on_arena = bool(info and info["arena_card_id"])
            on_platform = on_arena if side.platform == "arena" else bool(info and info["on_paper"])
            legal = side.format == "freeform" or e.legalities.get(side.format) in ("legal", "restricted")
            in_identity = side.color_identity is None or set(e.color_identity) <= set(side.color_identity)
            addable = 0
            if legal and in_identity and on_platform and other > have:
                limit = allowed_copies(e, side.format)
                addable = other - have if limit is None else max(0, min(other, limit) - have)
            if side.platform == "arena":
                card_id = info["arena_card_id"] if info else None
            else:
                card_id = owned_pick.get(default, default) if default else e.card_id
            return CardFit(legal=legal, in_identity=in_identity, on_platform=on_platform, addable=addable,
                           card_id=card_id)

        rows.append(CompareRow(
            oracle_id=oracle_id, name=e.name, card=summaries[e.card_id], a=a, b=b,
            price_eur=prices.get(e.card_id) if prices.get(e.card_id) is not None else prices.get(default),
            fit_a=fit(side_a, a, b), fit_b=fit(side_b, b, a),
        ))
    return DeckComparison(a=side_a, b=side_b, rows=rows, prices_as_of=get_meta(conn, META_UPDATED_AT))


def _side(conn: sqlite3.Connection, deck_id: int) -> tuple[DeckSide, list[Entry]]:
    deck = conn.execute("SELECT id, name, format, platform FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if deck is None:
        raise DeckNotFound(deck_id)
    entries = load_entries(conn, deck_id)
    commanders = [e for e in entries if e.board == "commander"]
    identity = sorted({c for e in commanders for c in e.color_identity}) if commanders else None
    return DeckSide(id=deck["id"], name=deck["name"], format=deck["format"], platform=deck["platform"],
                    color_identity=identity), entries


def _copies(entries: list[Entry]) -> dict[str, int]:
    copies: dict[str, int] = {}
    for e in entries:
        if e.board in COUNTED:
            copies[e.oracle_id] = copies.get(e.oracle_id, 0) + e.quantity
    return copies


def _prices(conn: sqlite3.Connection, card_ids: list[str]) -> dict[str, float | None]:
    ids = list(dict.fromkeys(card_ids))
    rows = conn.execute(f"SELECT id, prices FROM card_details WHERE id IN ({', '.join('?' * len(ids))})", ids)
    return {r["id"]: _price(json.loads(r["prices"] or "{}"), "eur") for r in rows}
