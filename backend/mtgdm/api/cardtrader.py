from collections.abc import Callable
from datetime import date
from typing import Literal, TypeVar

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from mtgdm.api.deps import Db
from mtgdm.cardtrader.client import CardTraderClient, CardTraderError
from mtgdm.cardtrader.wishlists import (
    CardTraderStatus,
    NothingToSend,
    WishlistResult,
    deck_lines,
    forget_token,
    save_token,
    send_wishlist,
    status,
    token,
    wants_lines,
)
from mtgdm.decks.service import DeckNotFound
from mtgdm.i18n import tr

router = APIRouter(tags=["cardtrader"])

T = TypeVar("T")


class TokenBody(BaseModel):
    token: str = Field(min_length=1, max_length=4000)


class WishlistRequest(BaseModel):
    source: Literal["deck", "wants"]  # a deck's missing cards, or the shopping list
    deck_id: int | None = None
    exclude_other_decks: bool = False
    include_proxied: bool = True


def _call(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except CardTraderError as exc:
        if exc.status == 401:
            raise HTTPException(status_code=400, detail=tr("cardtrader_bad_token")) from exc
        raise HTTPException(status_code=502, detail=tr("cardtrader_failed", error=exc.message)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=tr("cardtrader_offline", error=exc)) from exc


def _client(request: Request, value: str) -> CardTraderClient:
    return CardTraderClient(value, request.app.state.cardtrader)


@router.get("/cardtrader")
def get_status(db: Db) -> CardTraderStatus:
    """Whether a CardTrader token is set (the token itself is never sent back)."""
    return status(db)


@router.put("/cardtrader/token")
def put_token(db: Db, request: Request, body: TokenBody) -> CardTraderStatus:
    """Keep the user's CardTrader API token once CardTrader accepts it."""
    value = body.token.strip()
    return _call(lambda: save_token(db, _client(request, value), value))


@router.delete("/cardtrader/token", status_code=204)
def delete_token(db: Db) -> None:
    forget_token(db)


@router.post("/cardtrader/wishlists")
def post_wishlist(db: Db, request: Request, body: WishlistRequest) -> WishlistResult:
    """Send cards to buy to CardTrader as a private wishlist (any printing); the result lists the
    cards CardTrader didn't recognize."""
    value = token(db)
    if not value:
        raise HTTPException(status_code=400, detail=tr("cardtrader_no_token"))
    if body.source == "deck":
        if body.deck_id is None:
            raise HTTPException(status_code=422, detail="deck_id is required")
        try:
            deck, lines = deck_lines(db, body.deck_id, body.exclude_other_decks, body.include_proxied)
        except DeckNotFound as exc:
            raise HTTPException(status_code=404, detail="Deck not found") from exc
        name = tr("cardtrader_deck_wishlist", deck=deck)
    else:
        lines = wants_lines(db)
        name = tr("cardtrader_wants_wishlist", date=date.today().isoformat())
    try:
        return _call(lambda: send_wishlist(_client(request, value), name, lines))
    except NothingToSend as exc:
        raise HTTPException(status_code=400, detail=tr("cardtrader_nothing")) from exc
