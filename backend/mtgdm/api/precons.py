from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from mtgdm.api.deps import Db
from mtgdm.collection.missing import missing_report
from mtgdm.decks.service import DeckNotFound
from mtgdm.i18n import tr
from mtgdm.mtgjson.client import MtgjsonError
from mtgdm.mtgjson.precons import (
    PreconDecklist,
    PreconNotFound,
    PreconOverview,
    PreconSuggestion,
    PreconSummary,
    browse_precons,
    precon_decklist,
    precons_for_missing,
    search_precons,
)

router = APIRouter(tags=["precons"])


@router.get("/precons")
def search(
    db: Db,
    q: Annotated[str, Query(description="Words of the deck's or its commander's name, or the set code")] = "",
    type: Annotated[list[str], Query(description="Deck types, e.g. 'Commander Deck'")] = [],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[PreconSummary]:
    """Official preconstructed decks (MTGJSON), loaded with the card data sync."""
    return search_precons(db, q, type or None, limit)


@router.get("/precons/commander")
def commander_precons(db: Db) -> list[PreconOverview]:
    """Commander precons with their commanders' colors, what you own of them and the cards' value."""
    return browse_precons(db)


@router.get("/decks/{deck_id}/missing/precons")
def missing_precons(db: Db, deck_id: int, exclude_other_decks: bool = False) -> list[PreconSuggestion]:
    """Precons that contain several of the cards this deck is missing."""
    try:
        report = missing_report(db, deck_id, exclude_other_decks)
    except DeckNotFound as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc
    return precons_for_missing(db, {e.oracle_id: (e.name, e.missing) for e in report.entries})


@router.get("/precons/{file_name}/decklist")
def decklist(db: Db, request: Request, file_name: str) -> PreconDecklist:
    """The deck as text for the import (its cards are fetched from MTGJSON when not stored yet)."""
    try:
        return precon_decklist(db, request.app.state.mtgjson, file_name)
    except PreconNotFound as exc:
        raise HTTPException(status_code=404, detail=tr("precon_not_found")) from exc
    except MtgjsonError as exc:
        raise HTTPException(status_code=502, detail=tr("precon_download_failed", error=exc)) from exc
