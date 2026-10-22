from collections.abc import Callable
from typing import Annotated, Literal, TypeVar

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import PlainTextResponse

from mtgdm.api.deps import Db
from mtgdm.collection import service
from mtgdm.collection.export import ExportFormat, export_collection
from mtgdm.collection.missing import Holding, MissingReport, deck_holdings, missing_report, render_missing
from mtgdm.collection.models import (
    CollectionItem,
    CollectionItemCreate,
    CollectionItemUpdate,
    CollectionStats,
    DeckToCollectionResult,
    Location,
    LocationCreate,
    LocationUpdate,
    ReplaceWithReal,
)
from mtgdm.collection.moxfield import (
    CollectionImportCommit,
    CollectionImportReport,
    CollectionImportRequest,
    CollectionImportResult,
    commit_moxfield,
    export_moxfield,
    parse_moxfield,
)
from mtgdm.collection.service import ItemNotFound, LocationNotEmpty, LocationNotFound, NotAProxy
from mtgdm.decks.service import CardNotFound, DeckNotFound
from mtgdm.i18n import tr

router = APIRouter(tags=["collection"])

T = TypeVar("T")


def _handle(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except ItemNotFound as exc:
        raise HTTPException(status_code=404, detail="Collection entry not found") from exc
    except LocationNotFound as exc:
        raise HTTPException(status_code=404, detail="Location not found") from exc
    except CardNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Card not found: {exc}") from exc
    except DeckNotFound as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc
    except LocationNotEmpty as exc:
        raise HTTPException(status_code=409, detail="This deck's cards are already in the collection") from exc
    except NotAProxy as exc:
        raise HTTPException(status_code=422, detail=tr("not_a_proxy")) from exc


@router.get("/collection")
def list_items(
    db: Db,
    card_id: str | None = None,
    oracle_id: str | None = None,
    location_id: int | None = None,
    unassigned: Annotated[bool, Query(description="Only copies without a location")] = False,
    q: Annotated[str | None, Query(description="Card name contains")] = None,
    kind: Annotated[Literal["real", "proxy", "all"], Query(description="Real copies, proxies or both")] = "all",
) -> list[CollectionItem]:
    return service.list_items(
        db, card_id=card_id, oracle_id=oracle_id, location_id=location_id, unassigned=unassigned, q=q, kind=kind
    )


@router.get("/collection/export", response_class=PlainTextResponse)
def collection_export(
    db: Db,
    format: ExportFormat | Literal["moxfield"] = "arena",
    location_id: int | None = None,
    unassigned: Annotated[bool, Query(description="Only copies without a location")] = False,
    download: bool = False,
) -> PlainTextResponse:
    """The collection (or one location) as an Arena-style list or CSV."""
    if format == "moxfield":
        body = export_moxfield(db, location_id, unassigned)
    else:
        body = export_collection(db, format, location_id, unassigned)
    csv_file = format in ("csv", "moxfield")
    media_type = "text/csv; charset=utf-8" if csv_file else "text/plain; charset=utf-8"
    headers = {}
    if download or csv_file:
        name = "collection-moxfield.csv" if format == "moxfield" else f"collection.{'csv' if csv_file else 'txt'}"
        headers["Content-Disposition"] = f'attachment; filename="{name}"'
    return PlainTextResponse(body, media_type=media_type, headers=headers)


@router.post("/collection/import/moxfield/parse")
def collection_import_parse(db: Db, body: CollectionImportRequest) -> CollectionImportReport:
    """Match a Moxfield collection CSV against the card data; nothing is saved."""
    return parse_moxfield(db, body.text)


@router.post("/collection/import/commit")
def collection_import_commit(db: Db, body: CollectionImportCommit) -> CollectionImportResult:
    """Add reviewed entries to the collection (optionally into one location): from a Moxfield CSV
    report, or from a decklist report (/api/import/parse) of a product that is not a deck."""
    return _handle(lambda: commit_moxfield(db, body))


@router.get("/collection/stats")
def collection_stats(db: Db) -> CollectionStats:
    return service.stats(db)


@router.post("/collection", status_code=201)
def add_item(db: Db, body: CollectionItemCreate) -> CollectionItem:
    return _handle(lambda: service.add_item(db, body))


@router.patch("/collection/{item_id}")
def update_item(db: Db, item_id: int, body: CollectionItemUpdate) -> CollectionItem:
    return _handle(lambda: service.update_item(db, item_id, body))


@router.post("/collection/{item_id}/replace-with-real")
def replace_with_real(db: Db, item_id: int, body: ReplaceWithReal) -> CollectionItem:
    """One copy of a proxy becomes a real card in the same place (a new copy, or a loose one moved
    there). Returns the real entry."""
    return _handle(lambda: service.replace_with_real(db, item_id, body))


@router.delete("/collection/{item_id}")
def remove_item(
    db: Db,
    item_id: int,
    quantity: Annotated[int | None, Query(ge=1, description="Copies to remove; all when omitted")] = None,
) -> CollectionItem | None:
    """Returns the remaining entry, or null when it was removed completely."""
    return _handle(lambda: service.remove_item(db, item_id, quantity))


@router.get("/locations")
def list_locations(db: Db) -> list[Location]:
    return service.list_locations(db)


@router.post("/locations", status_code=201)
def create_location(db: Db, body: LocationCreate) -> Location:
    return service.create_location(db, body)


@router.patch("/locations/{location_id}")
def update_location(db: Db, location_id: int, body: LocationUpdate) -> Location:
    return _handle(lambda: service.update_location(db, location_id, body))


@router.delete("/locations/{location_id}", status_code=204)
def delete_location(db: Db, location_id: int) -> Response:
    _handle(lambda: service.delete_location(db, location_id))
    return Response(status_code=204)


@router.post("/decks/{deck_id}/collection")
def deck_to_collection(db: Db, deck_id: int, replace: bool = False) -> DeckToCollectionResult:
    """'I own this deck': add its cards to the collection in the deck's box location."""
    return _handle(lambda: service.add_deck_to_collection(db, deck_id, replace))


@router.get("/decks/{deck_id}/holdings")
def deck_holdings_endpoint(db: Db, deck_id: int) -> list[Holding]:
    """Per card of the deck: copies needed, owned anywhere, in the deck's box, missing."""
    return _handle(lambda: deck_holdings(db, deck_id))


@router.get("/decks/{deck_id}/missing")
def deck_missing(db: Db, deck_id: int, exclude_other_decks: bool = False) -> MissingReport:
    """Cards the deck needs beyond the collection; optionally ignoring copies in other decks' boxes."""
    return _handle(lambda: missing_report(db, deck_id, exclude_other_decks))


@router.get("/decks/{deck_id}/missing/export", response_class=PlainTextResponse)
def deck_missing_export(
    db: Db,
    deck_id: int,
    format: Literal["text", "cardmarket", "csv"] = "cardmarket",
    exclude_other_decks: bool = False,
    include_proxied: Annotated[bool, Query(description="Include cards a proxy stands in for (a shopping list)")] = True,
) -> PlainTextResponse:
    report = _handle(lambda: missing_report(db, deck_id, exclude_other_decks))
    body = render_missing(report, format, include_proxied)
    if format == "csv":
        return PlainTextResponse(
            body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="missing-deck-{deck_id}.csv"'},
        )
    return PlainTextResponse(body)
