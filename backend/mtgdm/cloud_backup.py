"""Automatic backups into a folder of your choice, e.g. one that iCloud Drive or OneDrive syncs.

The card database stays local (it can be downloaded again). After changes, the user's own data
(the JSON backup of mtgdm.backup) is written to `<folder>/mtgdm-backup.json`, whole and atomically
(temporary file, then rename), with older copies in `<folder>/history/`. A sync client copes with
one small file written whole; a live SQLite database in a synced folder it does not.

Another computer using the same folder sees a backup written by a different machine that is newer
than what it last wrote or loaded, and offers to load it (replacing its data; its own data is saved
to history first). Changes are found by comparing a hash of the backup without its timestamps.
"""

import hashlib
import json
import logging
import os
import platform
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mtgdm.backup import ImportResult, export_backup, import_backup
from mtgdm.scryfall.bulk import get_meta, set_meta

log = logging.getLogger(__name__)

FILE_NAME = "mtgdm-backup.json"
HISTORY_DIR = "history"
KEEP_HISTORY = 20
CHECK_SECONDS = 30
# meta keys
FOLDER_KEY = "cloud_backup_folder"
ENABLED_KEY = "cloud_backup_enabled"
MACHINE_KEY = "cloud_backup_machine_id"
HASH_KEY = "cloud_backup_hash"          # of the data last written or loaded
WRITTEN_KEY = "cloud_backup_written_at"  # when this machine last wrote
SEEN_KEY = "cloud_backup_seen_at"        # newest other machine's backup loaded or dismissed


class CloudBackupSettings(BaseModel):
    folder: str | None
    enabled: bool


class RemoteBackup(BaseModel):
    machine_name: str
    written_at: str
    decks: int
    collection_items: int


class CloudBackupStatus(BaseModel):
    folder: str | None
    enabled: bool
    machine_name: str
    last_written_at: str | None
    error: str | None = None          # the folder is missing or not writable
    newer: RemoteBackup | None = None  # another computer's backup, newer than what this one has
    suggestions: list[str] = []        # synced folders found on this computer


class FolderError(ValueError):
    pass


def machine_id(conn: sqlite3.Connection) -> str:
    value = get_meta(conn, MACHINE_KEY)
    if value is None:
        value = uuid.uuid4().hex
        with conn:
            set_meta(conn, MACHINE_KEY, value)
    return value


def machine_name() -> str:
    return platform.node().removesuffix(".local") or "?"


def get_settings(conn: sqlite3.Connection) -> CloudBackupSettings:
    return CloudBackupSettings(folder=get_meta(conn, FOLDER_KEY), enabled=get_meta(conn, ENABLED_KEY) == "1")


def save_settings(conn: sqlite3.Connection, settings: CloudBackupSettings) -> CloudBackupSettings:
    folder = settings.folder.strip() if settings.folder else None
    if settings.enabled:
        if not folder:
            raise FolderError("no folder")
        folder = str(_check_folder(Path(folder).expanduser()))
    with conn:
        if folder and folder != get_meta(conn, FOLDER_KEY):
            set_meta(conn, FOLDER_KEY, folder)
            set_meta(conn, HASH_KEY, "")  # a new folder: write there at the next check
        set_meta(conn, ENABLED_KEY, "1" if settings.enabled else "0")
    return get_settings(conn)


def data_hash(data: dict[str, Any]) -> str:
    """Of the user's data only: timestamps and app version don't make a backup different."""
    stable = {k: v for k, v in data.items() if k not in ("exported_at", "app_version", "machine")}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def write_if_changed(conn: sqlite3.Connection, force: bool = False) -> bool:
    """Write the backup when the data changed since it was last written or loaded. Returns
    whether a file was written."""
    settings = get_settings(conn)
    if not settings.enabled or not settings.folder:
        return False
    data = export_backup(conn)
    digest = data_hash(data)
    if not force and digest == get_meta(conn, HASH_KEY):
        return False
    folder = _check_folder(Path(settings.folder))
    remote = _read(folder)
    if not force and remote is not None and _is_newer(conn, remote):
        return False  # another computer's newer data waits to be loaded or dismissed: don't overwrite it
    now = datetime.now(UTC).isoformat(timespec="microseconds")
    data["machine"] = {"id": machine_id(conn), "name": machine_name(), "written_at": now}
    _write(folder, data)
    with conn:
        set_meta(conn, HASH_KEY, digest)
        set_meta(conn, WRITTEN_KEY, now)
    return True


def status(conn: sqlite3.Connection) -> CloudBackupStatus:
    settings = get_settings(conn)
    result = CloudBackupStatus(folder=settings.folder, enabled=settings.enabled, machine_name=machine_name(),
                               last_written_at=get_meta(conn, WRITTEN_KEY), suggestions=suggested_folders())
    if not settings.enabled or not settings.folder:
        return result
    try:
        _check_folder(Path(settings.folder))
    except FolderError as exc:
        result.error = str(exc)
        return result
    remote = _read(Path(settings.folder))
    if remote is not None and _is_newer(conn, remote):
        result.newer = RemoteBackup(
            machine_name=remote["machine"].get("name") or "?",
            written_at=remote["machine"]["written_at"],
            decks=len(remote.get("decks", [])),
            collection_items=len(remote.get("collection", [])),
        )
    return result


def load_newer(conn: sqlite3.Connection) -> ImportResult:
    """Replace this computer's data with the other computer's backup (this one's goes to history)."""
    settings = get_settings(conn)
    folder = _check_folder(Path(settings.folder or ""))
    remote = _read(folder)
    if remote is None:
        raise FolderError("no backup")
    own = export_backup(conn)
    own["machine"] = {"id": machine_id(conn), "name": machine_name(),
                      "written_at": datetime.now(UTC).isoformat(timespec="microseconds"), "replaced": True}
    _keep_in_history(folder, own)
    result = import_backup(conn, remote, replace=True)
    with conn:
        set_meta(conn, SEEN_KEY, remote["machine"]["written_at"])
        # What is loaded now is in the folder already: nothing to write back until something changes.
        set_meta(conn, HASH_KEY, data_hash(export_backup(conn)))
    return result


def dismiss_newer(conn: sqlite3.Connection) -> None:
    """Keep this computer's data; don't offer that backup again (a newer one will be)."""
    settings = get_settings(conn)
    remote = _read(Path(settings.folder)) if settings.folder else None
    if remote is not None:
        with conn:
            set_meta(conn, SEEN_KEY, remote["machine"]["written_at"])


def suggested_folders() -> list[str]:
    """Folders that iCloud Drive, OneDrive or Dropbox sync, if they exist here."""
    home = Path.home()
    candidates = [
        home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "MTG Deck Manager",  # iCloud Drive (macOS)
        home / "iCloudDrive" / "MTG Deck Manager",                                            # iCloud for Windows
        *(p / "MTG Deck Manager" for p in sorted(home.glob("OneDrive*"))),
        *(p / "MTG Deck Manager" for p in sorted((home / "Library" / "CloudStorage").glob("OneDrive*"))
          if (home / "Library" / "CloudStorage").is_dir()),
        home / "Dropbox" / "MTG Deck Manager",
        home / "Documents" / "MTG Deck Manager",
    ]
    return [str(p) for p in candidates if p.parent.is_dir()]


def _is_newer(conn: sqlite3.Connection, remote: dict[str, Any]) -> bool:
    machine = remote.get("machine") or {}
    if not machine.get("written_at") or machine.get("id") == machine_id(conn):
        return False
    known = max(get_meta(conn, WRITTEN_KEY) or "", get_meta(conn, SEEN_KEY) or "")
    return machine["written_at"] > known


def _check_folder(folder: Path) -> Path:
    try:
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / f".mtgdm-write-test-{os.getpid()}"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise FolderError(str(exc)) from exc
    return folder


def _write(folder: Path, data: dict[str, Any]) -> None:
    target = folder / FILE_NAME
    if target.is_file():
        previous = _read(folder)
        if previous is not None:
            _keep_in_history(folder, previous)
    tmp = folder / f".{FILE_NAME}.{os.getpid()}.part"
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, target)


def _keep_in_history(folder: Path, data: dict[str, Any]) -> None:
    history = folder / HISTORY_DIR
    history.mkdir(exist_ok=True)
    machine = data.get("machine") or {}
    stamp = (machine.get("written_at") or data.get("exported_at") or "unknown").replace(":", "-")
    name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in machine.get("name") or "unknown")
    (history / f"mtgdm-backup-{stamp}-{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                                               encoding="utf-8")
    for old in sorted(history.glob("mtgdm-backup-*.json"))[:-KEEP_HISTORY]:
        old.unlink(missing_ok=True)


def _read(folder: Path) -> dict[str, Any] | None:
    try:
        data = json.loads((folder / FILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None  # missing, being synced, or not ours
    return data if isinstance(data, dict) and isinstance(data.get("machine"), dict) else None


class CloudBackupWriter:
    """Checks every CHECK_SECONDS whether the data changed and writes the backup; once more on stop."""

    def __init__(self, connect: Callable[[], sqlite3.Connection], interval: float = CHECK_SECONDS):
        self._connect = connect
        self._interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="cloud-backup", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._check()  # changes made in the last seconds

    def _run(self) -> None:
        while not self._stop.wait(self._interval):
            self._check()

    def _check(self) -> None:
        try:
            conn = self._connect()
            try:
                write_if_changed(conn)
            finally:
                conn.close()
        except Exception:  # a sync client holding the file, a folder gone: try again next time
            log.exception("cloud backup failed")
