from datetime import date
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import JSONResponse

from mtgdm import cloud_backup
from mtgdm.api.deps import Db
from mtgdm.backup import BackupError, ImportResult, export_backup, import_backup
from mtgdm.cloud_backup import CloudBackupSettings, CloudBackupStatus, FolderError
from mtgdm.i18n import tr

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


@router.get("/cloud")
def cloud_status(db: Db) -> CloudBackupStatus:
    """Automatic backups into a (synced) folder: settings, last write, and a newer backup written by
    another computer, if there is one."""
    return cloud_backup.status(db)


@router.put("/cloud")
def cloud_settings(db: Db, body: CloudBackupSettings) -> CloudBackupStatus:
    try:
        cloud_backup.save_settings(db, body)
        if body.enabled:
            cloud_backup.write_if_changed(db)
    except FolderError as exc:
        raise HTTPException(status_code=422, detail=tr("cloud_folder_error", error=exc)) from exc
    return cloud_backup.status(db)


@router.post("/cloud/write")
def cloud_write(db: Db) -> CloudBackupStatus:
    """Write the backup now."""
    try:
        cloud_backup.write_if_changed(db, force=True)
    except FolderError as exc:
        raise HTTPException(status_code=422, detail=tr("cloud_folder_error", error=exc)) from exc
    return cloud_backup.status(db)


@router.post("/cloud/load")
def cloud_load(db: Db) -> ImportResult:
    """Replace this computer's data with the newer backup from another one (this one's is kept in
    the folder's history)."""
    try:
        return cloud_backup.load_newer(db)
    except (FolderError, BackupError) as exc:
        raise HTTPException(status_code=422, detail=tr("cloud_folder_error", error=exc)) from exc


@router.post("/cloud/dismiss", status_code=204)
def cloud_dismiss(db: Db) -> None:
    """Keep this computer's data; don't offer that backup again."""
    cloud_backup.dismiss_newer(db)
