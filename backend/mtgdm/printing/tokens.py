"""Tokens (and emblems) a deck's cards, or any cards picked for printing, make, from Scryfall's
all_parts links, for printing.

A card's printing links the token printings of its own set; the same token made by several cards
(same oracle id) is listed once, with every card that makes it."""

import json
import sqlite3

from pydantic import BaseModel

from mtgdm.collection.service import DECK_BOX_BOARDS


class DeckToken(BaseModel):
    oracle_id: str
    card_id: str            # the token printing to print
    printing: str           # e.g. "TFDN #3"
    name: str
    type_line: str | None
    oracle_text: str | None
    faces: int              # 2 for double-faced tokens
    sources: list[str]      # deck cards that make it


def deck_tokens(conn: sqlite3.Connection, deck_id: int) -> list[DeckToken]:
    rows = conn.execute(
        f"""
        SELECT c.name, json_extract(d.raw, '$.all_parts') AS parts
        FROM deck_cards dc JOIN cards c ON c.id = dc.card_id JOIN card_details d ON d.id = c.id
        WHERE dc.deck_id = ? AND dc.board IN ({", ".join("?" * len(DECK_BOX_BOARDS))})
        ORDER BY dc.rowid
        """,
        (deck_id, *DECK_BOX_BOARDS),
    ).fetchall()
    return _tokens_of(conn, rows)


def card_tokens(conn: sqlite3.Connection, card_ids: list[str]) -> list[DeckToken]:
    """Tokens the given printings make (cards added by hand to a print list)."""
    if not card_ids:
        return []
    rows = conn.execute(
        f"""
        SELECT c.id, c.name, json_extract(d.raw, '$.all_parts') AS parts
        FROM cards c JOIN card_details d ON d.id = c.id
        WHERE c.id IN ({", ".join("?" * len(card_ids))})
        """,
        card_ids,
    ).fetchall()
    # Sources listed in the order the cards were added.
    order = {card_id: i for i, card_id in enumerate(card_ids)}
    return _tokens_of(conn, sorted(rows, key=lambda r: order[r["id"]]))


def _tokens_of(conn: sqlite3.Connection, rows: list[sqlite3.Row]) -> list[DeckToken]:
    """Rows of (name, all_parts JSON) → the tokens they make, each with the cards that make it."""
    sources: dict[str, list[str]] = {}  # token printing id -> cards that make it
    for row in rows:
        for part in json.loads(row["parts"] or "[]"):
            # A token version of the card itself (e.g. Ajani's Pridemate) is not something it makes.
            if part.get("component") == "token" and part.get("id") and part.get("name") != row["name"]:
                names = sources.setdefault(part["id"], [])
                if row["name"] not in names:
                    names.append(row["name"])
    if not sources:
        return []

    tokens: dict[str, DeckToken] = {}
    for t in conn.execute(
        f"""
        SELECT id, oracle_id, name, type_line, oracle_text, image_faces, set_code, collector_number FROM cards
        WHERE id IN ({", ".join("?" * len(sources))})
        """,
        list(sources),
    ):
        key = t["oracle_id"] or t["id"]
        if key in tokens:  # the same token from another set's printing
            tokens[key].sources += [s for s in sources[t["id"]] if s not in tokens[key].sources]
            continue
        tokens[key] = DeckToken(
            oracle_id=key, card_id=t["id"], printing=f"{(t['set_code'] or '').upper()} #{t['collector_number']}",
            name=t["name"], type_line=t["type_line"], oracle_text=t["oracle_text"],
            faces=max(1, t["image_faces"] or 0), sources=list(sources[t["id"]]),
        )
    return sorted(tokens.values(), key=lambda t: (t.name.lower(), t.type_line or ""))
