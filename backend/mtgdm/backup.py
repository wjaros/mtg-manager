"""Backup of the user's own data: collection, locations and decks as JSON, without the
Scryfall card data. Cards are stored by Scryfall id plus name / set / number, so a backup can be
restored after Scryfall data changed or on another machine."""

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from mtgdm import __version__
from mtgdm.decks.service import _after_change
from mtgdm.decks.versions import current_entries
from mtgdm.i18n import tr

FORMAT = "mtgdm-backup"
VERSION = 1


class BackupError(ValueError):
    pass


class ImportResult(BaseModel):
    locations: int
    collection_items: int
    decks: int
    deck_cards: int
    missing_cards: list[str]  # cards that could not be found in the local card data


def export_backup(conn: sqlite3.Connection) -> dict[str, Any]:
    def card_ref(row: sqlite3.Row) -> dict[str, Any]:
        return {"card_id": row["card_id"], "name": row["name"], "set": row["set_code"],
                "collector_number": row["collector_number"]}

    locations = [dict(r) for r in conn.execute("SELECT id, name, kind FROM locations ORDER BY id")]
    collection = [
        {**card_ref(r), "quantity": r["quantity"], "finish": r["finish"], "language": r["language"],
         "condition": r["condition"], "location_id": r["location_id"], "source": r["source"], "note": r["note"]}
        for r in conn.execute(
            """
            SELECT ci.*, c.name, c.set_code, c.collector_number
            FROM collection_items ci JOIN cards c ON c.id = ci.card_id ORDER BY ci.id
            """
        )
    ]
    decks = []
    for d in conn.execute("SELECT * FROM decks ORDER BY id"):
        cards = [
            {**card_ref(r), "quantity": r["quantity"], "board": r["board"], "category": r["category"]}
            for r in conn.execute(
                """
                SELECT dc.*, c.name, c.set_code, c.collector_number
                FROM deck_cards dc JOIN cards c ON c.id = dc.card_id WHERE dc.deck_id = ? ORDER BY dc.rowid
                """,
                (d["id"],),
            )
        ]
        history = []
        for v in conn.execute("SELECT * FROM deck_versions WHERE deck_id = ? ORDER BY number", (d["id"],)):
            entries = json.loads(v["cards"])
            refs = {r["id"]: r for r in conn.execute(
                f"SELECT id, name, set_code, collector_number FROM cards WHERE id IN ({', '.join('?' * len(entries))})",
                [e["card_id"] for e in entries],
            )} if entries else {}
            history.append({
                "number": v["number"], "note": v["note"], "format": v["format"], "platform": v["platform"],
                "created_at": v["created_at"],
                "cards": [
                    {"card_id": e["card_id"], "name": refs[e["card_id"]]["name"] if e["card_id"] in refs else None,
                     "set": refs[e["card_id"]]["set_code"] if e["card_id"] in refs else None,
                     "collector_number": refs[e["card_id"]]["collector_number"] if e["card_id"] in refs else None,
                     "quantity": e["quantity"], "board": e["board"], "category": e.get("category")}
                    for e in entries
                ],
            })
        decks.append({
            "name": d["name"], "format": d["format"], "platform": d["platform"], "description": d["description"],
            "preferred_sets": json.loads(d["preferred_sets"]) if d["preferred_sets"] else [],
            "location_id": d["location_id"], "created_at": d["created_at"], "cards": cards, "versions": history,
        })
    return {
        "format": FORMAT,
        "version": VERSION,
        "app_version": __version__,
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "locations": locations,
        "collection": collection,
        "decks": decks,
    }


def import_backup(conn: sqlite3.Connection, data: dict[str, Any], replace: bool = False) -> ImportResult:
    """Restore a backup. With replace, existing collection, locations and decks are removed first;
    otherwise everything is added. Runs in one transaction: a broken file changes nothing."""
    if data.get("format") != FORMAT:
        raise BackupError(tr("backup_not_ours"))
    if not isinstance(data.get("version"), int) or data["version"] > VERSION:
        raise BackupError(tr("backup_newer"))

    resolver = _CardResolver(conn)
    result = ImportResult(locations=0, collection_items=0, decks=0, deck_cards=0, missing_cards=[])
    try:
        with conn:
            if replace:
                for table in ("deck_versions", "deck_cards", "decks", "collection_items", "locations"):
                    conn.execute(f"DELETE FROM {table}")

            location_ids: dict[Any, int] = {}
            for loc in data.get("locations", []):
                location_ids[loc["id"]] = conn.execute(
                    "INSERT INTO locations(name, kind) VALUES (?, ?)", (loc["name"], loc.get("kind", "other"))
                ).lastrowid
                result.locations += 1

            for item in data.get("collection", []):
                card_id = resolver.resolve(item)
                if card_id is None:
                    result.missing_cards.append(item.get("name") or str(item.get("card_id")))
                    continue
                conn.execute(
                    """
                    INSERT INTO collection_items(card_id, quantity, finish, language, condition, location_id, source, note)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (card_id, item["quantity"], item.get("finish", "nonfoil"), item.get("language", "en"),
                     item.get("condition", "NM"), location_ids.get(item.get("location_id")),
                     item.get("source", "import"), item.get("note")),
                )
                result.collection_items += 1

            for deck in data.get("decks", []):
                deck_id = conn.execute(
                    """
                    INSERT INTO decks(name, format, platform, description, preferred_sets, location_id)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (deck["name"], deck.get("format", "freeform"), deck.get("platform", "paper"),
                     deck.get("description"), json.dumps(deck["preferred_sets"]) if deck.get("preferred_sets") else None,
                     location_ids.get(deck.get("location_id"))),
                ).lastrowid
                for entry in deck.get("cards", []):
                    card_id = resolver.resolve(entry)
                    if card_id is None:
                        result.missing_cards.append(entry.get("name") or str(entry.get("card_id")))
                        continue
                    conn.execute(
                        """
                        INSERT INTO deck_cards(deck_id, card_id, quantity, board, category) VALUES (?, ?, ?, ?, ?)
                        ON CONFLICT(deck_id, card_id, board) DO UPDATE SET quantity = quantity + excluded.quantity
                        """,
                        (deck_id, card_id, entry["quantity"], entry.get("board", "main"), entry.get("category")),
                    )
                    result.deck_cards += 1
                _after_change(conn, deck_id)
                _restore_versions(conn, deck_id, deck.get("versions") or [], resolver)
                result.decks += 1
    except (KeyError, TypeError, sqlite3.IntegrityError) as exc:
        raise BackupError(tr("backup_broken", error=exc)) from exc
    result.missing_cards = sorted(set(result.missing_cards))
    return result


def _restore_versions(conn: sqlite3.Connection, deck_id: int, history: list[dict[str, Any]], resolver) -> None:
    """A deck's saved versions; a backup without them starts the history with the restored deck."""
    if not history:
        conn.execute(
            """
            INSERT INTO deck_versions(deck_id, number, note, format, platform, cards)
            SELECT id, 1, 'Przywrócono z kopii', format, platform, ? FROM decks WHERE id = ?
            """,
            (json.dumps(current_entries(conn, deck_id)), deck_id),
        )
        return
    for v in history:
        entries = []
        for e in v["cards"]:
            card_id = resolver.resolve(e)
            if card_id is not None:
                entries.append({"card_id": card_id, "quantity": e["quantity"], "board": e.get("board", "main"),
                                "category": e.get("category")})
        conn.execute(
            """
            INSERT INTO deck_versions(deck_id, number, note, format, platform, cards, created_at)
            VALUES (?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')))
            """,
            (deck_id, v["number"], v.get("note"), v.get("format", "freeform"), v.get("platform", "paper"),
             json.dumps(entries), v.get("created_at")),
        )


class _CardResolver:
    """Scryfall id first; then the same printing by set + number; then any printing by name."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.cache: dict[tuple, str | None] = {}

    def resolve(self, ref: dict[str, Any]) -> str | None:
        key = (ref.get("card_id"), ref.get("set"), ref.get("collector_number"), ref.get("name"))
        if key not in self.cache:
            self.cache[key] = self._lookup(*key)
        return self.cache[key]

    def _lookup(self, card_id, set_code, number, name) -> str | None:
        for sql, params in (
            ("SELECT id FROM cards WHERE id = ?", (card_id,)),
            ("SELECT id FROM cards WHERE set_code = ? AND collector_number = ?", (set_code, number)),
            ("SELECT default_card_id FROM oracle_cards WHERE name = ?", (name,)),
        ):
            if all(p is not None for p in params):
                row = self.conn.execute(sql, params).fetchone()
                if row:
                    return row[0]
        return None
