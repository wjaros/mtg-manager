"""Sync of Scryfall sets and their SVG icons.

Icons are downloaded locally (no hotlinking) into <images>/sets/<name>.svg; many sets share
one icon (e.g. token sets use the parent's), so each distinct file is fetched once.

Note: arena_code of one set can equal the Scryfall code of another (me1 -> arena 'med', while
'med' is its own set), so code lookups must try sets.code before arena_code.
"""

import logging
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import httpx

from mtgdm.scryfall.client import ScryfallClient, ScryfallError

log = logging.getLogger(__name__)

ICON_SUBDIR = "sets"
ICON_WORKERS = 8

Progress = Callable[[str, int, int], None]


def sync_sets(
    conn: sqlite3.Connection,
    client: ScryfallClient,
    images_dir: Path,
    on_progress: Progress | None = None,
) -> int:
    """Fetch all sets, upsert them and download missing icons. Returns the number of sets."""
    sets = list(client.iter_list("/sets"))
    icon_files = _download_icons(client, sets, images_dir / ICON_SUBDIR, on_progress)

    rows = [
        (
            s["code"],
            s.get("arena_code"),
            s.get("mtgo_code"),
            s["name"],
            s.get("set_type"),
            s.get("released_at"),
            int(bool(s.get("digital"))),
            icon_files.get(s.get("icon_svg_uri") or ""),
        )
        for s in sets
    ]
    with conn:
        # Upsert (not REPLACE) so rows referenced by cards.set_code are never deleted.
        conn.executemany(
            """
            INSERT INTO sets(code, arena_code, mtgo_code, name, set_type, released_at, digital, icon_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                arena_code = excluded.arena_code,
                mtgo_code = excluded.mtgo_code,
                name = excluded.name,
                set_type = excluded.set_type,
                released_at = excluded.released_at,
                digital = excluded.digital,
                icon_path = COALESCE(excluded.icon_path, sets.icon_path)
            """,
            rows,
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES ('sets_synced_at', ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (datetime.now(UTC).isoformat(timespec="seconds"),),
        )
    return len(rows)


def icon_filename(icon_uri: str) -> str:
    """'https://svgs.scryfall.io/sets/mdd.svg?1792382400' -> 'mdd.svg'."""
    return PurePosixPath(urlsplit(icon_uri).path).name


def _download_icons(
    client: ScryfallClient,
    sets: list[dict[str, Any]],
    icons_dir: Path,
    on_progress: Progress | None,
) -> dict[str, str]:
    """Download missing icons; returns {icon_svg_uri: path relative to images dir}."""
    icons_dir.mkdir(parents=True, exist_ok=True)
    by_name: dict[str, str] = {}
    for s in sets:
        uri = s.get("icon_svg_uri")
        if uri:
            by_name.setdefault(icon_filename(uri), uri)

    missing = [(name, uri) for name, uri in by_name.items() if not (icons_dir / name).is_file()]
    done = 0

    def fetch(item: tuple[str, str]) -> None:
        name, uri = item
        target = icons_dir / name
        tmp = target.with_suffix(".part")
        try:
            with client.stream(uri) as resp, tmp.open("wb") as f:
                for chunk in resp.iter_bytes():
                    f.write(chunk)
            tmp.replace(target)
        except (ScryfallError, httpx.HTTPError, OSError) as exc:  # one broken icon must not fail the sync
            tmp.unlink(missing_ok=True)
            log.warning("Set icon %s failed: %s", uri, exc)

    with ThreadPoolExecutor(max_workers=ICON_WORKERS) as pool:
        for _ in pool.map(fetch, missing):
            done += 1
            if on_progress:
                on_progress("set_icons", done, len(missing))

    result = {}
    for s in sets:
        uri = s.get("icon_svg_uri")
        if uri and (icons_dir / icon_filename(uri)).is_file():
            result[uri] = f"{ICON_SUBDIR}/{icon_filename(uri)}"
    return result
