"""Proxy PDFs are built in a background thread: missing images are downloaded first (that is the
slow part), then the pages are rendered into a file the browser downloads with a plain link (also
in the pywebview window, which allows downloads of links but not of blobs)."""

import logging
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from mtgdm.db import connect
from mtgdm.i18n import Lang, set_lang
from mtgdm.printing.layout import Correction, PageLayout
from mtgdm.printing.render import Duplex, Slot, render_proxies
from mtgdm.scryfall.images import ImageCache

log = logging.getLogger(__name__)
KEEP_JOBS = 5


@dataclass
class PrintJob:
    id: str
    filename: str
    stage: Literal["images", "render", "done", "error"] = "images"
    done: int = 0
    total: int = 0
    pages: int = 0
    missing_images: list[str] = field(default_factory=list)  # names printed as a frame with the name
    error: str | None = None
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class PrintRequest:
    slots: list[Slot]
    layout: PageLayout
    correction: Correction
    cut_marks: bool
    title: str
    profile_label: str | None
    filename: str
    lang: Lang
    backs: list[Slot | None] | None = None  # duplex: the other face of a double-faced card, or None (app back)
    duplex: Duplex = "off"
    back_shift: tuple[float, float] = (0.0, 0.0)


class PrintJobs:
    def __init__(self, db_path: Path, out_dir: Path, cache: ImageCache):
        self._db_path = db_path
        self._dir = out_dir
        self._cache = cache
        self._lock = threading.Lock()
        self._jobs: dict[str, PrintJob] = {}

    def start(self, request: PrintRequest, run: Callable[[Callable[[], None]], None] | None = None) -> PrintJob:
        """`run` (tests) runs the work synchronously instead of in a thread."""
        images = len(request.slots) + sum(1 for b in request.backs or [] if b)
        job = PrintJob(id=uuid.uuid4().hex, filename=request.filename, total=images)
        with self._lock:
            self._jobs[job.id] = job
            self._forget_old()
        work = lambda: self._run(job.id, request)  # noqa: E731
        if run:
            run(work)
        else:
            threading.Thread(target=work, name=f"print-{job.id[:8]}", daemon=True).start()
        return self.get(job.id)

    def get(self, job_id: str) -> PrintJob | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return replace(job) if job else None

    def pdf_path(self, job_id: str) -> Path:
        return self._dir / f"{job_id}.pdf"

    def _update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for key, value in changes.items():
                setattr(job, key, value)

    def _advance(self, job_id: str, step: int = 1) -> None:
        with self._lock:
            self._jobs[job_id].done += step

    def _run(self, job_id: str, request: PrintRequest) -> None:
        set_lang(request.lang)
        try:
            conn = connect(self._db_path)
            try:
                images = self._fetch_images(conn, job_id, request.slots + [b for b in request.backs or [] if b])
            finally:
                conn.close()
            self._update(job_id, stage="render", done=0, total=len(request.slots))
            self._dir.mkdir(parents=True, exist_ok=True)
            target = self.pdf_path(job_id)
            tmp = target.with_suffix(".part")
            with tmp.open("wb") as out:
                pages = render_proxies(
                    out, request.slots, lambda slot: images.get((slot.card_id, slot.face)), request.layout,
                    request.correction, request.cut_marks, request.title, request.profile_label,
                    progress=lambda step: self._advance(job_id, step), backs=request.backs, duplex=request.duplex,
                    back_shift=request.back_shift,
                )
            tmp.replace(target)
            self._update(job_id, stage="done", pages=pages)
        except Exception as exc:
            log.exception("print job failed")
            self._update(job_id, stage="error", error=str(exc))

    def _fetch_images(self, conn: sqlite3.Connection, job_id: str, slots: list[Slot]) -> dict[tuple[str, int], Path]:
        """PNG (745 x 1040, ~300 dpi at card size), else the large JPEG; each image once."""
        images: dict[tuple[str, int], Path] = {}
        missing: list[str] = []
        for slot in slots:
            key = (slot.card_id, slot.face)
            if key not in images and slot.name not in missing:
                path = None
                for size in ("png", "large"):
                    try:
                        path = self._cache.get(conn, slot.card_id, size, slot.face)
                        break
                    except Exception:  # no such image, or offline
                        continue
                if path is None:
                    missing.append(slot.name)
                else:
                    images[key] = path
            self._advance(job_id)
        self._update(job_id, missing_images=missing)
        return images

    def _forget_old(self) -> None:
        """Keep the newest jobs and their files only."""
        for job in sorted(self._jobs.values(), key=lambda j: j.created_at)[:-KEEP_JOBS]:
            del self._jobs[job.id]
            self.pdf_path(job.id).unlink(missing_ok=True)


def clear_print_dir(out_dir: Path) -> None:
    """PDFs of earlier runs (the job list lives in memory only)."""
    shutil.rmtree(out_dir, ignore_errors=True)
