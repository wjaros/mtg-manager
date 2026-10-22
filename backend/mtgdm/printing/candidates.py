"""Which cards of a deck need a proxy to build it physically: copies you don't own, and copies
that only exist in other decks' boxes (counted by oracle id, like the missing-cards report)."""

import sqlite3
from typing import Literal

from pydantic import BaseModel

from mtgdm.collection.missing import deck_holdings
from mtgdm.collection.service import DECK_BOX_BOARDS


class ProxyCandidate(BaseModel):
    oracle_id: str
    card_id: str            # the deck's printing (the default to print)
    name: str
    reason: Literal["missing", "in_other_deck"]
    qty: int                # copies to proxy for this reason
    other_decks: list[str]  # where the copies are (reason "in_other_deck")
    faces: int              # images: 2 for double-faced cards
    image_status: str | None  # Scryfall's: highres_scan, lowres, placeholder, missing


def proxy_candidates(conn: sqlite3.Connection, deck_id: int, include_basics: bool = False) -> list[ProxyCandidate]:
    holdings = deck_holdings(conn, deck_id)  # raises DeckNotFound
    # The deck's first printing of each card represents it (as in the missing-cards report).
    cards = {
        r["oracle_id"]: r
        for r in conn.execute(
            f"""
            SELECT c.oracle_id, c.id, c.name, c.type_line, c.image_faces,
                   json_extract(d.raw, '$.image_status') AS image_status
            FROM deck_cards dc JOIN cards c ON c.id = dc.card_id LEFT JOIN card_details d ON d.id = c.id
            WHERE dc.deck_id = ? AND dc.board IN ({", ".join("?" * len(DECK_BOX_BOARDS))})
            ORDER BY dc.rowid DESC
            """,
            (deck_id, *DECK_BOX_BOARDS),
        )
    }
    result = []
    for h in holdings:
        card = cards[h.oracle_id]
        if not include_basics and "Basic" in (card["type_line"] or "").split("—")[0]:
            continue
        # Copies you can put in this deck: loose ones and those already in its box.
        available = h.owned - h.in_other_decks
        short = max(0, h.needed - available)
        missing = min(short, h.missing)
        common = {"oracle_id": h.oracle_id, "card_id": card["id"], "name": card["name"],
                  "faces": max(1, card["image_faces"] or 0), "image_status": card["image_status"]}
        if missing:
            result.append(ProxyCandidate(**common, reason="missing", qty=missing, other_decks=[]))
        if short - missing:
            result.append(ProxyCandidate(**common, reason="in_other_deck", qty=short - missing,
                                         other_decks=h.other_decks))
    result.sort(key=lambda c: (c.reason, c.name.lower()))
    return result


def image_statuses(conn: sqlite3.Connection, card_ids: list[str]) -> dict[str, str | None]:
    if not card_ids:
        return {}
    return {
        r[0]: r[1]
        for r in conn.execute(
            f"SELECT id, json_extract(raw, '$.image_status') FROM card_details WHERE id IN ({', '.join('?' * len(card_ids))})",
            card_ids,
        )
    }


def card_faces(conn: sqlite3.Connection, card_ids: list[str]) -> dict[str, tuple[str, int]]:
    """Name and number of images per card."""
    if not card_ids:
        return {}
    return {
        r["id"]: (r["name"], max(1, r["image_faces"] or 0))
        for r in conn.execute(
            f"SELECT id, name, image_faces FROM cards WHERE id IN ({', '.join('?' * len(card_ids))})", card_ids
        )
    }

