import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from mtgdm.api.deps import AppSettings, Db
from mtgdm.scryfall.bulk import BULK_TYPE, META_UPDATED_AT, get_meta
from mtgdm.scryfall.client import ScryfallClient, ScryfallError
from mtgdm.scryfall.manager import SyncManager

router = APIRouter(prefix="/sync", tags=["sync"])

EVENT_POLL_SECONDS = 0.5


class SyncProgressModel(BaseModel):
    running: bool
    stage: str | None
    done: int
    total: int
    started_at: float | None
    finished_at: float | None
    error: str | None
    result: dict[str, Any] | None
    version: int


class SyncStatus(BaseModel):
    progress: SyncProgressModel
    card_count: int
    oracle_count: int
    set_count: int
    cards_updated_at: str | None
    sets_synced_at: str | None
    data_dir: str
    db_size_bytes: int


class SyncCheck(BaseModel):
    local_updated_at: str | None
    remote_updated_at: str
    update_available: bool


class SyncStart(BaseModel):
    force: bool = False


def _manager(request: Request) -> SyncManager:
    return request.app.state.sync_manager


def _progress(manager: SyncManager) -> SyncProgressModel:
    return SyncProgressModel(**asdict(manager.snapshot()))


@router.get("/status")
def status(request: Request, db: Db, settings: AppSettings) -> SyncStatus:
    counts = db.execute(
        "SELECT (SELECT COUNT(*) FROM cards), (SELECT COUNT(*) FROM oracle_cards), (SELECT COUNT(*) FROM sets)"
    ).fetchone()
    db_size = sum(p.stat().st_size for p in settings.data_dir.glob("db.sqlite*") if p.is_file())
    return SyncStatus(
        progress=_progress(_manager(request)),
        card_count=counts[0],
        oracle_count=counts[1],
        set_count=counts[2],
        cards_updated_at=get_meta(db, META_UPDATED_AT),
        sets_synced_at=get_meta(db, "sets_synced_at"),
        data_dir=str(settings.data_dir),
        db_size_bytes=db_size,
    )


@router.get("/check")
def check(request: Request, db: Db) -> SyncCheck:
    """Ask Scryfall whether newer bulk data exists (one API request)."""
    client: ScryfallClient = request.app.state.scryfall
    try:
        remote = client.bulk_data(BULK_TYPE)["updated_at"]
    except (ScryfallError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail=f"Scryfall unavailable: {exc}") from exc
    local = get_meta(db, META_UPDATED_AT)
    return SyncCheck(local_updated_at=local, remote_updated_at=remote, update_available=local != remote)


@router.post("/start", status_code=202)
def start(request: Request, body: SyncStart | None = None) -> SyncProgressModel:
    manager = _manager(request)
    if not manager.start(force=bool(body and body.force)):
        raise HTTPException(status_code=409, detail="Sync already running")
    return _progress(manager)


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Server-sent events with sync progress; the stream ends when no sync is running."""
    manager = _manager(request)

    async def stream() -> AsyncIterator[str]:
        last_version = -1
        while not await request.is_disconnected():
            progress = manager.snapshot()
            if progress.version != last_version:
                last_version = progress.version
                yield f"data: {json.dumps(asdict(progress))}\n\n"
            if not progress.running:
                return
            await asyncio.sleep(EVENT_POLL_SECONDS)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
