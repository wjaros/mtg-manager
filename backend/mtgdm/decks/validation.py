"""Deck validation per format. Works on oracle cards: rules ignore which printing
is in the deck, except for Arena availability and digital-only printings."""

import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from mtgdm.decks.service import DeckNotFound
from mtgdm.i18n import tr

Severity = Literal["error", "warning", "info"]

COMMANDER_FORMATS = {"brawl": 100, "standardbrawl": 60, "commander": 100}
CONSTRUCTED_FORMATS = {"historic", "standard", "pioneer"}
CONSTRUCTED_MIN_SIZE = 60
SIDEBOARD_MAX = 15
MAX_COPIES = 4
# Typical land counts; outside the range is only a warning.
LAND_RANGE = {100: (33, 40), 60: (22, 26)}

_ANY_NUMBER_RE = re.compile(r"A deck can have any number of cards named", re.I)
_UP_TO_RE = re.compile(r"A deck can have up to (\w+) cards named", re.I)
_NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_PARTNER_WITH_RE = re.compile(r"^Partner with ([^(\n]+?)\s*(?:\(|$)", re.M)
_PARTNER_GROUP_RE = re.compile(r"^Partner—([^(\n]+?)\s*(?:\(|$)", re.M)
_PARTNER_RE = re.compile(r"^Partner\s*(?:\(|$)", re.M)


class Issue(BaseModel):
    severity: Severity
    code: str
    message: str
    card_ids: list[str] = []


class ValidationResult(BaseModel):
    valid: bool  # no errors
    format: str
    issues: list[Issue]


@dataclass
class Entry:
    card_id: str
    oracle_id: str
    name: str
    quantity: int
    board: str
    type_line: str
    oracle_text: str
    color_identity: list[str]
    legalities: dict[str, str]
    games: list[str]
    digital: bool
    has_arena_printing: bool
    owned: int = 0
    keywords: list[str] = field(default_factory=list)

    @property
    def front_type(self) -> str:
        return self.type_line.split("//")[0]

    @property
    def is_basic(self) -> bool:
        return "Basic" in self.front_type and "Land" in self.front_type

    @property
    def is_land(self) -> bool:
        return "Land" in self.front_type


def allowed_copies(e: Entry, fmt: str) -> int | None:
    """Copies of a card a deck of this format may have; None: any number (basic lands, "a deck can have
    any number of cards named …", freeform)."""
    if fmt == "freeform" or e.is_basic or _ANY_NUMBER_RE.search(e.oracle_text):
        return None
    if m := _UP_TO_RE.search(e.oracle_text):
        return _NUMBER_WORDS.get(m.group(1).lower(), MAX_COPIES)
    return 1 if fmt in COMMANDER_FORMATS else MAX_COPIES


def validate_deck(conn: sqlite3.Connection, deck_id: int) -> ValidationResult:
    deck = conn.execute("SELECT format, platform FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if deck is None:
        raise DeckNotFound(deck_id)
    entries = load_entries(conn, deck_id)
    fmt, platform = deck["format"], deck["platform"]

    issues: list[Issue] = []
    if fmt in COMMANDER_FORMATS:
        issues += _commander_rules(entries, fmt)
    elif fmt in CONSTRUCTED_FORMATS:
        issues += _constructed_rules(entries, fmt)
    issues += _platform_rules(entries, platform)
    issues += _general_warnings(entries, fmt, platform)
    if platform == "paper":
        issues += _proxy_info(conn, deck_id)

    order = {"error": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order[i.severity])
    return ValidationResult(valid=not any(i.severity == "error" for i in issues), format=fmt, issues=issues)


def load_entries(conn: sqlite3.Connection, deck_id: int) -> list[Entry]:
    rows = conn.execute(
        """
        SELECT dc.card_id, dc.quantity, dc.board, c.oracle_id, c.name, c.type_line, c.oracle_text,
               c.color_identity, c.legalities, c.games, c.digital, c.keywords,
               o.arena_card_id IS NOT NULL AS has_arena_printing,
               (SELECT COALESCE(SUM(ci.quantity), 0) FROM collection_items ci JOIN cards x ON x.id = ci.card_id
                WHERE x.oracle_id = c.oracle_id AND ci.kind = 'real') AS owned
        FROM deck_cards dc
        JOIN cards c ON c.id = dc.card_id
        LEFT JOIN oracle_cards o ON o.oracle_id = c.oracle_id
        WHERE dc.deck_id = ?
        ORDER BY dc.rowid
        """,
        (deck_id,),
    ).fetchall()
    return [
        Entry(
            card_id=r["card_id"],
            oracle_id=r["oracle_id"],
            name=r["name"],
            quantity=r["quantity"],
            board=r["board"],
            type_line=r["type_line"] or "",
            oracle_text=r["oracle_text"] or "",
            color_identity=json.loads(r["color_identity"] or "[]"),
            legalities=json.loads(r["legalities"] or "{}"),
            games=json.loads(r["games"] or "[]"),
            digital=bool(r["digital"]),
            has_arena_printing=bool(r["has_arena_printing"]),
            owned=r["owned"],
            keywords=json.loads(r["keywords"] or "[]"),
        )
        for r in rows
    ]


# --- commander formats --------------------------------------------------------


def _commander_rules(entries: list[Entry], fmt: str) -> list[Issue]:
    issues: list[Issue] = []
    target = COMMANDER_FORMATS[fmt]
    commanders = [e for e in entries if e.board == "commander"]
    in_deck = [e for e in entries if e.board in ("main", "commander")]
    companions = [e for e in entries if e.board == "companion"]
    size = sum(e.quantity for e in in_deck)

    if size != target:
        issues.append(Issue(
            severity="error", code="deck_size",
            message=tr("deck_size_exact", size=size, target=target),
        ))

    if not commanders:
        issues.append(Issue(severity="error", code="no_commander", message=tr("no_commander")))
    elif len(commanders) > 2 or sum(e.quantity for e in commanders) > 2:
        issues.append(Issue(
            severity="error", code="too_many_commanders", message=tr("too_many_commanders"),
            card_ids=[e.card_id for e in commanders],
        ))
    else:
        for c in commanders:
            if not _can_be_commander(c, fmt, partner_slot=len(commanders) == 2):
                issues.append(Issue(
                    severity="error", code="invalid_commander",
                    message=tr("invalid_commander" if fmt == "commander" else "invalid_commander_pw", name=c.name),
                    card_ids=[c.card_id],
                ))
        if len(commanders) == 2 and not _valid_pair(*commanders):
            issues.append(Issue(
                severity="error", code="invalid_partner",
                message=tr("invalid_partner", first=commanders[0].name, second=commanders[1].name),
                card_ids=[e.card_id for e in commanders],
            ))

    identity = {c for e in commanders for c in e.color_identity}
    colorless_commander = bool(commanders) and not identity
    if commanders:
        outside = [
            e for e in in_deck + companions
            if not set(e.color_identity) <= identity and not (colorless_commander and e.is_basic and fmt != "commander")
        ]
        if outside:
            issues.append(Issue(
                severity="error", code="color_identity",
                message=tr("color_identity", identity="".join(sorted(identity)) or tr("colorless"), names=_names(outside)),
                card_ids=[e.card_id for e in outside],
            ))
        if colorless_commander and fmt != "commander":
            basic_types = {e.name for e in in_deck if e.is_basic and e.color_identity}
            if len(basic_types) > 1:
                issues.append(Issue(
                    severity="error", code="colorless_basics",
                    message=tr("colorless_basics", names=", ".join(sorted(basic_types))),
                ))

    issues += _copy_limit(in_deck, limit=1, rule="singleton")
    issues += _legality(in_deck + companions, fmt)

    sideboard = [e for e in entries if e.board == "sideboard"]
    if sideboard:
        issues.append(Issue(
            severity="warning", code="sideboard",
            message=tr("no_sideboard", format=_format_name(fmt), n=sum(e.quantity for e in sideboard)),
            card_ids=[e.card_id for e in sideboard],
        ))
    if len(companions) > 1:
        issues.append(Issue(severity="error", code="companions", message=tr("companions")))
    return issues


def _can_be_commander(e: Entry, fmt: str, partner_slot: bool) -> bool:
    front = e.front_type
    if "can be your commander" in e.oracle_text:
        return True
    if "Legendary" not in front:
        return False
    if "Creature" in front:
        return True
    # Brawl allows planeswalkers; mtg.wiki also lists legendary Vehicles/Spacecraft.
    if fmt != "commander" and ("Planeswalker" in front or "Vehicle" in front or "Spacecraft" in front):
        return True
    return partner_slot and "Background" in front


def _valid_pair(a: Entry, b: Entry) -> bool:
    def partner_with(x: Entry) -> str | None:
        m = _PARTNER_WITH_RE.search(x.oracle_text)
        return m.group(1).strip() if m else None

    def partner_group(x: Entry) -> str | None:
        m = _PARTNER_GROUP_RE.search(x.oracle_text)
        return m.group(1).strip() if m else None

    if partner_with(a) == b.name and partner_with(b) == a.name:
        return True
    if _PARTNER_RE.search(a.oracle_text) and _PARTNER_RE.search(b.oracle_text):
        return True
    if partner_group(a) and partner_group(a) == partner_group(b):
        return True
    if "Friends forever" in a.oracle_text and "Friends forever" in b.oracle_text:
        return True
    for x, y in ((a, b), (b, a)):
        if "Doctor's companion" in x.oracle_text and "Time Lord Doctor" in y.front_type:
            return True
        if "Choose a Background" in x.oracle_text and "Background" in y.front_type:
            return True
    return False


# --- constructed ----------------------------------------------------------------


def _constructed_rules(entries: list[Entry], fmt: str) -> list[Issue]:
    issues: list[Issue] = []
    main = [e for e in entries if e.board == "main"]
    sideboard = [e for e in entries if e.board == "sideboard"]
    size = sum(e.quantity for e in main)
    side_size = sum(e.quantity for e in sideboard)
    if size < CONSTRUCTED_MIN_SIZE:
        issues.append(Issue(
            severity="error", code="deck_size",
            message=tr("deck_size_min", size=size, min=CONSTRUCTED_MIN_SIZE),
        ))
    if side_size > SIDEBOARD_MAX:
        issues.append(Issue(
            severity="error", code="sideboard_size",
            message=tr("sideboard_size", size=side_size, max=SIDEBOARD_MAX),
        ))
    issues += _copy_limit(main + sideboard, limit=MAX_COPIES, rule="max4")
    issues += _legality(main + sideboard, fmt)
    return issues


# --- shared rules -----------------------------------------------------------------


def _copy_limit(entries: list[Entry], limit: int, rule: str) -> list[Issue]:
    by_oracle: dict[str, list[Entry]] = {}
    for e in entries:
        by_oracle.setdefault(e.oracle_id, []).append(e)
    over = []
    for group in by_oracle.values():
        first = group[0]
        count = sum(e.quantity for e in group)
        allowed = limit
        if first.is_basic or _ANY_NUMBER_RE.search(first.oracle_text):
            continue
        if m := _UP_TO_RE.search(first.oracle_text):
            allowed = _NUMBER_WORDS.get(m.group(1).lower(), limit)
        if count > allowed:
            over.append((first, count, allowed))
    if not over:
        return []
    detail = ", ".join(f"{e.name} ×{count}" for e, count, _ in over)
    message = (
        tr("singleton", detail=detail) if rule == "singleton" else tr("max_copies", n=MAX_COPIES, detail=detail)
    )
    over_ids = {e.oracle_id for e, _, _ in over}
    return [Issue(
        severity="error", code=rule, message=message,
        card_ids=[e.card_id for e in entries if e.oracle_id in over_ids],
    )]


def _legality(entries: list[Entry], fmt: str) -> list[Issue]:
    banned, not_legal = [], []
    for e in _unique(entries):
        status = e.legalities.get(fmt, "not_legal")
        if status == "banned":
            banned.append(e)
        elif status not in ("legal", "restricted"):
            not_legal.append(e)
    issues = []
    if banned:
        issues.append(Issue(
            severity="error", code="banned",
            message=tr("banned", format=_format_name(fmt), names=_names(banned)),
            card_ids=[e.card_id for e in banned],
        ))
    if not_legal:
        issues.append(Issue(
            severity="error", code="not_legal",
            message=tr("not_legal", format=_format_name(fmt), names=_names(not_legal)),
            card_ids=[e.card_id for e in not_legal],
        ))
    return issues


def _platform_rules(entries: list[Entry], platform: str) -> list[Issue]:
    playable = [e for e in entries if e.board in ("main", "commander", "companion", "sideboard")]
    if platform == "arena":
        missing = [e for e in _unique(playable) if not e.has_arena_printing]
        swapped = [e for e in _unique(playable) if e.has_arena_printing and "arena" not in e.games]
        issues = []
        if missing:
            issues.append(Issue(
                severity="error", code="not_on_arena",
                message=tr("not_on_arena", names=_names(missing)),
                card_ids=[e.card_id for e in missing],
            ))
        if swapped:
            issues.append(Issue(
                severity="info", code="arena_printing",
                message=tr("arena_printing", names=_names(swapped)),
                card_ids=[e.card_id for e in swapped],
            ))
        return issues
    digital = [e for e in _unique(playable) if e.digital or "paper" not in e.games]
    if digital:
        return [Issue(
            severity="warning", code="digital_only",
            message=tr("digital_only", names=_names(digital)),
            card_ids=[e.card_id for e in digital],
        )]
    return []


def _general_warnings(entries: list[Entry], fmt: str, platform: str) -> list[Issue]:
    issues = []
    in_deck = [e for e in entries if e.board in ("main", "commander")]
    size = sum(e.quantity for e in in_deck)
    target = COMMANDER_FORMATS.get(fmt) or (60 if fmt in CONSTRUCTED_FORMATS else None)
    if target and size >= target * 0.9:
        low, high = LAND_RANGE[100 if target == 100 else 60]
        lands = sum(e.quantity for e in in_deck if e.is_land)
        if not low <= lands <= high:
            issues.append(Issue(
                severity="warning", code="land_count",
                message=tr("land_count", lands=lands, low=low, high=high, target=target),
            ))
    if platform == "paper":
        need = Counter()
        owned = {}
        for e in entries:
            if e.board in ("main", "commander", "companion", "sideboard"):
                need[e.oracle_id] += e.quantity
                owned[e.oracle_id] = e.owned
        missing_ids = {oid for oid, n in need.items() if owned[oid] < n}
        if missing_ids:
            missing = [e for e in _unique(entries) if e.oracle_id in missing_ids]
            copies = sum(need[oid] - owned[oid] for oid in missing_ids)
            issues.append(Issue(
                severity="warning", code="not_in_collection",
                message=tr("not_in_collection", n=copies, names=_names(missing)),
                card_ids=[e.card_id for e in missing],
            ))
    return issues


def _proxy_info(conn: sqlite3.Connection, deck_id: int) -> list[Issue]:
    """Proxies don't change whether the deck is valid (they are its cards); just say how many."""
    from mtgdm.collection.missing import deck_holdings  # collection imports the decks package

    holdings = [h for h in deck_holdings(conn, deck_id) if h.proxy]
    if not holdings:
        return []
    return [Issue(severity="info", code="proxies", message=tr("deck_proxies", n=sum(h.proxy for h in holdings)))]


def _unique(entries: list[Entry]) -> list[Entry]:
    seen, result = set(), []
    for e in entries:
        if e.oracle_id not in seen:
            seen.add(e.oracle_id)
            result.append(e)
    return result


def _names(entries: list[Entry], limit: int = 8) -> str:
    names = [e.name for e in _unique(entries)]
    more = len(names) - limit
    return ", ".join(names[:limit]) + (tr("and_more", n=more) if more > 0 else "")


def _format_name(fmt: str) -> str:
    return {
        "brawl": "Brawl", "standardbrawl": "Standard Brawl", "commander": "Commander",
        "historic": "Historic", "standard": "Standard", "pioneer": "Pioneer",
    }.get(fmt, fmt)
