from datetime import date
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from mtgdm.api.deps import Db
from mtgdm.backup import BackupError, ImportResult, export_backup, import_backup

router = APIRouter(prefix="/backup", tags=["backup"])


@router.get("/export")
def export(db: Db) -> JSONResponse:
    """Collection, locations and decks as a downloadable JSON file (no Scryfall data)."""
    return JSONResponse(
        export_backup(db),
        headers={"Content-Disposition": f'attachment; filename="mtgdm-backup-{date.today().isoformat()}.json"'},
    )


@router.post("/import")
def restore(db: Db, data: dict[str, Any] = Body(...), replace: bool = False) -> ImportResult:
    """Restore a backup file; with replace=true the current collection and decks are removed first."""
    try:
        return import_backup(db, data, replace)
    except BackupError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
