from collections.abc import Callable
from typing import Annotated, TypeVar

from fastapi import APIRouter, HTTPException, Query, Request

from mtgdm.api.deps import Db
from mtgdm.collection.missing import missing_report
from mtgdm.collection.service import LocationNotFound
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
from mtgdm.mtgjson.products import (
    ProductDeck,
    ProductDetail,
    ProductImportError,
    ProductImportRequest,
    ProductImportResult,
    ProductNotFound,
    ProductSummary,
    get_product,
    get_product_deck,
    import_product,
    search_products,
)

router = APIRouter(tags=["precons"])
T = TypeVar("T")


@router.get("/precons")
def search(
    db: Db,
    q: Annotated[str, Query(description="Words of the deck's or its commander's name, or the set code")] = "",
    type: Annotated[list[str], Query(description="Deck types, e.g. 'Commander Deck'")] = [],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[PreconSummary]:
    """Official preconstructed decks (MTGJSON), loaded with the card data sync."""
    return search_precons(db, q, type or None, limit)


@router.get("/precons/products")
def products(
    db: Db,
    q: Annotated[str, Query(description="Words of the product's, its set's or a deck's name, or the set code")] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ProductSummary]:
    """Products holding several small decks (Beginner Box, Starter Kit, Jumpstart), newest first."""
    return search_products(db, q, limit)


@router.get("/precons/products/{key}")
def product(db: Db, request: Request, key: str) -> ProductDetail:
    """The product's decks with their cards matched (fetched from MTGJSON when not stored yet)."""
    return _product_call(lambda: get_product(db, request.app.state.mtgjson, key))


@router.get("/precons/products/{key}/decks/{file_name}")
def product_deck(db: Db, request: Request, key: str, file_name: str) -> ProductDeck:
    """One deck of a big product (its decks aren't all fetched when it is opened)."""
    return _product_call(lambda: get_product_deck(db, request.app.state.mtgjson, key, file_name))


@router.post("/precons/products/{key}/import", status_code=201)
def product_import(db: Db, request: Request, key: str, body: ProductImportRequest) -> ProductImportResult:
    """Decks from the product's decks, each alone or several combined; optionally into the collection."""
    return _product_call(lambda: import_product(db, request.app.state.mtgjson, key, body))


def _product_call(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except (ProductNotFound, PreconNotFound) as exc:
        raise HTTPException(status_code=404, detail=tr("precon_not_found")) from exc
    except LocationNotFound as exc:
        raise HTTPException(status_code=404, detail="Location not found") from exc
    except ProductImportError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MtgjsonError as exc:
        raise HTTPException(status_code=502, detail=tr("precon_download_failed", error=exc)) from exc


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
