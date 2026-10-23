"""Scryfall's functional oracle tags ("otag:ramp" in Scryfall search) for the roles a deck counts:
ramp, card draw, removal, board wipes, ...

They come from Scryfall Tagger (community-made) and aren't part of the bulk data, so they are
fetched through the search API, as compact CSV pages (175 cards each), at Scryfall's request rate.
Refreshed weekly with the card data sync.
"""

import csv
import io
import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from mtgdm.scryfall.bulk import get_meta, set_meta
from mtgdm.scryfall.client import ScryfallClient, ScryfallError

log = logging.getLogger(__name__)

# Tagger tag -> what the app calls it (the UI labels are translated).
TAGS = ("ramp", "draw", "removal", "board-wipe", "counterspell", "tutor", "protection", "recursion", "lifegain")
PAGE_SIZE = 175
MAX_PAGES = 60
SYNCED_KEY = "card_tags_synced_at"
REFRESH_DAYS = 7
Progress = Callable[[str, int, int], None]


def sync_tags(conn: sqlite3.Connection, client: ScryfallClient, on_progress: Progress | None = None,
              force: bool = False, now: datetime | None = None) -> int | None:
    """Fetch every tag's cards, replacing what is stored. Returns the tagged cards, or None when the
    tags are still fresh."""
    now = now or datetime.now(UTC)
    synced = get_meta(conn, SYNCED_KEY)
    if not force and synced and now - datetime.fromisoformat(synced) < timedelta(days=REFRESH_DAYS):
        return None
    oracle_of = dict(conn.execute("SELECT id, oracle_id FROM cards WHERE oracle_id IS NOT NULL"))
    total = 0
    for i, tag in enumerate(TAGS):
        if on_progress:
            on_progress("tags", i, len(TAGS))
        oracles = {oracle_of[card_id] for card_id in _tagged_ids(client, tag) if card_id in oracle_of}
        with conn:
            conn.execute("DELETE FROM card_tags WHERE tag = ?", (tag,))
            conn.executemany("INSERT OR IGNORE INTO card_tags(oracle_id, tag) VALUES (?, ?)",
                             [(o, tag) for o in oracles])
        total += len(oracles)
    with conn:
        set_meta(conn, SYNCED_KEY, now.isoformat(timespec="seconds"))
    if on_progress:
        on_progress("tags", len(TAGS), len(TAGS))
    return total


def _tagged_ids(client: ScryfallClient, tag: str) -> list[str]:
    ids: list[str] = []
    for page in range(1, MAX_PAGES + 1):
        try:
            text = client.get_text("/cards/search", {"q": f"otag:{tag}", "format": "csv", "page": page})
        except ScryfallError as exc:
            if exc.status in (404, 422):  # past the last page (or no such tag any more)
                break
            raise
        rows = list(csv.DictReader(io.StringIO(text)))
        ids += [r["scryfall_id"] for r in rows if r.get("scryfall_id")]
        if len(rows) < PAGE_SIZE:
            break
    return ids


def card_tags(conn: sqlite3.Connection, oracle_ids: list[str]) -> dict[str, list[str]]:
    if not oracle_ids:
        return {}
    result: dict[str, list[str]] = {}
    for oracle, tag in conn.execute(
        f"SELECT oracle_id, tag FROM card_tags WHERE oracle_id IN ({', '.join('?' * len(oracle_ids))})", oracle_ids
    ):
        result.setdefault(oracle, []).append(tag)
    return result
