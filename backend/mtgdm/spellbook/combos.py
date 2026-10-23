"""A deck's combos from Commander Spellbook: those it has and those one card away, with the cards
mapped to local printings (the deck's own, else the default one) and the collection."""

import sqlite3
from typing import Any

from pydantic import BaseModel

from mtgdm.decks.service import DeckNotFound
from mtgdm.spellbook.client import SpellbookClient

COMBO_URL = "https://commanderspellbook.com/combo/{id}/"
# Deck format -> Commander Spellbook legality key (formats it doesn't know: no legality shown).
LEGALITY_KEYS = {
    "commander": "commander", "brawl": "brawl", "standardbrawl": "standardBrawl",
    "standard": "standard", "pioneer": "pioneer",
}


class ComboCard(BaseModel):
    name: str
    oracle_id: str | None
    card_id: str | None  # local printing for the image; None when the card data doesn't have it
    image_faces: int = 0
    in_deck: bool
    owned: int = 0  # real copies in the collection


class Combo(BaseModel):
    id: str
    url: str
    cards: list[ComboCard]
    requires: list[str]  # templates, e.g. "Permanent castable for {C}"
    produces: list[str]
    description: str
    prerequisites: str
    mana_needed: str
    popularity: int | None
    legal: bool | None  # in the deck's format, when Commander Spellbook knows it


class DeckCombos(BaseModel):
    included: list[Combo]
    almost: list[Combo]  # one card missing


def deck_combos(conn: sqlite3.Connection, client: SpellbookClient, deck_id: int) -> DeckCombos:
    deck = conn.execute("SELECT format FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if deck is None:
        raise DeckNotFound(deck_id)
    rows = conn.execute(
        """SELECT dc.board, c.id, c.name, c.oracle_id, c.image_faces, dc.quantity FROM deck_cards dc
           JOIN cards c ON c.id = dc.card_id
           WHERE dc.deck_id = ? AND dc.board IN ('main', 'commander', 'companion')""",
        (deck_id,),
    ).fetchall()
    commanders: dict[str, int] = {}
    main: dict[str, int] = {}
    in_deck: dict[str, sqlite3.Row] = {}
    for r in rows:
        target = commanders if r["board"] == "commander" else main
        target[r["name"]] = target.get(r["name"], 0) + r["quantity"]
        in_deck.setdefault(r["oracle_id"], r)
    if not rows:
        return DeckCombos(included=[], almost=[])

    results = client.find_my_combos(sorted(commanders.items()), sorted(main.items()))
    variants = [*results.get("included", []), *results.get("almostIncluded", [])]
    others = {u["card"].get("oracleId") for v in variants for u in v["uses"]} - in_deck.keys() - {None}
    local = _local_cards(conn, others)
    legality_key = LEGALITY_KEYS.get(deck["format"])

    def combo(v: dict[str, Any]) -> Combo:
        cards = []
        for use in v["uses"]:
            oracle_id = use["card"].get("oracleId")
            own = in_deck.get(oracle_id)
            row = own or local.get(oracle_id)
            cards.append(ComboCard(
                name=use["card"]["name"], oracle_id=oracle_id,
                card_id=row["id"] if row else None, image_faces=row["image_faces"] if row else 0,
                in_deck=own is not None, owned=local[oracle_id]["owned"] if oracle_id in local else 0,
            ))
        legalities = v.get("legalities") or {}
        prerequisites = "\n".join(p for p in (v.get("easyPrerequisites"), v.get("notablePrerequisites")) if p)
        return Combo(
            id=v["id"], url=COMBO_URL.format(id=v["id"]), cards=cards,
            requires=[r["template"]["name"] for r in v.get("requires", [])],
            produces=[p["feature"]["name"] for p in v.get("produces", [])],
            description=v.get("description") or "", prerequisites=prerequisites,
            mana_needed=v.get("manaNeeded") or "", popularity=v.get("popularity"),
            legal=legalities.get(legality_key) if legality_key else None,
        )

    def by_popularity(combos: list[Combo]) -> list[Combo]:
        return sorted(combos, key=lambda c: -(c.popularity or 0))

    return DeckCombos(
        included=by_popularity([combo(v) for v in results.get("included", [])]),
        almost=by_popularity([combo(v) for v in results.get("almostIncluded", [])]),
    )


def _local_cards(conn: sqlite3.Connection, oracle_ids: set[str]) -> dict[str, dict[str, Any]]:
    """Default printing and owned copies of cards outside the deck."""
    if not oracle_ids:
        return {}
    marks = ",".join("?" * len(oracle_ids))
    return {
        r["oracle_id"]: dict(r)
        for r in conn.execute(
            f"""SELECT o.oracle_id, c.id, c.image_faces,
                       (SELECT COALESCE(SUM(ci.quantity), 0) FROM collection_items ci JOIN cards cc ON cc.id = ci.card_id
                        WHERE cc.oracle_id = o.oracle_id AND ci.kind = 'real') AS owned
                FROM oracle_cards o JOIN cards c ON c.id = o.default_card_id
                WHERE o.oracle_id IN ({marks})""",
            list(oracle_ids),
        )
    }
