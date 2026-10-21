"""Deck history: snapshots of deck_cards (plus format and platform) and diffs between them.
The working copy in deck_cards is saved on every change; a snapshot is taken on demand, and
everything that differs from the latest snapshot is "unsaved"."""

import json
import sqlite3
from typing import Any

from mtgdm.cards.search import card_summaries
from mtgdm.decks.models import Board, DeckCard, DeckChange, DeckChanges, DeckVersion, DeckVersionDetail

BOARD_ORDER: list[Board] = ["commander", "companion", "main", "sideboard", "maybe"]

Entries = list[dict[str, Any]]  # [{card_id, quantity, board, category}]


class VersionNotFound(LookupError):
    pass


class NoChanges(ValueError):
    pass


def current_entries(conn: sqlite3.Connection, deck_id: int) -> Entries:
    return [dict(r) for r in conn.execute(
        "SELECT card_id, quantity, board, category FROM deck_cards WHERE deck_id = ? ORDER BY rowid", (deck_id,)
    )]


def latest(conn: sqlite3.Connection, deck_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM deck_versions WHERE deck_id = ? ORDER BY number DESC LIMIT 1", (deck_id,)
    ).fetchone()


def unsaved_changes(conn: sqlite3.Connection, deck_id: int) -> DeckChanges:
    """Working copy compared with the latest snapshot (an empty deck when there is none)."""
    base = latest(conn, deck_id)
    deck = conn.execute("SELECT format, platform FROM decks WHERE id = ?", (deck_id,)).fetchone()
    return DeckChanges(
        base_id=base["id"] if base else None,
        base_number=base["number"] if base else None,
        base_created_at=base["created_at"] if base else None,
        format_before=base["format"] if base and base["format"] != deck["format"] else None,
        platform_before=base["platform"] if base and base["platform"] != deck["platform"] else None,
        cards=diff(conn, json.loads(base["cards"]) if base else [], current_entries(conn, deck_id)),
    )


def save(conn: sqlite3.Connection, deck_id: int, note: str | None = None, *, allow_empty: bool = False) -> DeckVersion:
    """Snapshot the working copy. Raises NoChanges when it equals the latest snapshot."""
    changes = unsaved_changes(conn, deck_id)
    if not allow_empty and changes.base_number is not None and not changes.cards \
            and not changes.format_before and not changes.platform_before:
        raise NoChanges(deck_id)
    with conn:
        conn.execute(
            """
            INSERT INTO deck_versions(deck_id, number, note, format, platform, cards)
            SELECT id, ?, ?, format, platform, ? FROM decks WHERE id = ?
            """,
            ((changes.base_number or 0) + 1, (note or "").strip() or None,
             json.dumps(current_entries(conn, deck_id)), deck_id),
        )
    return list_versions(conn, deck_id)[0]


def list_versions(conn: sqlite3.Connection, deck_id: int) -> list[DeckVersion]:
    """Newest first, each with copies added / removed since the version before it."""
    rows = conn.execute("SELECT * FROM deck_versions WHERE deck_id = ? ORDER BY number", (deck_id,)).fetchall()
    versions = []
    previous: Entries = []
    for row in rows:
        entries = json.loads(row["cards"])
        changes = diff(conn, previous, entries, summaries=False)
        versions.append(_version(row, entries, changes))
        previous = entries
    return versions[::-1]


def get_version(conn: sqlite3.Connection, deck_id: int, version_id: int, compare: str = "previous") -> DeckVersionDetail:
    """A snapshot's cards and its changes: since the previous version, or from it to the working copy."""
    row = _row(conn, deck_id, version_id)
    entries = json.loads(row["cards"])
    if compare == "current":
        changes = diff(conn, entries, current_entries(conn, deck_id))
    else:
        before = conn.execute(
            "SELECT cards FROM deck_versions WHERE deck_id = ? AND number < ? ORDER BY number DESC LIMIT 1",
            (deck_id, row["number"]),
        ).fetchone()
        changes = diff(conn, json.loads(before["cards"]) if before else [], entries)
    summaries = {c.id: c for c in card_summaries(conn, list({e["card_id"] for e in entries}))}
    return DeckVersionDetail(
        **_version(row, entries, changes).model_dump(),
        cards=[
            DeckCard(card=summaries[e["card_id"]], quantity=e["quantity"], board=e["board"], category=e.get("category"))
            for e in entries if e["card_id"] in summaries
        ],
        changes=changes,
    )


def snapshot(conn: sqlite3.Connection, deck_id: int, version_id: int) -> tuple[sqlite3.Row, Entries]:
    row = _row(conn, deck_id, version_id)
    return row, json.loads(row["cards"])


def diff(conn: sqlite3.Connection, before: Entries, after: Entries, *, summaries: bool = True) -> list[DeckChange]:
    """Changes per card name and board: copies added / removed and printings swapped.
    Matching by name keeps a printing swap from looking like a removal plus an addition."""
    ids = list({e["card_id"] for e in before + after})
    names = dict(conn.execute(
        f"SELECT id, name FROM cards WHERE id IN ({', '.join('?' * len(ids))})", ids
    ).fetchall()) if ids else {}

    def group(entries: Entries) -> dict[tuple[str, str], dict[str, int]]:
        groups: dict[tuple[str, str], dict[str, int]] = {}
        for e in entries:
            per_printing = groups.setdefault((names.get(e["card_id"], e["card_id"]), e["board"]), {})
            per_printing[e["card_id"]] = per_printing.get(e["card_id"], 0) + e["quantity"]
        return groups

    old, new = group(before), group(after)
    raw = []
    for key in old.keys() | new.keys():
        b, a = old.get(key, {}), new.get(key, {})
        if b == a:
            continue
        card_id = next(iter(a or b))
        raw.append((key, card_id, sum(b.values()), sum(a.values()), bool(a) and bool(b) and a.keys() != b.keys()))
    raw.sort(key=lambda r: (BOARD_ORDER.index(r[0][1]) if r[0][1] in BOARD_ORDER else 9, r[0][0]))

    cards = {c.id: c for c in card_summaries(conn, list({r[1] for r in raw}))} if summaries else {}
    return [
        DeckChange(name=name, board=board, card=cards.get(card_id), before=b, after=a, printing_changed=printing)
        for (name, board), card_id, b, a, printing in raw
    ]


def _row(conn: sqlite3.Connection, deck_id: int, version_id: int) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM deck_versions WHERE id = ? AND deck_id = ?", (version_id, deck_id)
    ).fetchone()
    if row is None:
        raise VersionNotFound(version_id)
    return row


def _version(row: sqlite3.Row, entries: Entries, changes: list[DeckChange]) -> DeckVersion:
    return DeckVersion(
        id=row["id"],
        number=row["number"],
        note=row["note"],
        format=row["format"],
        platform=row["platform"],
        created_at=row["created_at"],
        total=sum(e["quantity"] for e in entries if e["board"] in ("main", "commander")),
        added=sum(max(0, c.after - c.before) for c in changes),
        removed=sum(max(0, c.before - c.after) for c in changes),
    )
