"""The UI's own preferences (deckbuilder layout, card sizes, grouping, language, interface scale…),
kept in meta. The window app's web view runs in private mode on a random port, so browser storage
is gone after a restart. They belong to this machine: not in backups."""

import sqlite3
from collections.abc import Callable

from mtgdm.scryfall.bulk import get_meta, set_meta

PREFIX = "ui:"
MAX_KEY = 100
MAX_VALUE = 200_000  # the print queue (a JSON list of cards) is the largest

SCALE_KEY = "scale"
MIN_SCALE, MAX_SCALE = 0.5, 3.0

# Zooms the window app's web view (set by `mtgdm app`); None in a browser, which has its own zoom.
_window_zoom: Callable[[float], None] | None = None


def get_all(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT key, value FROM meta WHERE substr(key, 1, ?) = ?", (len(PREFIX), PREFIX)
    ).fetchall()
    return {key[len(PREFIX):]: value for key, value in rows if key[len(PREFIX):] != SCALE_KEY}


def set_pref(conn: sqlite3.Connection, key: str, value: str | None) -> None:
    """Store a preference; None removes it."""
    with conn:
        if value is None:
            conn.execute("DELETE FROM meta WHERE key = ?", (PREFIX + key,))
        else:
            set_meta(conn, PREFIX + key, value)


def get_scale(conn: sqlite3.Connection) -> float:
    """Size of the whole interface (1 = 100%)."""
    try:
        scale = float(get_meta(conn, PREFIX + SCALE_KEY) or 1)
    except ValueError:
        return 1.0
    return min(MAX_SCALE, max(MIN_SCALE, scale))


def set_scale(conn: sqlite3.Connection, scale: float) -> float:
    scale = round(min(MAX_SCALE, max(MIN_SCALE, scale)), 2)
    set_pref(conn, SCALE_KEY, str(scale))
    if _window_zoom:
        _window_zoom(scale)
    return scale


def set_window_zoom(zoom: Callable[[float], None] | None) -> None:
    global _window_zoom
    _window_zoom = zoom


def native_zoom() -> bool:
    """The scale zooms the window app's web view (in a browser the browser's own zoom does that)."""
    return _window_zoom is not None
