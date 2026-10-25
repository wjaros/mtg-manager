"""Scryfall's oracle tags (Tagger, community-made): what cards do. The app counts a few common
functions (ramp, card draw, removal, ...); every tag is kept, with its hierarchy, for later use.

They come from the oracle_tags bulk file (~6 MB, updated daily, on data.scryfall.io, which has no
rate limit). Tags are identified by id: Scryfall warns that slugs change. Their labels are not
shown in the UI; Scryfall asks apps that show them to be able to hide individual tags.
Refreshed weekly with the card data sync.
"""

import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mtgdm.scryfall.bulk import download_bulk, get_meta, iter_bulk_file, set_meta
from mtgdm.scryfall.client import ScryfallClient

log = logging.getLogger(__name__)

BULK_TYPE = "oracle_tags"
# What the app calls a function (the UI labels are translated) -> its Tagger tag id.
FUNCTION_TAGS = {
    "ramp": "2f3e4ad7-5e60-41b4-bdbc-653f16869cf6",
    "draw": "b6448c45-ce65-4848-aa98-2151e4e07437",
    "removal": "444f824c-f910-4530-9dbe-ede7a84cd7f9",
    "board-wipe": "3fb7e4fd-5304-4120-b7c4-8a89f70ad3f0",  # slug "sweeper"
    "counterspell": "690fc968-48ba-4854-a948-3db6bf19d3a9",
    "tutor": "c768d2ec-3264-4a90-a98f-bea8467857d3",
    "protection": "6e2cdc7c-b02c-4b59-a171-f93723721b79",
    "recursion": "82b824ad-648f-467f-a190-2e0fa9a795d2",
    "lifegain": "4caab3cc-1d60-44fb-a26a-cc833bc67c97",
}
TAGS = tuple(FUNCTION_TAGS)
SYNCED_KEY = "card_tags_synced_at"
REFRESH_DAYS = 7
Progress = Callable[[str, int, int], None]

# A tag and all its descendants (the hierarchy may have several parents per tag; UNION ends cycles).
_SUBTREE = """
    WITH RECURSIVE subtree(id) AS (
        SELECT ? UNION SELECT p.tag_id FROM oracle_tag_parents p JOIN subtree s ON p.parent_id = s.id
    )
"""


def sync_tags(conn: sqlite3.Connection, client: ScryfallClient, bulk_dir: Path, on_progress: Progress | None = None,
              force: bool = False, now: datetime | None = None) -> int | None:
    """Download the oracle tags and replace the stored ones. Returns the function tags given to cards
    (a card may have several), or None when the tags are still fresh."""
    now = now or datetime.now(UTC)
    synced = get_meta(conn, SYNCED_KEY)
    fresh = synced and now - datetime.fromisoformat(synced) < timedelta(days=REFRESH_DAYS)
    # No oracle tags yet: functions synced by an older version (one search per tag) are not enough.
    if not force and fresh and conn.execute("SELECT 1 FROM oracle_tags LIMIT 1").fetchone():
        return None
    path = download_bulk(client, client.bulk_data(BULK_TYPE), bulk_dir, on_progress, name=BULK_TYPE, stage="tags")
    with conn:
        _import_tags(conn, path)
        total = sum(_derive_function(conn, function, tag_id) for function, tag_id in FUNCTION_TAGS.items())
        set_meta(conn, SYNCED_KEY, now.isoformat(timespec="seconds"))
    return total


def _import_tags(conn: sqlite3.Connection, path: Path) -> None:
    local = {row[0] for row in conn.execute("SELECT DISTINCT oracle_id FROM cards WHERE oracle_id IS NOT NULL")}
    conn.execute("DELETE FROM oracle_taggings")
    conn.execute("DELETE FROM oracle_tag_parents")
    conn.execute("DELETE FROM oracle_tags")
    parents: set[tuple[str, str]] = set()
    for tag in iter_bulk_file(path):
        if tag.get("type", "oracle") != "oracle":
            continue
        conn.execute("INSERT INTO oracle_tags(id, slug, label, description) VALUES (?, ?, ?, ?)",
                     (tag["id"], tag["slug"], tag.get("label") or tag["slug"], tag.get("description")))
        # Both directions are listed; either one alone is enough to link two tags.
        parents.update((tag["id"], parent) for parent in tag.get("parent_ids") or [])
        parents.update((child, tag["id"]) for child in tag.get("child_ids") or [])
        conn.executemany(
            "INSERT OR IGNORE INTO oracle_taggings(oracle_id, tag_id, weight) VALUES (?, ?, ?)",
            [(t["oracle_id"], tag["id"], t.get("weight") or "median")
             for t in tag.get("taggings") or [] if t.get("oracle_id") in local],
        )
    # Links to tags the file doesn't have would break the foreign keys: left out.
    conn.executemany(
        "INSERT INTO oracle_tag_parents(tag_id, parent_id) SELECT ?, ?"
        " WHERE EXISTS (SELECT 1 FROM oracle_tags WHERE id = ?) AND EXISTS (SELECT 1 FROM oracle_tags WHERE id = ?)",
        [(tag_id, parent, tag_id, parent) for tag_id, parent in parents],
    )


def _derive_function(conn: sqlite3.Connection, function: str, tag_id: str) -> int:
    """card_tags rows of one function: the cards of its tag and of the tag's descendants."""
    if not conn.execute("SELECT 1 FROM oracle_tags WHERE id = ?", (tag_id,)).fetchone():
        # Gone from Tagger (deleted or merged): keep the cards it had rather than none.
        log.warning("oracle tag %s (%s) not in the bulk file; keeping the stored cards", tag_id, function)
        return 0
    conn.execute("DELETE FROM card_tags WHERE tag = ?", (function,))
    # The CTE inside INSERT (not before it): sqlite3 reports no rowcount for statements starting with WITH.
    return conn.execute(
        "INSERT INTO card_tags(oracle_id, tag)" + _SUBTREE
        + "SELECT DISTINCT t.oracle_id, ? FROM oracle_taggings t JOIN subtree s ON t.tag_id = s.id",
        (tag_id, function),
    ).rowcount


def card_tags(conn: sqlite3.Connection, oracle_ids: list[str]) -> dict[str, list[str]]:
    if not oracle_ids:
        return {}
    result: dict[str, list[str]] = {}
    for oracle, tag in conn.execute(
        f"SELECT oracle_id, tag FROM card_tags WHERE oracle_id IN ({', '.join('?' * len(oracle_ids))})", oracle_ids
    ):
        result.setdefault(oracle, []).append(tag)
    return result
