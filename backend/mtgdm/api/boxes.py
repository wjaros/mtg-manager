from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException, Response

from mtgdm.api.deps import Db
from mtgdm.decks import boxes, service
from mtgdm.decks.boxes import BoxCombineRequest, BoxDetail, BoxError, BoxNotFound, BoxSummary, BoxUpdate
from mtgdm.decks.models import DeckDetail

router = APIRouter(prefix="/boxes", tags=["boxes"])

T = TypeVar("T")


def _handle(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except BoxNotFound as exc:
        raise HTTPException(status_code=404, detail="Box not found") from exc
    except BoxError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_boxes(db: Db) -> list[BoxSummary]:
    """Boxes of small decks (imported from Import › Boxes), newest first."""
    return boxes.list_boxes(db)


@router.get("/{box_id}")
def get_box(db: Db, box_id: int) -> BoxDetail:
    """The box with its own decks and the decks combined from them."""
    return _handle(lambda: boxes.get_box(db, box_id))


@router.patch("/{box_id}")
def rename_box(db: Db, box_id: int, body: BoxUpdate) -> BoxSummary:
    return _handle(lambda: boxes.rename_box(db, box_id, body))


@router.delete("/{box_id}", status_code=204)
def delete_box(db: Db, box_id: int, with_cards: bool = False) -> Response:
    """The box and its decks; with_cards also removes its location and the copies in it."""
    _handle(lambda: boxes.delete_box(db, box_id, with_cards))
    return Response(status_code=204)


@router.post("/{box_id}/combine", status_code=201)
def combine(db: Db, box_id: int, body: BoxCombineRequest) -> DeckDetail:
    """A new deck in the box made of these parts' cards (a copy: the parts stay)."""
    return _handle(lambda: service.get_deck(db, boxes.combine(db, box_id, body)))
