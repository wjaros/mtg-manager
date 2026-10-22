"""Where a card is: physical copies per location (including deck boxes) and the decks that list it,
so adding it to another deck tells you which box to take it from."""

import sqlite3

from pydantic import BaseModel


class UsageLocation(BaseModel):
    location_id: int | None  # None = copies without a location
    name: str | None
    deck_id: int | None      # the deck whose box this location is
    deck_name: str | None
    quantity: int
    kind: str = "real"       # real copies or proxies (listed separately)


class UsageDeck(BaseModel):
    id: int
    name: str
    quantity: int            # copies in the list (main, commander, companion, sideboard)
    platform: str


class CardUsage(BaseModel):
    name: str
    in_deck: int             # copies in the deck being built (main + commander + companion)
    owned: int               # real copies in the collection, any printing
    free: int                # owned copies not in other decks' boxes
    proxies: int = 0         # proxies of the card, anywhere
    locations: list[UsageLocation]
    decks: list[UsageDeck]   # other decks whose list contains the card


def card_usage(conn: sqlite3.Connection, card_id: str, deck_id: int | None = None) -> CardUsage | None:
    card = conn.execute("SELECT oracle_id, name FROM cards WHERE id = ?", (card_id,)).fetchone()
    if card is None:
        return None
    oracle = card["oracle_id"]

    locations = [
        UsageLocation(**dict(r))
        for r in conn.execute(
            """
            SELECT ci.location_id, l.name, d.id AS deck_id, d.name AS deck_name, SUM(ci.quantity) AS quantity, ci.kind
            FROM collection_items ci
            JOIN cards x ON x.id = ci.card_id
            LEFT JOIN locations l ON l.id = ci.location_id
            LEFT JOIN decks d ON d.location_id = ci.location_id AND ci.location_id IS NOT NULL
            WHERE x.oracle_id = ?
            GROUP BY ci.location_id, ci.kind
            ORDER BY ci.kind = 'proxy', d.id IS NOT NULL, l.name COLLATE NOCASE
            """,
            (oracle,),
        )
    ]
    real = [loc for loc in locations if loc.kind == "real"]
    owned = sum(loc.quantity for loc in real)
    in_other_boxes = sum(loc.quantity for loc in real if loc.deck_id is not None and loc.deck_id != deck_id)

    rows = conn.execute(
        """
        SELECT d.id, d.name, d.platform, SUM(dc.quantity) AS quantity
        FROM deck_cards dc JOIN cards x ON x.id = dc.card_id JOIN decks d ON d.id = dc.deck_id
        WHERE x.oracle_id = ? AND dc.board IN ('main', 'commander', 'companion', 'sideboard')
        GROUP BY d.id
        ORDER BY d.name COLLATE NOCASE
        """,
        (oracle,),
    ).fetchall()
    in_deck = conn.execute(
        """
        SELECT COALESCE(SUM(dc.quantity), 0) FROM deck_cards dc JOIN cards x ON x.id = dc.card_id
        WHERE x.oracle_id = ? AND dc.deck_id IS ? AND dc.board IN ('main', 'commander', 'companion')
        """,
        (oracle, deck_id),
    ).fetchone()[0]
    return CardUsage(
        name=card["name"],
        in_deck=in_deck,
        owned=owned,
        free=owned - in_other_boxes,
        proxies=sum(loc.quantity for loc in locations if loc.kind == "proxy"),
        locations=locations,
        decks=[UsageDeck(**dict(r)) for r in rows if r["id"] != deck_id],
    )
