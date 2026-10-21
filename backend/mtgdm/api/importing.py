from fastapi import APIRouter, HTTPException

from mtgdm.api.deps import AppSettings, Db
from mtgdm.decks import importer
from mtgdm.decks.models import (
    DeckDetail,
    ImportCommitRequest,
    ImportParseRequest,
    ImportReport,
    SeedInfo,
)
from mtgdm.decks.service import CardNotFound

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/parse")
def parse(db: Db, body: ImportParseRequest) -> ImportReport:
    """Match a pasted decklist against the card database; nothing is saved."""
    return importer.build_report(db, body.text, body.platform, body.preferred_sets)


@router.post("/commit", status_code=201)
def commit(db: Db, body: ImportCommitRequest) -> DeckDetail:
    """Create a deck from the reviewed import entries."""
    try:
        return importer.commit(db, body)
    except CardNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Card not found: {exc}") from exc


@router.get("/seeds")
def seeds(settings: AppSettings) -> list[SeedInfo]:
    """Example decklists shipped with the app (seeds/*.txt)."""
    return importer.list_seeds(settings.seeds_dir)
