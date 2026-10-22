"""Collection exports: an Arena-style list ('4 Lightning Bolt (STA) 42', accepted by Moxfield,
Archidekt, ManaBox and others) and a CSV with one row per copy group."""

import csv
import io
import sqlite3
from typing import Literal

from mtgdm.decks.export import _arena_name

ExportFormat = Literal["arena", "csv"]

CSV_HEADER = ["Count", "Name", "Edition", "Edition Name", "Collector Number", "Foil", "Condition", "Language",
              "Location", "Scryfall ID"]


def export_collection(
    conn: sqlite3.Connection, fmt: ExportFormat, location_id: int | None = None, unassigned: bool = False
) -> str:
    where, params = ["ci.kind = 'real'"], []  # proxies are not part of what you own
    if location_id is not None:
        where.append("ci.location_id = ?")
        params.append(location_id)
    if unassigned:
        where.append("ci.location_id IS NULL")
    rows = conn.execute(
        f"""
        SELECT ci.card_id, ci.quantity, ci.finish, ci.language, ci.condition, l.name AS location,
               c.name, c.layout, c.set_code, c.collector_number, s.name AS set_name
        FROM collection_items ci
        JOIN cards c ON c.id = ci.card_id
        LEFT JOIN sets s ON s.code = c.set_code
        LEFT JOIN locations l ON l.id = ci.location_id
        {"WHERE " + " AND ".join(where) if where else ""}
        ORDER BY c.name, c.set_code, c.collector_number, ci.id
        """,
        params,
    ).fetchall()
    return _arena(rows) if fmt == "arena" else _csv(rows)


def _arena(rows: list[sqlite3.Row]) -> str:
    # One line per printing: finish, condition and location do not exist in this format.
    counts: dict[str, int] = {}
    lines: dict[str, str] = {}
    for r in rows:
        counts[r["card_id"]] = counts.get(r["card_id"], 0) + r["quantity"]
        lines[r["card_id"]] = f"{_arena_name(dict(r))} ({r['set_code'].upper()}) {r['collector_number']}"
    return "".join(f"{counts[card_id]} {line}\n" for card_id, line in lines.items())


def _csv(rows: list[sqlite3.Row]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for r in rows:
        writer.writerow([
            r["quantity"], r["name"], r["set_code"], r["set_name"] or "", r["collector_number"],
            "" if r["finish"] == "nonfoil" else r["finish"], r["condition"], r["language"], r["location"] or "",
            r["card_id"],
        ])
    return out.getvalue()
