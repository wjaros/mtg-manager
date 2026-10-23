"""Is there a newer release? One request to GitHub's releases API (at most every CHECK_HOURS),
with the changes of every release newer than this one and the download for this computer.
No automatic install: the macOS app isn't signed, so it couldn't replace itself cleanly."""

import json
import platform
import re
import sqlite3
import sys
from datetime import UTC, datetime, timedelta

import httpx
from pydantic import BaseModel

from mtgdm import APP_NAME, __version__
from mtgdm.scryfall.bulk import get_meta, set_meta

REPOSITORY = "wjaros/mtg-manager"
RELEASES_URL = f"https://api.github.com/repos/{REPOSITORY}/releases"
CHECK_HOURS = 6
ENABLED_KEY = "update_check_enabled"
CACHE_KEY = "update_check_cache"  # {"checked_at": ..., "releases": [...]}
SKIPPED_KEY = "update_skipped_version"  # "Skip this version": no reminder until a newer one


class Download(BaseModel):
    name: str
    url: str
    size: int


class ReleaseNotes(BaseModel):
    version: str
    published_at: str | None
    url: str
    notes: str  # Markdown: the changes only (download instructions left out)


class UpdateInfo(BaseModel):
    enabled: bool
    current: str
    latest: str | None
    newer: bool
    skipped: bool = False      # the user skipped the latest version (show it in Settings, not the banner)
    download: Download | None  # the file for this computer
    url: str | None            # the release page
    releases: list[ReleaseNotes]  # every release newer than this one, newest first
    checked_at: str | None
    error: str | None = None


def version_tuple(tag: str) -> tuple[int, ...]:
    """'v0.1.10' -> (0, 1, 10); anything unparsable sorts first."""
    numbers = re.findall(r"\d+", tag)
    return tuple(int(n) for n in numbers) if numbers else (0,)


def asset_suffix(system: str = sys.platform, machine: str = platform.machine()) -> str | None:
    """The end of this computer's download's name (see scripts/build_macos.sh, build_windows.ps1)."""
    if system == "darwin":
        return "-arm64.dmg" if machine.lower() in ("arm64", "aarch64") else "-x86_64.dmg"
    if system == "win32":
        return "-windows-x64.zip"
    return None


def changes_only(body: str) -> str:
    """Release notes from the "What's changed" heading on (the download instructions are on the page)."""
    match = re.search(r"^##\s+What's changed", body or "", re.IGNORECASE | re.MULTILINE)
    return (body[match.end():] if match else body or "").strip()


def is_enabled(conn: sqlite3.Connection) -> bool:
    return get_meta(conn, ENABLED_KEY) != "0"


def set_enabled(conn: sqlite3.Connection, enabled: bool) -> None:
    with conn:
        set_meta(conn, ENABLED_KEY, "1" if enabled else "0")


def skip(conn: sqlite3.Connection, version: str) -> None:
    with conn:
        set_meta(conn, SKIPPED_KEY, version)


def check(conn: sqlite3.Connection, http: httpx.Client, force: bool = False, now: datetime | None = None) -> UpdateInfo:
    now = now or datetime.now(UTC)
    enabled = is_enabled(conn)
    cache = json.loads(get_meta(conn, CACHE_KEY) or "{}")
    error = None
    fresh = cache.get("checked_at") and now - datetime.fromisoformat(cache["checked_at"]) < timedelta(hours=CHECK_HOURS)
    if (enabled or force) and (force or not fresh):
        try:
            resp = http.get(RELEASES_URL, params={"per_page": 20},
                            headers={"Accept": "application/vnd.github+json", "User-Agent": f"{APP_NAME}/{__version__}"})
            resp.raise_for_status()
            cache = {"checked_at": now.isoformat(timespec="seconds"), "releases": [
                {"tag": r["tag_name"], "published_at": r.get("published_at"), "url": r["html_url"], "body": r.get("body") or "",
                 "assets": [{"name": a["name"], "url": a["browser_download_url"], "size": a.get("size", 0)}
                            for a in r.get("assets", [])]}
                for r in resp.json() if not r.get("draft") and not r.get("prerelease")
            ]}
            with conn:
                set_meta(conn, CACHE_KEY, json.dumps(cache))
        except (httpx.HTTPError, ValueError, KeyError) as exc:  # offline or rate limited: try later
            error = str(exc) or type(exc).__name__
    return _info(enabled, cache, error, get_meta(conn, SKIPPED_KEY))


def _info(enabled: bool, cache: dict, error: str | None, skipped: str | None = None) -> UpdateInfo:
    current = version_tuple(__version__)
    releases = sorted(cache.get("releases", []), key=lambda r: version_tuple(r["tag"]), reverse=True)
    newer = [r for r in releases if version_tuple(r["tag"]) > current]
    latest = releases[0] if releases else None
    suffix = asset_suffix()
    download = None
    if newer and suffix:
        asset = next((a for a in newer[0]["assets"] if a["name"].endswith(suffix)), None)
        download = Download(**asset) if asset else None
    return UpdateInfo(
        enabled=enabled,
        current=__version__,
        latest=latest["tag"].lstrip("v") if latest else None,
        newer=bool(newer),
        skipped=bool(newer) and skipped is not None and version_tuple(skipped) >= version_tuple(newer[0]["tag"]),
        download=download,
        url=newer[0]["url"] if newer else None,
        releases=[ReleaseNotes(version=r["tag"].lstrip("v"), published_at=r["published_at"], url=r["url"],
                               notes=changes_only(r["body"])) for r in newer],
        checked_at=cache.get("checked_at"),
        error=error,
    )
