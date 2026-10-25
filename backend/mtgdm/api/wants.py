from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from mtgdm.api.deps import Db
from mtgdm.collection.wants import (
    WantList,
    WantsFormat,
    add_deck_missing,
    add_want,
    reduce_want,
    remove_want,
    render_wants,
    want_list,
)
from mtgdm.decks.service import CardNotFound, DeckNotFound

router = APIRouter(tags=["wants"])

T = TypeVar("T")


def _handle(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except CardNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Card not found: {exc}") from exc
    except DeckNotFound as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc


class WantAdd(BaseModel):
    card_id: str
    quantity: int = Field(default=1, ge=1, le=99)


class DeckWantsResult(BaseModel):
    added: int  # copies the deck put on the list
    wants: WantList


@router.get("/wants")
def get_wants(db: Db) -> WantList:
    """Cards to buy: copies added by hand and decks' missing copies, minus those bought since."""
    return want_list(db)


@router.post("/wants")
def post_want(db: Db, body: WantAdd) -> WantList:
    _handle(lambda: add_want(db, body.card_id, body.quantity))
    return want_list(db)


@router.post("/wants/{oracle_id}/reduce")
def post_reduce_want(db: Db, oracle_id: str, quantity: int = 1) -> WantList:
    reduce_want(db, oracle_id, quantity)
    return want_list(db)


@router.delete("/wants/{oracle_id}")
def delete_want(db: Db, oracle_id: str) -> WantList:
    remove_want(db, oracle_id)
    return want_list(db)


@router.delete("/wants")
def clear_wants(db: Db) -> WantList:
    remove_want(db)
    return want_list(db)


@router.post("/decks/{deck_id}/wants")
def post_deck_wants(
    db: Db, deck_id: int, exclude_other_decks: bool = False, include_proxied: bool = True
) -> DeckWantsResult:
    """Put the deck's missing cards on the list (replacing what this deck added before)."""
    added = _handle(lambda: add_deck_missing(db, deck_id, exclude_other_decks, include_proxied))
    return DeckWantsResult(added=added, wants=want_list(db))


@router.get("/wants/export", response_class=PlainTextResponse)
def export_wants(db: Db, format: WantsFormat = "cardmarket") -> PlainTextResponse:
    body = render_wants(want_list(db), format)
    if format == "csv":
        return PlainTextResponse(
            body,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="wants.csv"'},
        )
    return PlainTextResponse(body)
