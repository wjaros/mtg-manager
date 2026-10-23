from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request

from mtgdm.api.deps import Db
from mtgdm.i18n import tr
from mtgdm.mtgjson.client import MtgjsonError
from mtgdm.mtgjson.precons import PreconDecklist, PreconNotFound, PreconSummary, precon_decklist, search_precons

router = APIRouter(prefix="/precons", tags=["precons"])


@router.get("")
def search(
    db: Db,
    q: Annotated[str, Query(description="Words of the deck's or its commander's name, or the set code")] = "",
    type: Annotated[list[str], Query(description="Deck types, e.g. 'Commander Deck'")] = [],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[PreconSummary]:
    """Official preconstructed decks (MTGJSON), loaded with the card data sync."""
    return search_precons(db, q, type or None, limit)


@router.get("/{file_name}/decklist")
def decklist(db: Db, request: Request, file_name: str) -> PreconDecklist:
    """The deck as text for the import (its cards are fetched from MTGJSON when not stored yet)."""
    try:
        return precon_decklist(db, request.app.state.mtgjson, file_name)
    except PreconNotFound as exc:
        raise HTTPException(status_code=404, detail=tr("precon_not_found")) from exc
    except MtgjsonError as exc:
        raise HTTPException(status_code=502, detail=tr("precon_download_failed", error=exc)) from exc
