from typing import Literal

from pydantic import BaseModel, Field

from mtgdm.cards.models import CardSummary

Finish = Literal["nonfoil", "foil", "etched"]
Condition = Literal["M", "NM", "EX", "GD", "LP", "PL", "PO"]
LocationKind = Literal["deck", "binder", "box", "other"]


class Location(BaseModel):
    id: int
    name: str
    kind: LocationKind
    card_count: int


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: LocationKind = "box"


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    kind: LocationKind | None = None


class CollectionItem(BaseModel):
    id: int
    card: CardSummary
    quantity: int
    finish: Finish
    language: str
    condition: Condition
    location: Location | None
    source: Literal["manual", "scan", "import"]
    note: str | None


class CollectionItemCreate(BaseModel):
    card_id: str
    quantity: int = Field(default=1, ge=1, le=999)
    finish: Finish | None = None      # default: nonfoil, or the card's only finish
    language: str | None = None       # default: the printing's language
    condition: Condition = "NM"
    location_id: int | None = None
    note: str | None = None


class CollectionItemUpdate(BaseModel):
    quantity: int | None = Field(default=None, ge=1, le=999)
    finish: Finish | None = None
    language: str | None = None
    condition: Condition | None = None
    location_id: int | None = None
    note: str | None = None


class CollectionStats(BaseModel):
    copies: int
    printings: int
    cards: int  # distinct oracle cards


class DeckToCollectionResult(BaseModel):
    location: Location
    added: int  # copies added
