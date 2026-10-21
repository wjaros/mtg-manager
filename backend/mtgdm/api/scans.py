from collections.abc import Callable
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel

from mtgdm.api.deps import AppSettings, Db
from mtgdm.scan import service
from mtgdm.scan.ocr.base import available_engines, default_engine_name
from mtgdm.scan.service import CommitResult, GridRequest, Scan, ScanError, ScanItemUpdate, ScanNotFound

router = APIRouter(tags=["scans"])

T = TypeVar("T")


def _handle(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except ScanNotFound as exc:
        raise HTTPException(status_code=404, detail="Scan not found") from exc
    except ScanError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class OcrEngines(BaseModel):
    available: list[str]
    default: str


@router.get("/scan-engines")
def engines() -> OcrEngines:
    return OcrEngines(available=available_engines(), default=default_engine_name())


@router.get("/scans")
def list_scans(db: Db) -> list[Scan]:
    return service.list_scans(db)


@router.post("/scans", status_code=201)
async def upload(
    request: Request,
    db: Db,
    settings: AppSettings,
    file: Annotated[UploadFile, File(description="Photo or scan (JPG, PNG, HEIC, WEBP, TIFF)")],
    kind: Annotated[Literal["auto", "single", "page"], Form()] = "auto",
    engine: Annotated[str | None, Form()] = None,
) -> list[Scan]:
    """Upload a photo, scan or PDF, recognize the cards and return the result for review (nothing
    is added yet). auto: a page when at least two cards are found. One scan per PDF page."""
    if engine and engine not in available_engines():
        raise HTTPException(status_code=422, detail=f"OCR engine not available: {engine}")
    data = await file.read()
    recognizer = request.app.state.recognizer
    return await run_in_threadpool(
        _handle, lambda: service.create_scans(db, settings.scans_dir, recognizer, data, file.filename or "upload", kind, engine)
    )


@router.post("/scans/{scan_id}/grid")
async def regrid(request: Request, db: Db, scan_id: int, body: GridRequest) -> Scan:
    """Fallback when cards were not found: cut the page (or a region) into rows x cols cards."""
    recognizer = request.app.state.recognizer
    return await run_in_threadpool(
        _handle, lambda: service.regrid_scan(db, recognizer, scan_id, body.rows, body.cols, body.region)
    )


@router.get("/scans/{scan_id}")
def get_scan(db: Db, scan_id: int) -> Scan:
    return _handle(lambda: service.get_scan(db, scan_id))


@router.patch("/scans/{scan_id}/items/{item_id}")
def update_item(db: Db, scan_id: int, item_id: int, body: ScanItemUpdate) -> Scan:
    """Choose the card, accept / reject, set quantity, finish, language, condition and location."""
    return _handle(lambda: service.update_item(db, scan_id, item_id, body))


@router.post("/scans/{scan_id}/commit")
def commit(db: Db, scan_id: int) -> CommitResult:
    """Add the accepted items to the collection."""
    return _handle(lambda: service.commit_scan(db, scan_id))


@router.delete("/scans/{scan_id}", status_code=204)
def delete(db: Db, settings: AppSettings, scan_id: int) -> Response:
    _handle(lambda: service.delete_scan(db, settings.scans_dir, scan_id))
    return Response(status_code=204)


# Scan and item ids are reused after deletes (and a manual grid replaces the items), so the same
# URL can point to a different image: the browser must revalidate (ETag) instead of caching.
NO_CACHE = {"Cache-Control": "no-cache"}


@router.get("/scans/{scan_id}/image", response_class=FileResponse)
def original_image(db: Db, scan_id: int) -> FileResponse:
    return FileResponse(_handle(lambda: service.crop_path(db, scan_id, None)), media_type="image/jpeg",
                        headers=NO_CACHE)


@router.get("/scans/{scan_id}/items/{item_id}/image", response_class=FileResponse)
def item_image(db: Db, scan_id: int, item_id: int) -> FileResponse:
    """The straightened card as it was read."""
    return FileResponse(_handle(lambda: service.crop_path(db, scan_id, item_id)), media_type="image/jpeg",
                        headers=NO_CACHE)
