"""Scans as stored records: upload -> recognition -> review -> commit to the collection."""

import io
import json
import logging
import shutil
import sqlite3
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

from mtgdm.cards.models import CardSummary
from mtgdm.cards.search import card_summaries
from mtgdm.collection.models import Condition, Finish
from mtgdm.i18n import tr
from mtgdm.scan.match import Matcher
from mtgdm.scan.ocr.base import get_engine
from mtgdm.scan.pipeline import ScannedCard, scan_grid, scan_image
from mtgdm.scryfall.bulk import META_UPDATED_AT, get_meta

log = logging.getLogger(__name__)

MAX_SIDE = 3000             # working resolution
MAX_UPLOAD_BYTES = 40_000_000
MAX_PDF_PAGES = 50
PDF_DPI = 300
SUPPORTED = (".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp")  # + .pdf

ItemStatus = Literal["pending", "accepted", "rejected"]


class ScanError(ValueError):
    pass


class ScanNotFound(LookupError):
    pass


class ScanCandidate(BaseModel):
    card: CardSummary
    score: float
    reasons: list[str]


class ScanItem(BaseModel):
    id: int
    corners: list[list[float]]
    ocr_name: str | None
    ocr_set: str | None
    ocr_number: str | None
    ocr_language: str | None
    candidates: list[ScanCandidate]
    chosen: CardSummary | None
    confidence: float
    status: ItemStatus
    quantity: int
    finish: Finish
    language: str | None
    condition: Condition
    location_id: int | None


class Scan(BaseModel):
    id: int
    kind: Literal["single", "page"]
    original_name: str | None
    created_at: str
    status: str            # processed | failed | committed
    ocr_engine: str | None
    error: str | None
    items: list[ScanItem]


class ScanItemUpdate(BaseModel):
    chosen_card_id: str | None = None
    status: ItemStatus | None = None
    quantity: int | None = Field(default=None, ge=1, le=999)
    finish: Finish | None = None
    language: str | None = None
    condition: Condition | None = None
    location_id: int | None = None


class GridRequest(BaseModel):
    rows: int = Field(ge=1, le=6)
    cols: int = Field(ge=1, le=6)
    # Relative x0, y0, x1, y1 of the area holding the cards; whole page when omitted.
    region: tuple[float, float, float, float] | None = None


class CommitResult(BaseModel):
    added: int        # copies added to the collection
    items: int


class Recognizer:
    """Shared matcher (name index is expensive to build) with its own connection; rebuilt when the
    card data changes. Recognition is serialized: OCR engines are not thread safe."""

    def __init__(self, db_path: Path, load_image_factory: Callable[[sqlite3.Connection], Callable]):
        self._db_path = db_path
        self._load_image_factory = load_image_factory
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._matcher: Matcher | None = None
        self._data_version: str | None = None

    def scan(self, image: np.ndarray, engine_name: str | None, kind: str = "auto") -> list[ScannedCard]:
        return self._run(lambda matcher, engine, load: scan_image(image, matcher, engine, load_image=load, kind=kind),
                         engine_name)

    def grid(self, image: np.ndarray, engine_name: str | None, rows: int, cols: int,
             region: tuple[float, float, float, float] | None) -> list[ScannedCard]:
        return self._run(
            lambda matcher, engine, load: scan_grid(image, matcher, engine, rows, cols, region=region, load_image=load),
            engine_name,
        )

    def _run(self, action, engine_name: str | None) -> list[ScannedCard]:
        from mtgdm.db import connect

        with self._lock:
            if self._conn is None:
                self._conn = connect(self._db_path)
            version = get_meta(self._conn, META_UPDATED_AT)
            if self._matcher is None or version != self._data_version:
                self._matcher, self._data_version = Matcher(self._conn), version
            return action(self._matcher, get_engine(engine_name), self._load_image_factory(self._conn))

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()


def decode_images(data: bytes, filename: str) -> list[np.ndarray]:
    """Upload bytes -> BGR images (one per PDF page), EXIF orientation applied, at most MAX_SIDE px."""
    name = filename.lower()
    if name.endswith(".pdf"):
        return _pdf_pages(data)
    if not name.endswith(SUPPORTED):
        raise ScanError(tr("scan_bad_type"))
    try:
        if name.endswith((".heic", ".heif")):
            # macOS reads HEIC itself; elsewhere it would take libheif (+12 MB of codecs) in the bundle,
            # and iPhones can save JPG instead.
            if sys.platform != "darwin":
                raise ScanError(tr("scan_heic_macos_only"))
            from mtgdm.scan.imageio_mac import decode

            return [cv2.cvtColor(decode(data, MAX_SIDE), cv2.COLOR_RGB2BGR)]
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        image = image.convert("RGB")
    except ScanError:
        raise
    except Exception as exc:  # any decoding problem is the file's fault
        raise ScanError(tr("scan_bad_image", error=exc)) from exc
    image.thumbnail((MAX_SIDE, MAX_SIDE))
    return [cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)]


def _pdf_pages(data: bytes) -> list[np.ndarray]:
    """Scanner PDFs: every page rendered at 300 dpi."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ScanError(tr("scan_bad_pdf", error=exc)) from exc
    try:
        if len(pdf) > MAX_PDF_PAGES:
            raise ScanError(tr("scan_pdf_pages", n=len(pdf), max=MAX_PDF_PAGES))
        pages = []
        for page in pdf:
            image = page.render(scale=PDF_DPI / 72).to_pil().convert("RGB")
            image.thumbnail((MAX_SIDE + 600, MAX_SIDE + 600))  # A4 at 300 dpi is 3508 px high: keep it
            pages.append(cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR))
        return pages
    finally:
        pdf.close()


def create_scans(conn: sqlite3.Connection, scans_dir: Path, recognizer: Recognizer, data: bytes, filename: str,
                 kind: str = "auto", engine: str | None = None) -> list[Scan]:
    """One scan per image (per page for PDFs): stored, recognized, ready for review."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ScanError(tr("scan_too_large"))
    images = decode_images(data, filename)
    scans = []
    for number, image in enumerate(images, start=1):
        label = filename if len(images) == 1 else f"{filename} (str. {number})"
        scans.append(_create_scan(conn, scans_dir, recognizer, image, label, kind, engine))
    return scans


def _create_scan(conn: sqlite3.Connection, scans_dir: Path, recognizer: Recognizer, image: np.ndarray,
                 label: str, kind: str, engine: str | None) -> Scan:
    with conn:
        scan_id = conn.execute(
            "INSERT INTO scans(file_path, kind, status, original_name, ocr_engine) VALUES ('', ?, 'processing', ?, ?)",
            ("page" if kind == "page" else "single", label, engine or get_engine().name),
        ).lastrowid
    folder = scans_dir / str(scan_id)
    folder.mkdir(parents=True, exist_ok=True)
    original = folder / "original.jpg"
    cv2.imwrite(str(original), image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    with conn:
        conn.execute("UPDATE scans SET file_path = ? WHERE id = ?", (str(original), scan_id))
    try:
        cards = recognizer.scan(image, engine, kind)
    except Exception as exc:
        log.exception("Recognition failed for scan %s", scan_id)
        with conn:
            conn.execute("UPDATE scans SET status = 'failed', error = ? WHERE id = ?", (str(exc), scan_id))
        raise ScanError(tr("scan_failed", error=exc)) from exc
    _save_items(conn, scan_id, folder, cards)
    return get_scan(conn, scan_id)


def regrid_scan(conn: sqlite3.Connection, recognizer: Recognizer, scan_id: int, rows: int, cols: int,
                region: tuple[float, float, float, float] | None, engine: str | None = None) -> Scan:
    """Replace the automatic result with a rows x cols grid over the page (or a region of it)."""
    row = conn.execute("SELECT status, file_path, ocr_engine FROM scans WHERE id = ?", (scan_id,)).fetchone()
    if row is None:
        raise ScanNotFound(scan_id)
    if row["status"] == "committed":
        raise ScanError(tr("scan_committed"))
    image = cv2.imread(row["file_path"])
    if image is None:
        raise ScanError(tr("scan_no_file"))
    cards = recognizer.grid(image, engine or row["ocr_engine"], rows, cols, region)
    folder = Path(row["file_path"]).parent
    for old in folder.glob("card-*.jpg"):
        old.unlink()
    with conn:
        conn.execute("DELETE FROM scan_items WHERE scan_id = ?", (scan_id,))
        conn.execute("UPDATE scans SET kind = 'page' WHERE id = ?", (scan_id,))
    _save_items(conn, scan_id, folder, cards)
    return get_scan(conn, scan_id)


def _save_items(conn: sqlite3.Connection, scan_id: int, folder: Path, cards: list[ScannedCard]) -> None:
    with conn:
        conn.execute("UPDATE scans SET status = 'processed', kind = ? WHERE id = ?",
                     ("page" if len(cards) > 1 else "single", scan_id))
        for index, card in enumerate(cards):
            crop = folder / f"card-{index}.jpg"
            cv2.imwrite(str(crop), card.image, [cv2.IMWRITE_JPEG_QUALITY, 90])
            top = card.candidates[0] if card.candidates else None
            conn.execute(
                """
                INSERT INTO scan_items(scan_id, crop_path, bbox, ocr_name, ocr_set, ocr_number, ocr_text, ocr_language,
                                       candidates, chosen_card_id, confidence, status, language)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (scan_id, str(crop), json.dumps(card.corners.round(1).tolist()), card.text.name, card.text.set_code,
                 card.text.collector_number, card.text.text, card.text.language,
                 json.dumps([{"card_id": c.card_id, "score": round(c.score, 3), "reasons": c.reasons}
                             for c in card.candidates]),
                 top.card_id if top else None, round(card.confidence, 3), card.text.language),
            )


def get_scan(conn: sqlite3.Connection, scan_id: int) -> Scan:
    row = conn.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
    if row is None:
        raise ScanNotFound(scan_id)
    items = conn.execute("SELECT * FROM scan_items WHERE scan_id = ? ORDER BY id", (scan_id,)).fetchall()
    card_ids = {i["chosen_card_id"] for i in items if i["chosen_card_id"]}
    for i in items:
        card_ids.update(c["card_id"] for c in json.loads(i["candidates"] or "[]"))
    cards = {c.id: c for c in card_summaries(conn, list(card_ids))}
    return Scan(
        id=row["id"], kind=row["kind"], original_name=row["original_name"], created_at=row["created_at"],
        status=row["status"], ocr_engine=row["ocr_engine"], error=row["error"],
        items=[
            ScanItem(
                id=i["id"],
                corners=json.loads(i["bbox"] or "[]"),
                ocr_name=i["ocr_name"], ocr_set=i["ocr_set"], ocr_number=i["ocr_number"], ocr_language=i["ocr_language"],
                candidates=[ScanCandidate(card=cards[c["card_id"]], score=c["score"], reasons=c["reasons"])
                            for c in json.loads(i["candidates"] or "[]") if c["card_id"] in cards],
                chosen=cards.get(i["chosen_card_id"]),
                confidence=i["confidence"] or 0.0,
                status=i["status"], quantity=i["quantity"], finish=i["finish"], language=i["language"],
                condition=i["condition"], location_id=i["location_id"],
            )
            for i in items
        ],
    )


def list_scans(conn: sqlite3.Connection, limit: int = 50) -> list[Scan]:
    ids = [r[0] for r in conn.execute("SELECT id FROM scans ORDER BY id DESC LIMIT ?", (limit,))]
    return [get_scan(conn, i) for i in ids]


def update_item(conn: sqlite3.Connection, scan_id: int, item_id: int, data: ScanItemUpdate) -> Scan:
    item = conn.execute("SELECT id FROM scan_items WHERE id = ? AND scan_id = ?", (item_id, scan_id)).fetchone()
    if item is None:
        raise ScanNotFound(item_id)
    changes = data.model_dump(exclude_unset=True)
    if "chosen_card_id" in changes and changes["chosen_card_id"] is not None:
        if conn.execute("SELECT 1 FROM cards WHERE id = ?", (changes["chosen_card_id"],)).fetchone() is None:
            raise ScanError(tr("unknown_card"))
        changes.setdefault("status", "accepted")  # picking a card by hand means accepting it
    if changes:
        with conn:
            conn.execute(
                f"UPDATE scan_items SET {', '.join(f'{k} = ?' for k in changes)} WHERE id = ?",
                [*changes.values(), item_id],
            )
    return get_scan(conn, scan_id)


def commit_scan(conn: sqlite3.Connection, scan_id: int) -> CommitResult:
    """Accepted items -> collection copies (source 'scan'). A scan is committed once."""
    scan = conn.execute("SELECT status FROM scans WHERE id = ?", (scan_id,)).fetchone()
    if scan is None:
        raise ScanNotFound(scan_id)
    if scan["status"] == "committed":
        raise ScanError(tr("scan_committed"))
    items = conn.execute(
        "SELECT * FROM scan_items WHERE scan_id = ? AND status = 'accepted' AND chosen_card_id IS NOT NULL",
        (scan_id,),
    ).fetchall()
    added = 0
    with conn:
        for i in items:
            lang = i["language"] or conn.execute("SELECT lang FROM cards WHERE id = ?", (i["chosen_card_id"],)).fetchone()[0]
            conn.execute(
                """
                INSERT INTO collection_items(card_id, quantity, finish, language, condition, location_id, source, scan_item_id)
                VALUES (?, ?, ?, ?, ?, ?, 'scan', ?)
                """,
                (i["chosen_card_id"], i["quantity"], i["finish"], lang, i["condition"], i["location_id"], i["id"]),
            )
            added += i["quantity"]
        conn.execute("UPDATE scans SET status = 'committed', committed_at = datetime('now') WHERE id = ?", (scan_id,))
    return CommitResult(added=added, items=len(items))


def delete_scan(conn: sqlite3.Connection, scans_dir: Path, scan_id: int) -> None:
    """Remove a scan and its files; copies already added to the collection stay."""
    with conn:  # items cascade; collection copies keep existing (their scan_item_id becomes NULL)
        if conn.execute("DELETE FROM scans WHERE id = ?", (scan_id,)).rowcount == 0:
            raise ScanNotFound(scan_id)
    shutil.rmtree(scans_dir / str(scan_id), ignore_errors=True)


def crop_path(conn: sqlite3.Connection, scan_id: int, item_id: int | None) -> Path:
    if item_id is None:
        row = conn.execute("SELECT file_path FROM scans WHERE id = ?", (scan_id,)).fetchone()
    else:
        row = conn.execute("SELECT crop_path FROM scan_items WHERE id = ? AND scan_id = ?", (item_id, scan_id)).fetchone()
    if row is None or not row[0] or not Path(row[0]).is_file():
        raise ScanNotFound(item_id or scan_id)
    return Path(row[0])
