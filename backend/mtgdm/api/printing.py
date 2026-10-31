import io
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from mtgdm.api.deps import Db
from mtgdm.collection.models import CollectionItem, CollectionItemCreate
from mtgdm.collection.service import LocationNotFound, add_item, deck_box
from mtgdm.decks.service import CardNotFound, DeckNotFound
from mtgdm.i18n import current_lang, tr
from mtgdm.printing import history, profiles
from mtgdm.printing.candidates import ProxyCandidate, card_faces, proxy_candidates
from mtgdm.printing.history import MarkRequest, MarkResult, PrintHistory
from mtgdm.printing.jobs import PrintJob, PrintJobs, PrintRequest
from mtgdm.printing.layout import PageLayout
from mtgdm.printing.profiles import (
    BackOffset,
    CalibrationResult,
    Measurements,
    Paper,
    PrinterProfile,
    PrintSettings,
    ProfileCreate,
    ProfileNotFound,
    ProfileUpdate,
)
from mtgdm.printing.render import Slot, render_calibration, render_duplex_test
from mtgdm.printing.tokens import DeckToken, card_tokens, deck_tokens

router = APIRouter(tags=["printing"])


class ProxyItem(BaseModel):
    card_id: str
    qty: int = Field(ge=1, le=99)
    faces: Literal["both", "front"] = "both"


class ProxyPrint(BaseModel):
    items: list[ProxyItem]
    profile_id: int | None = None
    paper: Paper = "a4"
    gap_mm: float = Field(default=0.0, ge=0, le=3)
    cut_marks: bool = True
    # Two-sided: fronts, then backs mirrored for a sheet turned over its long or short edge.
    duplex: Literal["off", "long", "short"] = "off"
    # "text": the card's rules text, mana cost and price in a frame instead of the Scryfall image.
    style: Literal["image", "text"] = "image"
    title: str = Field(default="", max_length=200)  # deck name: in the footer and the file name
    deck_id: int | None = None  # printed from this deck: its cards can then be marked as proxies in its box


class PrintJobStatus(BaseModel):
    id: str
    stage: Literal["images", "render", "done", "error"]
    done: int
    total: int
    pages: int
    missing_images: list[str]
    error: str | None
    overflow: bool = False  # the compensated grid leaves the printable area
    print_job_id: int | None = None  # the recorded print (history): mark its cards as proxies, print again


def _profile_or_404(db, profile_id: int) -> PrinterProfile:
    try:
        return profiles.get_profile(db, profile_id)
    except ProfileNotFound as exc:
        raise HTTPException(status_code=404, detail=tr("print_profile_not_found")) from exc


def _profile_label(profile: PrinterProfile | None) -> str | None:
    if profile is None or profile.calibrated_at is None:
        return None
    return tr("print_profile", name=profile.name, x=profile.scale_x, y=profile.scale_y)


def _disposition(name: str) -> str:
    # Headers are latin-1: an ASCII name plus the real one in RFC 5987 form.
    ascii_name = "".join(ch if ch.isascii() and (ch.isalnum() or ch in " -_") else "_" for ch in name).strip()
    return f'attachment; filename="{ascii_name or "proxies"}.pdf"; filename*=UTF-8\'\'{quote(name)}.pdf'


@router.get("/decks/{deck_id}/proxy-candidates")
def candidates(db: Db, deck_id: int, include_basics: bool = False, include_proxied: bool = False) -> list[ProxyCandidate]:
    """Cards of the deck you can't put in its box: not owned, or only in other decks' boxes."""
    try:
        return proxy_candidates(db, deck_id, include_basics, include_proxied)
    except DeckNotFound as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc


@router.get("/decks/{deck_id}/tokens")
def tokens(db: Db, deck_id: int) -> list[DeckToken]:
    """Tokens and emblems the deck's cards make (Scryfall's related parts)."""
    if db.execute("SELECT 1 FROM decks WHERE id = ?", (deck_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Deck not found")
    return deck_tokens(db, deck_id)


@router.get("/print/tokens")
def print_tokens(
    db: Db, card: Annotated[list[str], Query(description="Card printing ids")] = []
) -> list[DeckToken]:
    """Tokens and emblems these cards make: suggestions for cards added to a print list by hand."""
    return card_tokens(db, list(dict.fromkeys(card)))


@router.get("/print/settings")
def get_print_settings(db: Db) -> PrintSettings:
    return profiles.get_settings(db)


@router.put("/print/settings")
def put_print_settings(db: Db, body: PrintSettings) -> PrintSettings:
    return profiles.save_settings(db, body)


@router.get("/print/profiles")
def list_profiles(db: Db) -> list[PrinterProfile]:
    return profiles.list_profiles(db)


@router.post("/print/profiles", status_code=201)
def create_profile(db: Db, body: ProfileCreate) -> PrinterProfile:
    return profiles.create_profile(db, body)


@router.patch("/print/profiles/{profile_id}")
def update_profile(db: Db, profile_id: int, body: ProfileUpdate) -> PrinterProfile:
    _profile_or_404(db, profile_id)
    return profiles.update_profile(db, profile_id, body)


@router.delete("/print/profiles/{profile_id}", status_code=204)
def delete_profile(db: Db, profile_id: int) -> Response:
    _profile_or_404(db, profile_id)
    profiles.delete_profile(db, profile_id)
    return Response(status_code=204)


@router.post("/print/profiles/{profile_id}/calibrate")
def calibrate(db: Db, profile_id: int, body: Measurements) -> CalibrationResult:
    _profile_or_404(db, profile_id)
    return profiles.calibrate_profile(db, profile_id, body)


@router.get("/print/calibration.pdf", response_class=Response)
def calibration_pdf(
    db: Db,
    paper: Paper = "a4",
    profile_id: Annotated[int | None, Query(description="given: the verification page of that profile")] = None,
) -> Response:
    """The calibration page (scale 1.0), or with a profile the verification page (its correction applied)."""
    settings = profiles.get_settings(db)
    profile = _profile_or_404(db, profile_id) if profile_id is not None else None
    out = io.BytesIO()
    render_calibration(out, PageLayout(paper, settings.card_w_mm, settings.card_h_mm),
                       profiles.correction(profile, paper), _profile_label(profile))
    name = tr("print_verification") if profile else tr("print_calibration_title")
    return Response(out.getvalue(), media_type="application/pdf", headers={"Content-Disposition": _disposition(name)})


@router.post("/print/profiles/{profile_id}/back-offset")
def save_back_offset(db: Db, profile_id: int, body: BackOffset) -> PrinterProfile:
    """Two-sided printing: the back's offset read on the duplex test page."""
    _profile_or_404(db, profile_id)
    return profiles.save_back_offset(db, profile_id, body)


@router.get("/print/duplex-test.pdf", response_class=Response)
def duplex_test_pdf(
    db: Db,
    duplex: Literal["long", "short"] = "long",
    paper: Paper = "a4",
    profile_id: Annotated[int | None, Query(description="given: its correction and back offset applied")] = None,
) -> Response:
    """Front scales and back lines: shows how far the printer puts the back side off the front."""
    settings = profiles.get_settings(db)
    profile = _profile_or_404(db, profile_id) if profile_id is not None else None
    out = io.BytesIO()
    render_duplex_test(out, PageLayout(paper, settings.card_w_mm, settings.card_h_mm), duplex,
                       profiles.correction(profile, paper), profiles.back_shift(profile, duplex), _profile_label(profile))
    return Response(out.getvalue(), media_type="application/pdf",
                    headers={"Content-Disposition": _disposition(tr("print_duplex_title"))})


@router.post("/print/jobs", status_code=202)
def start_print(db: Db, request: Request, body: ProxyPrint) -> PrintJobStatus:
    """Start building a proxy PDF; poll the job, then download it from /print/jobs/{id}/pdf."""
    faces = card_faces(db, list({i.card_id for i in body.items}))
    unknown = [i.card_id for i in body.items if i.card_id not in faces]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Card not found: {unknown[0]}")
    slots: list[Slot] = []
    backs: list[Slot | None] = []
    for item in body.items:
        name, count = faces[item.card_id]
        for _ in range(item.qty):
            if body.duplex != "off":
                # Two-sided: a double-faced card's back face on the back, else the app's card back.
                slots.append(Slot(item.card_id, 0, name))
                backs.append(Slot(item.card_id, 1, name) if count > 1 and item.faces == "both" else None)
            else:
                slots += [Slot(item.card_id, face, name) for face in range(count if item.faces == "both" else 1)]
    if not slots:
        raise HTTPException(status_code=422, detail=tr("print_nothing"))
    profile = _profile_or_404(db, body.profile_id) if body.profile_id is not None else None
    settings = profiles.get_settings(db)
    layout = PageLayout(body.paper, settings.card_w_mm, settings.card_h_mm, body.gap_mm)
    correction = profiles.correction(profile, body.paper)
    title = body.title.strip() or "Proxies"
    if body.deck_id is not None and db.execute("SELECT 1 FROM decks WHERE id = ?", (body.deck_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Deck not found")
    history_id = history.record_print(
        db, deck_id=body.deck_id, profile_id=profile.id if profile else None, title=title, paper=body.paper,
        style=body.style, duplex=body.duplex, items=[i.model_dump() for i in body.items],
    )
    jobs: PrintJobs = request.app.state.print_jobs
    job = jobs.start(PrintRequest(slots, layout, correction, body.cut_marks, title, _profile_label(profile),
                                  # Unique per print, so downloads don't overwrite each other.
                                  f"{title} - proxies {datetime.now():%Y-%m-%d %H-%M-%S}", current_lang(),
                                  backs or None, body.duplex,
                                  profiles.back_shift(profile, body.duplex), body.style == "text", history_id))
    return _status(job, layout.overflow(correction))


@router.get("/print/history")
def print_history(db: Db) -> list[PrintHistory]:
    """Printed proxy PDFs, newest first."""
    return history.list_history(db)


@router.get("/print/history/{history_id}")
def print_history_entry(db: Db, history_id: int) -> PrintHistory:
    return _history_or_404(lambda: history.get_history(db, history_id))


@router.post("/print/history/{history_id}/mark-proxies")
def mark_proxies(db: Db, history_id: int, body: MarkRequest) -> MarkResult:
    """Record a print's cards as proxies: printed from a deck, in its box (only what it still lacks);
    otherwise in the location given. With dry_run, only what would be marked."""
    return _history_or_404(lambda: history.mark_proxies(db, history_id, body))


class DeckProxy(BaseModel):
    card_id: str
    quantity: int = Field(default=1, ge=1, le=99)


@router.post("/decks/{deck_id}/proxies", status_code=201)
def add_deck_proxy(db: Db, deck_id: int, body: DeckProxy) -> CollectionItem:
    """A proxy of a card in the deck's box (created if the deck has none yet)."""
    try:
        box = deck_box(db, deck_id)
        return add_item(db, CollectionItemCreate(card_id=body.card_id, quantity=body.quantity, location_id=box,
                                                 kind="proxy"))
    except DeckNotFound as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc
    except CardNotFound as exc:
        raise HTTPException(status_code=404, detail=f"Card not found: {exc}") from exc


def _history_or_404(fn):
    try:
        return fn()
    except history.HistoryNotFound as exc:
        raise HTTPException(status_code=404, detail=tr("print_history_not_found")) from exc
    except LocationNotFound as exc:
        raise HTTPException(status_code=404, detail="Location not found") from exc
    except history.NoLocation as exc:
        raise HTTPException(status_code=422, detail=tr("print_choose_location")) from exc


@router.get("/print/jobs/{job_id}")
def print_status(request: Request, job_id: str) -> PrintJobStatus:
    job = request.app.state.print_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=tr("print_job_not_found"))
    return _status(job)


@router.get("/print/jobs/{job_id}/pdf", response_class=FileResponse)
def print_pdf(request: Request, job_id: str) -> FileResponse:
    jobs: PrintJobs = request.app.state.print_jobs
    job = jobs.get(job_id)
    if job is None or job.stage != "done":
        raise HTTPException(status_code=404, detail=tr("print_job_not_found"))
    return FileResponse(jobs.pdf_path(job_id), media_type="application/pdf",
                        headers={"Content-Disposition": _disposition(job.filename)})


def _status(job: PrintJob, overflow: bool = False) -> PrintJobStatus:
    return PrintJobStatus(id=job.id, stage=job.stage, done=job.done, total=job.total, pages=job.pages,
                          missing_images=job.missing_images, error=job.error, overflow=overflow,
                          print_job_id=job.history_id)
