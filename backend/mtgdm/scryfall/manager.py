"""Runs the Scryfall sync in a background thread and exposes its progress to the API."""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from mtgdm.config import Settings
from mtgdm.scryfall.client import ScryfallClient
from mtgdm.scryfall.sync import SyncResult, run_sync

log = logging.getLogger(__name__)


@dataclass
class SyncProgress:
    running: bool = False
    stage: str | None = None   # sets | set_icons | download | import | precons
    done: int = 0
    total: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    result: dict[str, Any] | None = None
    version: int = 0           # bumped on every change; lets SSE clients skip duplicates


class SyncManager:
    def __init__(self, settings: Settings, client: ScryfallClient,
                 runner: Callable[..., SyncResult] = run_sync):
        self._settings = settings
        self._client = client
        self._runner = runner
        self._lock = threading.Lock()
        self._progress = SyncProgress()
        self._thread: threading.Thread | None = None

    def snapshot(self) -> SyncProgress:
        with self._lock:
            return replace(self._progress)

    def start(self, force: bool = False) -> bool:
        """Start a sync unless one is running. Returns False if already running."""
        with self._lock:
            if self._progress.running:
                return False
            self._progress = SyncProgress(
                running=True, started_at=time.time(), version=self._progress.version + 1
            )
        self._thread = threading.Thread(target=self._run, args=(force,), name="scryfall-sync", daemon=True)
        self._thread.start()
        return True

    def wait(self, timeout: float | None = None) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(self, force: bool) -> None:
        try:
            result = self._runner(self._settings, force=force, client=self._client, on_progress=self._on_progress)
            self._update(result={
                "sets": result.sets,
                "cards": result.cards.cards,
                "removed": result.cards.removed,
                "skipped": result.cards.skipped,
                "updated_at": result.cards.updated_at,
                "precons": result.precons,
            })
        except Exception as exc:  # reported to the UI instead of killing the thread silently
            log.exception("Scryfall sync failed")
            self._update(error=str(exc) or type(exc).__name__)
        finally:
            self._update(running=False, finished_at=time.time())

    def _on_progress(self, stage: str, done: int, total: int) -> None:
        self._update(stage=stage, done=done, total=total)

    def _update(self, **changes: Any) -> None:
        with self._lock:
            for key, value in changes.items():
                setattr(self._progress, key, value)
            self._progress.version += 1
