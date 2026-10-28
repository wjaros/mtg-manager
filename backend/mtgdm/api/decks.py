from collections.abc import Callable
from typing import Annotated, Literal, TypeVar
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response

from mtgdm.api.deps import Db
from mtgdm.decks import service, versions
from mtgdm.decks.compare import DeckComparison, compare_decks
from mtgdm.decks.export import export_deck
from mtgdm.decks.models import (
    Board,
    DeckCardAdd,
    DeckCardEntry,
    DeckCardUpdate,
    DeckCreate,
    DeckDetail,
    DeckSummary,
    DeckUpdate,
    DeckVersion,
    DeckVersionCreate,
    DeckVersionDetail,
    ExportResult,
)
from mtgdm.decks.pdf import deck_pages, render_pdf
from mtgdm.decks.service import CardNotFound, DeckNotFound
from mtgdm.decks.stats import DeckStats, deck_stats
from mtgdm.decks.validation import ValidationResult, validate_deck
from mtgdm.decks.versions import NoChanges, VersionNotFound
from mtgdm.i18n import tr
from mtgdm.spellbook.client import SpellbookError
from mtgdm.spellbook.combos import DeckCombos, deck_combos

router = APIRouter(prefix="/decks", tags=["decks"])

T = TypeVar("T")


def _handle(fn: Callable[[], T]) -> T:
    try:
        return fn()
    except DeckNotFound as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc
    except CardNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Card not found: {exc}") from exc
    except VersionNotFound as exc:
        raise HTTPException(status_code=404, detail="Version not found") from exc
    except NoChanges as exc:
        raise HTTPException(status_code=409, detail=tr("no_changes")) from exc


@router.get("")
def list_decks(db: Db) -> list[DeckSummary]:
    return service.list_decks(db)


@router.post("", status_code=201)
def create_deck(db: Db, body: DeckCreate) -> DeckDetail:
    return service.create_deck(db, body)


@router.get("/{deck_id}")
def get_deck(db: Db, deck_id: int) -> DeckDetail:
    return _handle(lambda: service.get_deck(db, deck_id))


@router.patch("/{deck_id}")
def update_deck(db: Db, deck_id: int, body: DeckUpdate) -> DeckDetail:
    return _handle(lambda: service.update_deck(db, deck_id, body))


@router.delete("/{deck_id}", status_code=204)
def delete_deck(db: Db, deck_id: int, with_cards: bool = False) -> Response:
    """with_cards: also remove the copies in the deck's box from the collection."""
    _handle(lambda: service.delete_deck(db, deck_id, with_cards))
    return Response(status_code=204)


@router.put("/{deck_id}/cards")
def replace_cards(db: Db, deck_id: int, body: list[DeckCardEntry]) -> DeckDetail:
    return _handle(lambda: service.replace_cards(db, deck_id, body))


@router.post("/{deck_id}/cards")
def add_card(db: Db, deck_id: int, body: DeckCardAdd) -> DeckDetail:
    return _handle(lambda: service.add_card(db, deck_id, body.card_id, body.quantity, body.board))


@router.patch("/{deck_id}/cards/{card_id}")
def update_card(db: Db, deck_id: int, card_id: str, body: DeckCardUpdate) -> DeckDetail:
    return _handle(lambda: service.update_card(
        db, deck_id, card_id, body.board,
        new_board=body.new_board, quantity=body.quantity, new_card_id=body.new_card_id, category=body.category,
    ))


@router.delete("/{deck_id}/cards/{card_id}")
def remove_card(
    db: Db,
    deck_id: int,
    card_id: str,
    board: Board = "main",
    quantity: Annotated[int | None, Query(ge=1, description="Copies to remove; all when omitted")] = None,
) -> DeckDetail:
    return _handle(lambda: service.remove_card(db, deck_id, card_id, board, quantity))


@router.get("/{deck_id}/versions")
def list_versions(db: Db, deck_id: int) -> list[DeckVersion]:
    """Saved versions, newest first."""
    _handle(lambda: service.get_deck(db, deck_id))
    return versions.list_versions(db, deck_id)


@router.post("/{deck_id}/versions", status_code=201)
def save_version(db: Db, deck_id: int, body: DeckVersionCreate) -> DeckVersion:
    """Snapshot the current deck; 409 when nothing changed since the latest version."""
    _handle(lambda: service.get_deck(db, deck_id))
    return _handle(lambda: versions.save(db, deck_id, body.note))


@router.get("/{deck_id}/versions/{version_id}")
def get_version(
    db: Db, deck_id: int, version_id: int, compare: Literal["previous", "current"] = "previous"
) -> DeckVersionDetail:
    return _handle(lambda: versions.get_version(db, deck_id, version_id, compare))


@router.post("/{deck_id}/versions/{version_id}/restore")
def restore_version(db: Db, deck_id: int, version_id: int) -> DeckDetail:
    """Replace the deck's cards with a saved version (shows as unsaved changes until saved)."""
    return _handle(lambda: service.restore_version(db, deck_id, version_id))


@router.get("/{deck_id}/export")
def export(db: Db, deck_id: int, target: Literal["arena", "text"] = "arena") -> ExportResult:
    """Decklist text; for Arena, printings missing on Arena are swapped or reported as unavailable."""
    return _handle(lambda: export_deck(db, deck_id, target))


@router.get("/{deck_id}/export/pdf", response_class=Response)
def export_pdf(db: Db, request: Request, deck_id: int) -> Response:
    """One card per page for a phone: commanders, then by mana value, lands last."""
    pages = _handle(lambda: deck_pages(db, deck_id))
    cache = request.app.state.image_cache

    def image(card_id: str, face: int):
        try:
            return cache.get(db, card_id, "large", face)
        except Exception:  # offline or no image: a text page
            return None

    name = db.execute("SELECT name FROM decks WHERE id = ?", (deck_id,)).fetchone()["name"]
    # Headers are latin-1: an ASCII name plus the real one in RFC 5987 form.
    ascii_name = "".join(ch if ch.isascii() and (ch.isalnum() or ch in " -_") else "_" for ch in name).strip()
    disposition = f'attachment; filename="{ascii_name or "deck"}.pdf"; filename*=UTF-8\'\'{quote(name)}.pdf'
    return Response(render_pdf(pages, image), media_type="application/pdf", headers={"Content-Disposition": disposition})


@router.get("/{deck_id}/validate")
def validate(db: Db, deck_id: int) -> ValidationResult:
    """Format rules (errors) and advice (warnings) for the deck."""
    return _handle(lambda: validate_deck(db, deck_id))


@router.get("/{deck_id}/compare/{other_id}")
def compare(db: Db, deck_id: int, other_id: int) -> DeckComparison:
    """Two decks card by card (by name): copies in each, price, and what could go from one into the other."""
    try:
        return compare_decks(db, deck_id, other_id)
    except DeckNotFound as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc


@router.get("/{deck_id}/stats")
def stats(db: Db, deck_id: int) -> DeckStats:
    return _handle(lambda: deck_stats(db, deck_id))


@router.get("/{deck_id}/combos")
def combos(db: Db, request: Request, deck_id: int) -> DeckCombos:
    """Combos in the deck and one card away, from Commander Spellbook."""
    try:
        return _handle(lambda: deck_combos(db, request.app.state.spellbook, deck_id))
    except SpellbookError as exc:
        raise HTTPException(status_code=502, detail=tr("combos_failed", error=exc)) from exc
