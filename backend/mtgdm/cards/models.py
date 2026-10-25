from typing import Literal

from pydantic import BaseModel

ColorMode = Literal["include", "exact", "identity"]
Order = Literal["name", "mv", "released"]
Unique = Literal["cards", "prints"]
Owned = Literal["owned", "missing", "free"]  # free = owned outside other decks' boxes


class CardSummary(BaseModel):
    """What the card grid needs: one printing with enough data to render and filter."""

    id: str
    oracle_id: str | None
    name: str
    printed_name: str | None
    lang: str
    layout: str | None
    mana_cost: str | None
    cmc: float | None
    type_line: str | None
    rarity: str | None
    set_code: str
    set_name: str
    collector_number: str | None
    released_at: str | None
    colors: list[str]
    color_identity: list[str]
    games: list[str]
    artist: str | None
    # 0 = no image, 1 = single image, 2+ = one image per face (transform / MDFC).
    image_faces: int
    owned: int           # copies in the collection, any printing of this card
    owned_printing: int  # copies of exactly this printing


class CardFace(BaseModel):
    name: str
    mana_cost: str | None = None
    type_line: str | None = None
    oracle_text: str | None = None
    power: str | None = None
    toughness: str | None = None
    loyalty: str | None = None
    artist: str | None = None
    flavor_text: str | None = None


class CardDetail(CardSummary):
    oracle_text: str | None
    power: str | None
    toughness: str | None
    loyalty: str | None
    flavor_text: str | None
    keywords: list[str]
    legalities: dict[str, str]
    finishes: list[str]
    produced_mana: list[str]
    prices: dict[str, str | None]
    prices_updated_at: str | None
    arena_id: int | None
    digital: bool
    promo: bool
    faces: list[CardFace]
    printings_count: int
    user_tags: list[str] = []  # the user's own tags on the card


class CardPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[CardSummary]
    # The query with its words that are card types as type filters ("desert" -> "t:desert"); first
    # page only. Words without a key search names, as on Scryfall: surprising when a type was meant.
    type_hint: str | None = None


class SetInfo(BaseModel):
    code: str
    name: str
    set_type: str | None
    released_at: str | None
    digital: bool
    arena_code: str | None
    card_count: int
    has_icon: bool
