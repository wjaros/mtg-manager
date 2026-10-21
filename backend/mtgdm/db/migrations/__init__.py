"""Numbered SQL migrations (NNN_name.sql) tracked in the schema_version table."""

import re
import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent
_FILENAME_RE = re.compile(r"^(\d{3})_[\w-]+\.sql$")


def available_migrations() -> list[tuple[int, Path]]:
    found = []
    for path in MIGRATIONS_DIR.iterdir():
        match = _FILENAME_RE.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    found.sort()
    versions = [v for v, _ in found]
    if len(versions) != len(set(versions)):
        raise RuntimeError(f"Duplicate migration numbers in {MIGRATIONS_DIR}")
    return found


def current_version(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY,"
        " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
    )
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] or 0


def migrate(conn: sqlite3.Connection, until: int | None = None) -> int:
    """Apply pending migrations (up to `until`, for tests), each in its own transaction.
    Returns the resulting version.

    Foreign keys are off while migrating, so a migration may rebuild a table (SQLite cannot
    change a column's constraints in place) without cascading deletes into the tables that
    reference it; every migration must leave no broken reference behind (checked before commit)."""
    version = current_version(conn)
    pending = [(n, p) for n, p in available_migrations() if n > version and (until is None or n <= until)]
    if not pending:
        return version
    foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    conn.execute("PRAGMA foreign_keys = OFF")  # no effect inside a transaction: set before BEGIN
    try:
        for number, path in pending:
            sql = path.read_text(encoding="utf-8")
            # executescript() commits implicitly, so the file runs in an explicit transaction,
            # committed only after the reference check.
            try:
                conn.executescript(f"BEGIN;\n{sql}\n;INSERT INTO schema_version(version) VALUES ({number});")
                broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise sqlite3.IntegrityError(
                        f"migration {path.name} leaves broken references: {[tuple(r) for r in broken[:5]]}"
                    )
                conn.commit()
            except sqlite3.Error:
                if conn.in_transaction:
                    conn.rollback()
                raise
            version = number
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")
    return version
