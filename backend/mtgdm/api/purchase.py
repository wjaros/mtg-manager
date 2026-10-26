import threading
from collections.abc import Callable
from typing import TypeVar

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from mtgdm.api.cardtrader import _call, _client
from mtgdm.api.deps import AppSettings, Db
from mtgdm.cardtrader.client import CardTraderError
from mtgdm.cardtrader.offers import CartResult, QuoteJob, fetch_quotes, send_to_cart
from mtgdm.cardtrader.wishlists import token
from mtgdm.db import connect
from mtgdm.decks.service import DeckNotFound
from mtgdm.i18n import current_lang, set_lang, tr
from mtgdm.purchase import opener
from mtgdm.purchase.basket import Basket, BasketProposal, Comparison, basket, comparison, propose
from mtgdm.purchase.settings import PurchaseSettings, get_settings, save_settings
from mtgdm.purchase.shopping import (
    InvalidOfferUrl,
    Offer,
    OfferNotFound,
    ShoppingList,
    add_offer,
    apply_choices,
    delete_offer,
    pick_cheapest,
    reset_done,
    set_done,
    shopping_list,
    update_offer,
)
from mtgdm.purchase.sources import (
    SAMPLE_CARD,
    InvalidTemplate,
    PurchaseLink,
    PurchaseSource,
    QueryMode,
    SourceNotFound,
    card_links,
    create_source,
    delete_source,
    get_source,
    list_sources,
    source_url,
    update_source,
)

router = APIRouter(tags=["purchase"])

T = TypeVar("T")
MAX_OPEN = 100


def _handle(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except InvalidTemplate as exc:
        raise HTTPException(status_code=422, detail=tr(exc.key)) from exc
    except SourceNotFound as exc:
        raise HTTPException(status_code=404, detail=tr("purchase_source_not_found")) from exc
    except OfferNotFound as exc:
        raise HTTPException(status_code=404, detail=tr("offer_not_found")) from exc
    except InvalidOfferUrl as exc:
        raise HTTPException(status_code=422, detail=tr("offer_bad_url")) from exc
    except DeckNotFound as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc
    except ValueError as exc:
        if str(exc) == "seller_name":
            raise HTTPException(status_code=422, detail=tr("offer_no_seller")) from exc
        raise


# --- settings and sources ------------------------------------------------------------------


@router.get("/purchase-settings")
def get_purchase_settings(db: Db) -> PurchaseSettings:
    return get_settings(db)


@router.put("/purchase-settings")
def put_purchase_settings(db: Db, body: PurchaseSettings) -> PurchaseSettings:
    """Free-delivery threshold, currency, shipping and exchange rates (typed in by hand)."""
    return save_settings(db, body)


class SourceBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url_template: str = Field(min_length=1, max_length=2000)
    enabled: bool = True
    sort_order: int | None = None
    query_mode: QueryMode = "name"
    query_suffix: str = Field(default="", max_length=100)
    note: str | None = Field(default=None, max_length=1000)
    free_delivery_threshold: float | None = Field(default=None, ge=0)
    shipping_cost: float | None = Field(default=None, ge=0)


class SourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url_template: str | None = Field(default=None, min_length=1, max_length=2000)
    enabled: bool | None = None
    sort_order: int | None = None
    query_mode: QueryMode | None = None
    query_suffix: str | None = Field(default=None, max_length=100)
    note: str | None = Field(default=None, max_length=1000)
    free_delivery_threshold: float | None = Field(default=None, ge=0)
    shipping_cost: float | None = Field(default=None, ge=0)


class TestUrl(BaseModel):
    url: str


@router.get("/purchase-sources")
def get_sources(db: Db) -> list[PurchaseSource]:
    return list_sources(db)


@router.post("/purchase-sources")
def post_source(db: Db, body: SourceBody) -> PurchaseSource:
    return _handle(lambda: create_source(db, body.model_dump(exclude_none=True)))


@router.patch("/purchase-sources/{source_id}")
def patch_source(db: Db, source_id: int, body: SourcePatch) -> PurchaseSource:
    """Fields left out stay; the nullable ones (note, threshold, shipping) are cleared with null."""
    values = body.model_dump(exclude_unset=True)
    nullable = {"note", "free_delivery_threshold", "shipping_cost"}
    values = {k: v for k, v in values.items() if v is not None or k in nullable}
    return _handle(lambda: update_source(db, source_id, values))


@router.delete("/purchase-sources/{source_id}", status_code=204)
def remove_source(db: Db, source_id: int) -> None:
    _handle(lambda: delete_source(db, source_id))


@router.get("/purchase-sources/{source_id}/test")
def test_source(db: Db, source_id: int, card: str = SAMPLE_CARD) -> TestUrl:
    """The source's search for a sample card, to open and check."""
    return _handle(lambda: TestUrl(url=source_url(get_source(db, source_id), card)))


@router.get("/cards/{card_id}/purchase-links")
def get_card_links(db: Db, card_id: str) -> list[PurchaseLink]:
    """Searches for the card at every enabled source."""
    found = card_links(db, card_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return found


class OpenUrls(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=MAX_OPEN)


@router.post("/open-urls", status_code=204)
def post_open_urls(body: OpenUrls) -> None:
    """The window app: open the links in the system browser, one tab each. Not in a browser (404)."""
    if not opener.enabled():
        raise HTTPException(status_code=404, detail=tr("open_urls_app_only"))
    if any(not u.startswith(("https://", "http://")) for u in body.urls):
        raise HTTPException(status_code=422, detail="Only http(s) links can be opened")
    opener.open_urls(body.urls)


# --- a deck's shopping list --------------------------------------------------------------------


class DoneBody(BaseModel):
    done: bool


@router.get("/decks/{deck_id}/shopping-list")
def get_shopping_list(db: Db, deck_id: int) -> ShoppingList:
    """The cards the deck lacks (proxied ones too: still to buy) with search links, done ticks and offers."""
    return _handle(lambda: shopping_list(db, deck_id))


@router.patch("/decks/{deck_id}/shopping-list/{oracle_id}")
def patch_shopping_row(db: Db, deck_id: int, oracle_id: str, body: DoneBody) -> ShoppingList:
    _handle(lambda: set_done(db, deck_id, oracle_id, body.done))
    return shopping_list(db, deck_id)


@router.delete("/decks/{deck_id}/shopping-list/done")
def delete_done(db: Db, deck_id: int) -> ShoppingList:
    """Untick every card (start the list over)."""
    _handle(lambda: reset_done(db, deck_id))
    return shopping_list(db, deck_id)


class OfferBody(BaseModel):
    oracle_id: str = Field(min_length=1)
    price: float = Field(ge=0, le=1_000_000)
    seller_name: str | None = Field(default=None, max_length=100)
    source_id: int | None = None
    qty_available: int | None = Field(default=None, ge=0)
    url: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=1000)
    chosen: bool = False


class OfferPatch(BaseModel):
    price: float | None = Field(default=None, ge=0, le=1_000_000)
    seller_name: str | None = Field(default=None, max_length=100)
    source_id: int | None = None
    qty_available: int | None = Field(default=None, ge=0)
    url: str | None = Field(default=None, max_length=2000)
    note: str | None = Field(default=None, max_length=1000)


class ChoicesBody(BaseModel):
    choices: dict[str, int | None]  # oracle id -> offer id; None: none chosen


@router.post("/decks/{deck_id}/offers")
def post_offer(db: Db, deck_id: int, body: OfferBody) -> Offer:
    """Note an offer seen at a seller (price per copy, in the settings' currency)."""
    values = body.model_dump(exclude={"oracle_id", "chosen"})
    offer = _handle(lambda: add_offer(db, deck_id, body.oracle_id, **values))
    if body.chosen:
        apply_choices(db, deck_id, {body.oracle_id: offer.id})
    return offer.model_copy(update={"chosen": body.chosen})


@router.patch("/offers/{offer_id}")
def patch_offer(db: Db, offer_id: int, body: OfferPatch) -> Offer:
    values = body.model_dump(exclude_unset=True)
    if values.get("price") is None:
        values.pop("price", None)
    return _handle(lambda: update_offer(db, offer_id, values))


@router.delete("/offers/{offer_id}", status_code=204)
def remove_offer(db: Db, offer_id: int) -> None:
    _handle(lambda: delete_offer(db, offer_id))


@router.put("/decks/{deck_id}/choices")
def put_choices(db: Db, deck_id: int, body: ChoicesBody) -> Basket:
    """Choose offers (an accepted proposal, or one card moved to another seller)."""
    _handle(lambda: apply_choices(db, deck_id, body.choices))
    return basket(db, deck_id)


@router.post("/decks/{deck_id}/choices/cheapest")
def post_cheapest(db: Db, deck_id: int, oracle_id: str | None = None) -> Basket:
    """Choose the cheapest offer for one card, or for every card without changing as cheap choices."""
    _handle(lambda: pick_cheapest(db, deck_id, oracle_id))
    return basket(db, deck_id)


@router.get("/decks/{deck_id}/basket")
def get_basket(db: Db, deck_id: int) -> Basket:
    """Chosen offers per seller with progress to free delivery and suggestions to reach it."""
    return _handle(lambda: basket(db, deck_id))


@router.get("/decks/{deck_id}/basket/proposal")
def get_proposal(db: Db, deck_id: int) -> BasketProposal:
    """A basket minimising cards + shipping, for the user to accept (PUT choices) or discard."""
    return _handle(lambda: propose(db, deck_id))


@router.get("/decks/{deck_id}/basket/compare")
def get_comparison(db: Db, deck_id: int) -> Comparison:
    """The sellers' basket next to CardTrader Zero (offers fetched before) and a mix of both."""
    return _handle(lambda: comparison(db, deck_id))


# --- CardTrader Zero offers ----------------------------------------------------------------------


def _token(db) -> str:
    value = token(db)
    if not value:
        raise HTTPException(status_code=400, detail=tr("cardtrader_no_token"))
    return value


@router.get("/decks/{deck_id}/cardtrader/quotes")
def get_quote_job(request: Request, deck_id: int) -> QuoteJob:
    jobs: dict[int, QuoteJob] = request.app.state.quote_jobs
    return jobs.get(deck_id) or QuoteJob(deck_id=deck_id, running=False)


@router.post("/decks/{deck_id}/cardtrader/quotes")
def post_quote_job(db: Db, settings: AppSettings, request: Request, deck_id: int) -> QuoteJob:
    """Fetch the cheapest CardTrader Zero offers of the cards still to buy, in the background."""
    _handle(lambda: shopping_list(db, deck_id))
    value = _token(db)
    jobs: dict[int, QuoteJob] = request.app.state.quote_jobs
    if deck_id in jobs and jobs[deck_id].running:
        raise HTTPException(status_code=409, detail=tr("cardtrader_quotes_running"))
    job = jobs[deck_id] = QuoteJob(deck_id=deck_id, running=True)
    client = _client(request, value)
    lang = current_lang()

    def run() -> None:
        set_lang(lang)
        conn = connect(settings.db_path)
        try:
            job.result = fetch_quotes(conn, client, deck_id, lambda done, total: _progress(job, done, total))
        except CardTraderError as exc:
            job.error = tr("cardtrader_bad_token") if exc.status == 401 else tr("cardtrader_failed", error=exc.message)
        except httpx.HTTPError as exc:
            job.error = tr("cardtrader_offline", error=exc)
        except Exception as exc:  # reported in the UI, not lost in a thread
            job.error = str(exc)
        finally:
            conn.close()
            job.running = False

    threading.Thread(target=run, daemon=True).start()
    return job


def _progress(job: QuoteJob, done: int, total: int) -> None:
    job.done, job.total = done, total


class CartBody(BaseModel):
    oracle_ids: list[str] = Field(min_length=1)


@router.post("/decks/{deck_id}/cardtrader/cart")
def post_cart(db: Db, request: Request, deck_id: int, body: CartBody) -> CartResult:
    """Put these cards' CardTrader Zero offers into the user's CardTrader cart (never bought from here)."""
    value = _token(db)
    _handle(lambda: shopping_list(db, deck_id))
    return _call(lambda: send_to_cart(db, _client(request, value), deck_id, body.oracle_ids))
