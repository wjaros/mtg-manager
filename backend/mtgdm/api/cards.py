from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from mtgdm.api.deps import AppSettings, Db
from mtgdm.cards.models import (
    CardDetail,
    CardPage,
    CardSummary,
    ColorMode,
    Order,
    Owned,
    SetInfo,
    Unique,
)
from mtgdm.cards.search import (
    CardQuery,
    InvalidQuery,
    get_card,
    get_printings,
    list_sets,
    search_cards,
)
from mtgdm.cards.similar import DeckNotFound, SimilarCards, similar_cards
from mtgdm.cards.user_tags import UserTag, all_tags, set_tags
from mtgdm.collection.usage import CardUsage, card_usage

router = APIRouter(tags=["cards"])


@router.get("/cards")
def cards(
    db: Db,
    q: Annotated[str | None, Query(description="Words in the card name (prefix match)")] = None,
    text: Annotated[str | None, Query(description="Words in the type line or rules text")] = None,
    colors: Annotated[str | None, Query(pattern="^[WUBRGCwubrgc]*$", description="e.g. WU; C = colorless")] = None,
    color_mode: ColorMode = "include",
    identity: Annotated[
        str | None, Query(pattern="^[WUBRGCwubrgc]*$", description="Color identity within these colors (deckbuilding)")
    ] = None,
    mv: Annotated[list[int], Query(description="Mana values; 7 means 7+")] = [],
    type: Annotated[list[str], Query(description="Type line must contain each value")] = [],
    tag: Annotated[list[str], Query(description="Scryfall function tags (ramp, draw, removal, ...), each required")] = [],
    user_tag: Annotated[list[str], Query(description="The user's own tags, each required")] = [],
    rarity: Annotated[list[str], Query()] = [],
    set: Annotated[list[str], Query(description="Scryfall set codes")] = [],
    format: Annotated[str | None, Query(description="Only cards legal in this format")] = None,
    game: Literal["paper", "arena", "mtgo"] | None = None,
    owned: Annotated[
        Owned | None, Query(description="owned / missing from the physical collection; free = not in other decks' boxes")
    ] = None,
    deck: Annotated[int | None, Query(description="Deck being built (its own box counts as free)")] = None,
    not_in_deck: Annotated[int | None, Query(description="Hide cards already in this deck, except basic lands")] = None,
    include_extras: Annotated[bool, Query(description="Include tokens, emblems, art cards, ...")] = False,
    include_proxies: Annotated[bool, Query(description="The owned filter counts proxies as copies")] = False,
    unique: Unique = "cards",
    order: Order = "name",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 60,
) -> CardPage:
    query = CardQuery(
        q=q, text=text, colors=colors, color_mode=color_mode, identity=identity, mv=mv, types=type, rarity=rarity,
        sets=set, format=format, game=game, owned=owned, deck=deck, not_in_deck=not_in_deck, include_extras=include_extras,
        include_proxies=include_proxies, tags=tag, user_tags=user_tag, unique=unique,
        order=order, page=page, page_size=page_size,
    )
    try:
        return search_cards(db, query)
    except InvalidQuery as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/cards/{card_id}")
def card(db: Db, card_id: str) -> CardDetail:
    result = get_card(db, card_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return result


@router.get("/cards/{card_id}/usage")
def usage(
    db: Db, card_id: str, deck: Annotated[int | None, Query(description="Deck being built")] = None
) -> CardUsage:
    """Where the card is: copies per location (deck boxes included) and decks whose list contains it."""
    result = card_usage(db, card_id, deck)
    if result is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return result


@router.get("/cards/{card_id}/printings")
def printings(db: Db, card_id: str) -> list[CardSummary]:
    result = get_printings(db, card_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return result


@router.get("/cards/{card_id}/similar")
def similar(
    db: Db,
    card_id: str,
    colors: Annotated[
        str | None,
        Query(pattern="^[WUBRGCwubrgc]*$", description="Color identity to search in (C: colorless); default: the card's"),
    ] = None,
    deck: Annotated[int | None, Query(description="Deck being built: only its format's cards, not those in it")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 60,
) -> SimilarCards:
    """Cards doing a similar job (alike rules text, shared Scryfall Tagger tags, close mana value): the best
    ones in the collection and the best others."""
    try:
        chosen = None if colors is None else [c for c in colors.upper() if c != "C"]
        result = similar_cards(db, card_id, chosen, deck, limit)
    except DeckNotFound as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return result


class UserTagsUpdate(BaseModel):
    tags: list[str]


@router.put("/cards/{card_id}/user-tags")
def update_user_tags(db: Db, card_id: str, body: UserTagsUpdate) -> list[str]:
    """Replace the user's own tags on a card (every printing of it); returns them as stored."""
    result = set_tags(db, card_id, body.tags)
    if result is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return result


@router.get("/user-tags")
def user_tags(db: Db) -> list[UserTag]:
    """The user's own tags in use, with their numbers of cards."""
    return all_tags(db)


@router.get("/sets")
def sets(db: Db) -> list[SetInfo]:
    return list_sets(db)


@router.get("/sets/{code}/icon", response_class=FileResponse)
def set_icon(db: Db, settings: AppSettings, code: str) -> FileResponse:
    row = db.execute("SELECT icon_path FROM sets WHERE code = ?", (code.lower(),)).fetchone()
    if row is None or row["icon_path"] is None:
        raise HTTPException(status_code=404, detail="Icon not found")
    path = settings.images_dir / row["icon_path"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Icon not found")
    return FileResponse(path, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=604800"})
