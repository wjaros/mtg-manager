from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.config import Settings
from mtgdm.db import connect, migrate


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", frontend_dist=tmp_path / "dist")


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture
def db(tmp_path: Path):
    conn = connect(tmp_path / "test.sqlite")
    migrate(conn)
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def card_db_template(tmp_path_factory) -> Path:
    """Migrated database with the fixture cards imported, built once per test session."""
    from mtgdm.scryfall.bulk import import_cards
    from tests.helpers import fixture_cards, insert_fixture_sets

    path = tmp_path_factory.mktemp("template") / "db.sqlite"
    conn = connect(path)
    migrate(conn)
    insert_fixture_sets(conn)
    import_cards(conn, fixture_cards(), "2026-10-20T09:06:24.827+00:00")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return path


@pytest.fixture
def card_settings(tmp_path, card_db_template) -> Settings:
    """Settings whose database is a fresh copy of the card template."""
    import shutil

    s = Settings(data_dir=tmp_path / "data", frontend_dist=tmp_path / "dist")
    s.ensure_dirs()
    shutil.copy(card_db_template, s.db_path)
    return s
