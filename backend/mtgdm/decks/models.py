from typing import Literal

from pydantic import BaseModel, Field

from mtgdm.cards.models import CardSummary

DeckFormat = Literal["brawl", "standardbrawl", "commander", "historic", "standard", "pioneer", "freeform"]
Platform = Literal["paper", "arena"]
Board = Literal["main", "commander", "companion", "sideboard", "maybe"]


class DeckCard(BaseModel):
    card: CardSummary
    quantity: int
    board: Board
    category: str | None


class DeckCounts(BaseModel):
    main: int
    commander: int
    companion: int
    sideboard: int
    maybe: int
    total: int  # cards that count toward deck size: main + commander


class DeckSummary(BaseModel):
    id: int
    name: str
    format: DeckFormat
    platform: Platform
    description: str | None
    commander_card_id: str | None
    partner_card_id: str | None
    companion_card_id: str | None
    commander_name: str | None
    # Card shown on the deck tile: the commander, else the companion, else a card of the main deck.
    cover_card_id: str | None
    # The commanders' identity; without a commander, the colours of the main deck's cards.
    color_identity: list[str]
    location_id: int | None    # deck box in the collection ("I own this deck")
    counts: DeckCounts
    unsaved_changes: int  # cards changed since the latest saved version
    created_at: str
    updated_at: str


class DeckChange(BaseModel):
    """One card name on one board that differs between two states of a deck."""

    name: str
    board: Board
    card: CardSummary | None  # the current printing (the old one when removed)
    before: int
    after: int
    printing_changed: bool


class DeckChanges(BaseModel):
    base_id: int | None  # version compared with; None = no saved version yet
    base_number: int | None
    base_created_at: str | None
    format_before: DeckFormat | None  # set only when changed
    platform_before: Platform | None
    cards: list[DeckChange]


class DeckDetail(DeckSummary):
    cards: list[DeckCard]
    changes: DeckChanges


class DeckVersion(BaseModel):
    id: int
    number: int
    note: str | None
    format: DeckFormat
    platform: Platform
    created_at: str
    total: int     # main + commander
    added: int     # copies added since the previous version
    removed: int


class DeckVersionDetail(DeckVersion):
    cards: list[DeckCard]
    changes: list[DeckChange]  # since the previous version, or to the working copy (compare=current)


class DeckVersionCreate(BaseModel):
    note: str | None = Field(default=None, max_length=200)


class DeckCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    format: DeckFormat = "freeform"
    platform: Platform = "paper"
    description: str | None = None


class DeckUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    format: DeckFormat | None = None
    platform: Platform | None = None
    description: str | None = None


class DeckCardAdd(BaseModel):
    card_id: str
    quantity: int = Field(default=1, ge=1, le=250)
    board: Board = "main"


class DeckCardUpdate(BaseModel):
    """Change one deck entry: move between boards, set quantity, or swap the printing."""

    board: Board = "main"  # entry to change
    new_board: Board | None = None
    quantity: int | None = Field(default=None, ge=1, le=250)
    new_card_id: str | None = None
    category: str | None = Field(default=None, max_length=40)  # "" clears the category


class DeckCardEntry(BaseModel):
    card_id: str
    quantity: int = Field(default=1, ge=1, le=250)
    board: Board = "main"
    category: str | None = None


# --- import / export -------------------------------------------------------

ImportStatus = Literal["matched", "warning", "not_found"]


class ImportMeta(BaseModel):
    name: str | None
    format: DeckFormat | None
    platform: Platform | None
    preferred_sets: list[str]
    description: str | None


class ImportLine(BaseModel):
    line_no: int
    text: str
    quantity: int
    name: str
    board: Board
    set_code: str | None
    collector_number: str | None
    foil: bool
    note: str | None  # trailing "# ..." comment on the line
    status: ImportStatus
    card: CardSummary | None
    warnings: list[str]
    suggestions: list[str]


class ImportLineError(BaseModel):
    line_no: int
    text: str
    message: str


class ImportCounts(BaseModel):
    matched: int
    warning: int
    not_found: int
    cards: int  # total quantity of resolved cards


class ImportReport(BaseModel):
    meta: ImportMeta
    lines: list[ImportLine]
    errors: list[ImportLineError]
    counts: ImportCounts


class ImportParseRequest(BaseModel):
    text: str = Field(max_length=200_000)
    # Override the '# platform:' / '# preferred-sets:' metadata (e.g. chosen in the UI).
    platform: Platform | None = None
    preferred_sets: list[str] | None = None


class ImportCommitRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    format: DeckFormat = "freeform"
    platform: Platform = "paper"
    description: str | None = None
    preferred_sets: list[str] = []
    entries: list[DeckCardEntry]


class ExportResult(BaseModel):
    target: Literal["arena", "text"]
    text: str
    warnings: list[str]
    unavailable: list[str]  # cards left out because no printing exists on the target


class SeedInfo(BaseModel):
    file: str
    name: str
    text: str
