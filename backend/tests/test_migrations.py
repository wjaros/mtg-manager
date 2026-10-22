import sqlite3

import pytest

from mtgdm.db import connect, current_version, migrate
from mtgdm.db.migrations import available_migrations

LATEST = available_migrations()[-1][0]

EXPECTED_TABLES = {
    "meta", "sets", "cards", "cards_fts", "locations", "collection_items",
    "decks", "deck_cards", "scans", "scan_items", "schema_version", "oracle_cards",
}


def test_fresh_db_reaches_latest_version(db):
    assert current_version(db) == LATEST
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert EXPECTED_TABLES <= tables


def test_migrate_is_idempotent(db):
    assert migrate(db) == LATEST
    assert db.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == LATEST


def test_wal_and_foreign_keys(tmp_path):
    conn = connect(tmp_path / "x.sqlite")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def _insert_card(db, card_id, name, type_line="Creature", oracle_text=""):
    db.execute(
        "INSERT INTO cards(id, name, type_line, oracle_text) VALUES (?, ?, ?, ?)",
        (card_id, name, type_line, oracle_text),
    )


def _fts(db, query):
    return [r[0] for r in db.execute(
        "SELECT c.id FROM cards_fts JOIN cards c ON c.rowid = cards_fts.rowid"
        " WHERE cards_fts MATCH ? ORDER BY c.id", (query,)
    )]


def test_fts_follows_card_changes(db):
    _insert_card(db, "a", "Giada, Font of Hope", "Legendary Creature — Angel", "Flying, vigilance")
    _insert_card(db, "b", "Serra Angel", "Creature — Angel", "Flying, vigilance")
    assert _fts(db, "giada") == ["a"]
    assert _fts(db, "type_line:angel") == ["a", "b"]

    db.execute("UPDATE cards SET name = 'Sigarda' WHERE id = 'a'")
    assert _fts(db, "giada") == []
    assert _fts(db, "sigarda") == ["a"]

    db.execute("DELETE FROM cards WHERE id = 'b'")
    assert _fts(db, "serra") == []


def test_check_constraints(db):
    # Deck formats are validated by the API since 005; the platform still has a CHECK.
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO decks(name, platform) VALUES ('x', 'mtgo')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO collection_items(card_id) VALUES ('missing')")


def test_deck_formats_migration_keeps_cards_and_history(tmp_path):
    """005 rebuilds the decks table: rows referencing it must survive (no cascading delete)."""
    conn = connect(tmp_path / "db.sqlite")
    migrate(conn, until=4)
    conn.execute("INSERT INTO cards(id, name) VALUES ('c1', 'X')")
    conn.execute("INSERT INTO locations(id, name) VALUES (7, 'Box')")
    conn.execute("INSERT INTO decks(id, name, format, location_id) VALUES (1, 'Old', 'standard', 7)")
    conn.execute("INSERT INTO deck_cards(deck_id, card_id, quantity) VALUES (1, 'c1', 3)")
    conn.execute("INSERT INTO deck_versions(deck_id, number, format, platform, cards) VALUES (1, 1, 'standard', 'paper', '[]')")
    conn.commit()
    assert migrate(conn) >= 5
    assert conn.execute("SELECT name, format, location_id FROM decks").fetchall()[0][:] == ("Old", "standard", 7)
    assert conn.execute("SELECT quantity FROM deck_cards WHERE deck_id = 1").fetchone()[0] == 3
    assert conn.execute("SELECT count(*) FROM deck_versions WHERE deck_id = 1").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1  # back on after migrating
    conn.execute("INSERT INTO decks(name, format) VALUES ('New', 'pioneer')")  # no CHECK on format any more
    # References still enforced and cascading.
    conn.execute("DELETE FROM decks WHERE id = 1")
    assert conn.execute("SELECT count(*) FROM deck_cards").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM deck_versions").fetchone()[0] == 0


def test_proxy_tracking_migration_keeps_items_as_real(tmp_path):
    """008 adds collection_items.kind: every existing copy becomes a real one, nothing is lost."""
    conn = connect(tmp_path / "db.sqlite")
    migrate(conn, until=7)
    conn.execute("INSERT INTO cards(id, name) VALUES ('c1', 'X')")
    conn.execute("INSERT INTO locations(id, name) VALUES (7, 'Box')")
    conn.execute("INSERT INTO collection_items(card_id, quantity, finish, condition, location_id, note)"
                 " VALUES ('c1', 3, 'foil', 'EX', 7, 'n')")
    conn.commit()
    assert migrate(conn) >= 8
    row = conn.execute("SELECT quantity, finish, condition, location_id, note, kind, printed_at, print_job_id"
                       " FROM collection_items").fetchone()
    assert tuple(row) == (3, "foil", "EX", 7, "n", "real", None, None)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO collection_items(card_id, kind) VALUES ('c1', 'fake')")
