import sqlite3
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request

from mtgdm.config import Settings
from mtgdm.db import connect


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[sqlite3.Connection]:
    """One connection per request; WAL lets reads run while a sync writes."""
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


Db = Annotated[sqlite3.Connection, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]
