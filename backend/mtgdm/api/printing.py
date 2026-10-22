import io
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from mtgdm.api.deps import Db
from mtgdm.decks.service import DeckNotFound
from mtgdm.i18n import current_lang, tr
from mtgdm.printing import profiles
from mtgdm.printing.candidates import ProxyCandidate, card_faces, proxy_candidates
from mtgdm.printing.jobs import PrintJob, PrintJobs, PrintRequest
from mtgdm.printing.layout import PageLayout
from mtgdm.printing.profiles import (
    CalibrationResult,
    Measurements,
    Paper,
    PrinterProfile,
    PrintSettings,
    ProfileCreate,
    ProfileNotFound,
    ProfileUpdate,
)
from mtgdm.printing.render import Slot, render_calibration

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
    title: str = Field(default="", max_length=200)  # deck name: in the footer and the file name


class PrintJobStatus(BaseModel):
    id: str
    stage: Literal["images", "render", "done", "error"]
    done: int
    total: int
    pages: int
    missing_images: list[str]
    error: str | None
    overflow: bool = False  # the compensated grid leaves the printable area


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
def candidates(db: Db, deck_id: int, include_basics: bool = False) -> list[ProxyCandidate]:
    """Cards of the deck you can't put in its box: not owned, or only in other decks' boxes."""
    try:
        return proxy_candidates(db, deck_id, include_basics)
    except DeckNotFound as exc:
        raise HTTPException(status_code=404, detail="Deck not found") from exc


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


@router.post("/print/jobs", status_code=202)
def start_print(db: Db, request: Request, body: ProxyPrint) -> PrintJobStatus:
    """Start building a proxy PDF; poll the job, then download it from /print/jobs/{id}/pdf."""
    faces = card_faces(db, list({i.card_id for i in body.items}))
    unknown = [i.card_id for i in body.items if i.card_id not in faces]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Card not found: {unknown[0]}")
    slots = [
        Slot(item.card_id, face, faces[item.card_id][0])
        for item in body.items
        for _ in range(item.qty)
        for face in range(faces[item.card_id][1] if item.faces == "both" else 1)
    ]
    if not slots:
        raise HTTPException(status_code=422, detail=tr("print_nothing"))
    profile = _profile_or_404(db, body.profile_id) if body.profile_id is not None else None
    settings = profiles.get_settings(db)
    layout = PageLayout(body.paper, settings.card_w_mm, settings.card_h_mm, body.gap_mm)
    correction = profiles.correction(profile, body.paper)
    title = body.title.strip() or "Proxies"
    jobs: PrintJobs = request.app.state.print_jobs
    job = jobs.start(PrintRequest(slots, layout, correction, body.cut_marks, title, _profile_label(profile),
                                  f"{title} - proxies", current_lang()))
    return _status(job, layout.overflow(correction))


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
                          missing_images=job.missing_images, error=job.error, overflow=overflow)
