"""The user's own tags on cards ("wincon", "pet card", ...), next to Scryfall's Tagger tags: per card
(oracle id, so every printing), several per card, matched in any case. Searched with `tag:wincon`."""

import re
import sqlite3
from typing import Any

from pydantic import BaseModel

MAX_LENGTH = 40


class UserTag(BaseModel):
    tag: str
    cards: int


def clean(tags: list[str]) -> list[str]:
    """Trimmed, inner spaces collapsed, empty and repeated ones (in any case) left out, sorted."""
    seen: dict[str, str] = {}
    for tag in tags:
        tag = re.sub(r"\s+", " ", tag).strip()[:MAX_LENGTH].strip()
        if tag and tag.lower() not in seen:
            seen[tag.lower()] = tag
    return sorted(seen.values(), key=str.lower)


def _spelled(conn: sqlite3.Connection, tags: list[str]) -> list[str]:
    """Tags spelled as already used on other cards ("WINCON" becomes "Wincon"): one spelling each."""
    spelled = []
    for tag in clean(tags):
        used = conn.execute("SELECT tag FROM user_tags WHERE tag = ? LIMIT 1", (tag,)).fetchone()
        spelled.append(used[0] if used else tag)
    return spelled


def tags_of(conn: sqlite3.Connection, oracle_id: str | None) -> list[str]:
    if oracle_id is None:
        return []
    return [r[0] for r in conn.execute(
        "SELECT tag FROM user_tags WHERE oracle_id = ? ORDER BY tag COLLATE NOCASE", (oracle_id,)
    )]


def set_tags(conn: sqlite3.Connection, card_id: str, tags: list[str]) -> list[str] | None:
    """Replace a card's tags (any printing of it); None for an unknown card."""
    row = conn.execute("SELECT oracle_id FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None or row["oracle_id"] is None:
        return None
    with conn:
        conn.execute("DELETE FROM user_tags WHERE oracle_id = ?", (row["oracle_id"],))
        conn.executemany("INSERT INTO user_tags(oracle_id, tag) VALUES (?, ?)",
                         [(row["oracle_id"], tag) for tag in _spelled(conn, tags)])
    return tags_of(conn, row["oracle_id"])


def all_tags(conn: sqlite3.Connection) -> list[UserTag]:
    """Every tag in use with its number of cards, for suggestions."""
    return [UserTag(tag=r[0], cards=r[1]) for r in conn.execute(
        "SELECT tag, COUNT(*) FROM user_tags GROUP BY tag ORDER BY tag"
    )]


def backup_tags(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Per card: oracle id, its name (to find it again should the id be unknown) and its tags."""
    entries: dict[str, dict[str, Any]] = {}
    for oracle_id, name, tag in conn.execute(
        """SELECT t.oracle_id, o.name, t.tag FROM user_tags t LEFT JOIN oracle_cards o ON o.oracle_id = t.oracle_id
           ORDER BY o.name, t.tag COLLATE NOCASE"""
    ):
        entries.setdefault(oracle_id, {"oracle_id": oracle_id, "name": name, "tags": []})["tags"].append(tag)
    return list(entries.values())


def restore_tags(conn: sqlite3.Connection, entries: list[dict[str, Any]]) -> list[str]:
    """Add the tags of a backup (in the caller's transaction); returns the names of cards not found."""
    missing = []
    for entry in entries:
        found = conn.execute(
            "SELECT oracle_id FROM oracle_cards WHERE oracle_id = ? OR name = ? ORDER BY oracle_id = ? DESC LIMIT 1",
            (entry.get("oracle_id"), entry.get("name"), entry.get("oracle_id")),
        ).fetchone()
        if found is None:
            missing.append(entry.get("name") or str(entry.get("oracle_id")))
            continue
        conn.executemany("INSERT OR IGNORE INTO user_tags(oracle_id, tag) VALUES (?, ?)",
                         [(found[0], tag) for tag in _spelled(conn, entry.get("tags") or [])])
    return missing
