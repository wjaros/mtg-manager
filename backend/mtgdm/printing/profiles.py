"""Printer profiles (per printer and paper: how much it scales and shifts a page) and the print
settings (card size, kept in the meta table)."""

import sqlite3
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from mtgdm.printing.layout import DEFAULT_CARD_MM, NO_CORRECTION, Correction, calibrate
from mtgdm.scryfall.bulk import get_meta, set_meta

Paper = Literal["a4", "letter"]
CARD_W_KEY, CARD_H_KEY = "print_card_w_mm", "print_card_h_mm"


class ProfileNotFound(LookupError):
    pass


class PrintSettings(BaseModel):
    card_w_mm: float = Field(ge=50, le=80)
    card_h_mm: float = Field(ge=70, le=110)


class PrinterProfile(BaseModel):
    id: int
    name: str
    paper: Paper
    scale_x: float
    scale_y: float
    offset_x_mm: float
    offset_y_mm: float
    measured_a_mm: float | None
    measured_b_mm: float | None
    measured_left_mm: float | None
    measured_top_mm: float | None
    card_w_mm: float | None  # card size of the calibration page
    card_h_mm: float | None
    back_offset_x_mm: float  # two-sided: the back's shift seen from the front (+ right / down)
    back_offset_y_mm: float
    back_offset_duplex: Literal["long", "short"] | None  # the flip mode it was measured with
    is_default: bool
    calibrated_at: str | None
    note: str | None


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    paper: Paper = "a4"
    is_default: bool = False
    note: str | None = None


class ProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    paper: Paper | None = None
    is_default: bool | None = None
    note: str | None = None


class Measurements(BaseModel):
    measured_a_mm: float = Field(gt=0)
    measured_b_mm: float = Field(gt=0)
    measured_left_mm: float | None = Field(default=None, ge=0)
    measured_top_mm: float | None = Field(default=None, ge=0)


class BackOffset(BaseModel):
    """Read on the duplex test page: where the back's line falls on the front's scale."""

    back_offset_x_mm: float = Field(ge=-10, le=10)
    back_offset_y_mm: float = Field(ge=-10, le=10)
    duplex: Literal["long", "short"]
    # Measured on a test page that already had the profile's back offset applied (verification):
    # what is left adds to it.
    relative: bool = False


class CalibrationResult(BaseModel):
    profile: PrinterProfile
    nominal_a_mm: float
    nominal_b_mm: float
    difference_x_pct: float
    difference_y_pct: float
    out_of_range: bool


def get_settings(conn: sqlite3.Connection) -> PrintSettings:
    w, h = get_meta(conn, CARD_W_KEY), get_meta(conn, CARD_H_KEY)
    return PrintSettings(card_w_mm=float(w or DEFAULT_CARD_MM[0]), card_h_mm=float(h or DEFAULT_CARD_MM[1]))


def save_settings(conn: sqlite3.Connection, settings: PrintSettings) -> PrintSettings:
    with conn:
        set_meta(conn, CARD_W_KEY, str(settings.card_w_mm))
        set_meta(conn, CARD_H_KEY, str(settings.card_h_mm))
    return settings


def list_profiles(conn: sqlite3.Connection) -> list[PrinterProfile]:
    return [_profile(r) for r in conn.execute("SELECT * FROM printer_profiles ORDER BY is_default DESC, name")]


def get_profile(conn: sqlite3.Connection, profile_id: int) -> PrinterProfile:
    row = conn.execute("SELECT * FROM printer_profiles WHERE id = ?", (profile_id,)).fetchone()
    if row is None:
        raise ProfileNotFound(profile_id)
    return _profile(row)


def default_profile(conn: sqlite3.Connection) -> PrinterProfile | None:
    row = conn.execute("SELECT * FROM printer_profiles ORDER BY is_default DESC, id LIMIT 1").fetchone()
    return _profile(row) if row else None


def create_profile(conn: sqlite3.Connection, body: ProfileCreate) -> PrinterProfile:
    with conn:
        # The first profile is the default one.
        first = conn.execute("SELECT COUNT(*) FROM printer_profiles").fetchone()[0] == 0
        profile_id = conn.execute(
            "INSERT INTO printer_profiles(name, paper, note, is_default) VALUES (?, ?, ?, ?)",
            (body.name.strip(), body.paper, body.note, int(body.is_default or first)),
        ).lastrowid
        if body.is_default:
            _only_default(conn, profile_id)
    return get_profile(conn, profile_id)


def update_profile(conn: sqlite3.Connection, profile_id: int, body: ProfileUpdate) -> PrinterProfile:
    get_profile(conn, profile_id)
    changes = body.model_dump(exclude_unset=True)
    with conn:
        for column in ("name", "paper", "note"):
            if column in changes and changes[column] is not None:
                value = changes[column].strip() if column == "name" else changes[column]
                conn.execute(f"UPDATE printer_profiles SET {column} = ? WHERE id = ?", (value, profile_id))
        if changes.get("is_default"):
            _only_default(conn, profile_id)
    return get_profile(conn, profile_id)


def delete_profile(conn: sqlite3.Connection, profile_id: int) -> None:
    profile = get_profile(conn, profile_id)
    with conn:
        conn.execute("DELETE FROM printer_profiles WHERE id = ?", (profile_id,))
        if profile.is_default:
            conn.execute("UPDATE printer_profiles SET is_default = 1 WHERE id = (SELECT MIN(id) FROM printer_profiles)")


def calibrate_profile(conn: sqlite3.Connection, profile_id: int, m: Measurements) -> CalibrationResult:
    """Store the measurements of a calibration page (printed with the current card size and the
    profile's paper) and the factors computed from them."""
    profile = get_profile(conn, profile_id)
    settings = get_settings(conn)
    result = calibrate(profile.paper, settings.card_w_mm, settings.card_h_mm, m.measured_a_mm, m.measured_b_mm,
                       m.measured_left_mm, m.measured_top_mm)
    c = result.correction
    with conn:
        conn.execute(
            """
            UPDATE printer_profiles SET scale_x = ?, scale_y = ?, offset_x_mm = ?, offset_y_mm = ?,
                measured_a_mm = ?, measured_b_mm = ?, measured_left_mm = ?, measured_top_mm = ?,
                card_w_mm = ?, card_h_mm = ?, calibrated_at = ?
            WHERE id = ?
            """,
            (c.scale_x, c.scale_y, c.offset_x, c.offset_y, m.measured_a_mm, m.measured_b_mm, m.measured_left_mm,
             m.measured_top_mm, settings.card_w_mm, settings.card_h_mm,
             datetime.now(UTC).isoformat(timespec="seconds"), profile_id),
        )
    return CalibrationResult(
        profile=get_profile(conn, profile_id),
        nominal_a_mm=result.nominal_a,
        nominal_b_mm=result.nominal_b,
        difference_x_pct=result.difference_x_pct,
        difference_y_pct=result.difference_y_pct,
        out_of_range=result.out_of_range,
    )


def save_back_offset(conn: sqlite3.Connection, profile_id: int, body: BackOffset) -> PrinterProfile:
    profile = get_profile(conn, profile_id)
    x, y = body.back_offset_x_mm, body.back_offset_y_mm
    if body.relative and profile.back_offset_duplex == body.duplex:
        x, y = profile.back_offset_x_mm + x, profile.back_offset_y_mm + y
    with conn:
        conn.execute(
            "UPDATE printer_profiles SET back_offset_x_mm = ?, back_offset_y_mm = ?, back_offset_duplex = ? WHERE id = ?",
            (x, y, body.duplex, profile_id),
        )
    return get_profile(conn, profile_id)


def back_shift(profile: PrinterProfile | None, duplex: Literal["off", "long", "short"]) -> tuple[float, float]:
    """How far to move the backs on the back page so they land behind the fronts.

    The offset is measured from the front. Turned over the long edge, the back page's x runs the
    other way (x_front = W - x_back), so moving the back by +d moves it by -d seen from the front;
    over the short edge, y runs the other way. Only for the flip mode it was measured with.
    """
    if profile is None or duplex == "off" or profile.back_offset_duplex != duplex:
        return 0.0, 0.0
    dx, dy = profile.back_offset_x_mm, profile.back_offset_y_mm
    return (dx, -dy) if duplex == "long" else (-dx, dy)


def recompute(profile: PrinterProfile) -> Correction:
    """The profile's correction, recomputed from its raw measurements (the stored factors are the
    same numbers; this is what a backup restore relies on)."""
    if profile.measured_a_mm is None or profile.measured_b_mm is None or profile.card_w_mm is None:
        return NO_CORRECTION
    return calibrate(profile.paper, profile.card_w_mm, profile.card_h_mm or DEFAULT_CARD_MM[1], profile.measured_a_mm,
                     profile.measured_b_mm, profile.measured_left_mm, profile.measured_top_mm).correction


def correction(profile: PrinterProfile | None, paper: Paper) -> Correction:
    """The scale is the printer's; offsets were measured on the profile's paper only."""
    if profile is None or profile.calibrated_at is None:
        return NO_CORRECTION
    if paper != profile.paper:
        return Correction(profile.scale_x, profile.scale_y)
    return Correction(profile.scale_x, profile.scale_y, profile.offset_x_mm, profile.offset_y_mm)


def _only_default(conn: sqlite3.Connection, profile_id: int) -> None:
    conn.execute("UPDATE printer_profiles SET is_default = (id = ?)", (profile_id,))


def _profile(row: sqlite3.Row) -> PrinterProfile:
    return PrinterProfile(**{**dict(row), "is_default": bool(row["is_default"])})
