from typing import Literal

from pydantic import BaseModel, Field

from mtgdm.cards.models import CardSummary

Finish = Literal["nonfoil", "foil", "etched"]
Condition = Literal["M", "NM", "EX", "GD", "LP", "PL", "PO"]
LocationKind = Literal["deck", "binder", "box", "other"]
# A real copy is owned; a proxy (printed stand-in) sits in a deck's box instead of a card you don't
# have there, and never counts as owned.
ItemKind = Literal["real", "proxy"]


class Location(BaseModel):
    id: int
    name: str
    kind: LocationKind
    card_count: int   # real copies
    proxy_count: int = 0


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
    kind: ItemKind = "real"
    printed_at: str | None = None   # proxies: when printed
    print_job_id: int | None = None  # proxies: the print they came from


class CollectionItemCreate(BaseModel):
    card_id: str
    quantity: int = Field(default=1, ge=1, le=999)
    finish: Finish | None = None      # default: nonfoil, or the card's only finish
    language: str | None = None       # default: the printing's language
    condition: Condition = "NM"
    location_id: int | None = None
    note: str | None = None
    kind: ItemKind = "real"  # proxies ignore finish, language and condition


class CollectionItemUpdate(BaseModel):
    quantity: int | None = Field(default=None, ge=1, le=999)
    finish: Finish | None = None
    language: str | None = None
    condition: Condition | None = None
    location_id: int | None = None
    note: str | None = None


class CollectionStats(BaseModel):
    copies: int    # real copies
    printings: int
    cards: int     # distinct oracle cards
    proxies: int = 0


class ReplaceWithReal(BaseModel):
    """A proxy you now have the real card for. Either a new copy (printing, finish, condition,
    language) goes into the proxy's place, or an existing real copy without a location is moved there."""

    card_id: str | None = None   # the printing bought; default: the proxy's printing
    finish: Finish | None = None
    condition: Condition = "NM"
    language: str | None = None
    use_existing_item_id: int | None = None


class DeckToCollectionResult(BaseModel):
    location: Location
    added: int  # copies added
