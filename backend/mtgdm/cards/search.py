"""Card search over the local Scryfall data (FTS5 + filters)."""

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any

from mtgdm.cards.models import (
    CardDetail,
    CardFace,
    CardPage,
    CardSummary,
    ColorMode,
    Order,
    Owned,
    SetInfo,
    Unique,
)
from mtgdm.cards.syntax import ParsedSyntax, QuerySyntaxError, parse_syntax

COLORS = "WUBRG"
FORMATS = frozenset({
    "standard", "pioneer", "modern", "legacy", "vintage", "pauper", "commander", "brawl",
    "standardbrawl", "historic", "timeless", "alchemy", "explorer", "oathbreaker", "penny",
    "duel", "oldschool", "premodern", "predh", "gladiator", "future",
})
# Layouts that are not deck cards; hidden unless include_extras is set.
EXTRA_LAYOUTS = ("token", "double_faced_token", "emblem", "art_series", "vanguard", "planar", "scheme")
MAX_PAGE_SIZE = 200

_SUMMARY_COLUMNS = """
    c.id, c.oracle_id, c.name, c.printed_name, c.lang, c.layout, c.mana_cost, c.cmc, c.type_line,
    c.rarity, c.set_code, COALESCE(s.name, c.set_code) AS set_name, c.collector_number,
    c.released_at, c.colors, c.color_identity, c.games, c.artist, c.image_faces,
    (SELECT COALESCE(SUM(ci.quantity), 0) FROM collection_items ci
     WHERE ci.card_id = c.id AND ci.kind = 'real') AS owned_printing,
    (SELECT COALESCE(SUM(ci.quantity), 0) FROM collection_items ci JOIN cards x ON x.id = ci.card_id
     WHERE x.oracle_id = c.oracle_id AND ci.kind = 'real') AS owned
"""
# Oracle ids / printings with at least one copy in the collection: real copies only, or proxies too.
def _owned_kinds(include_proxies: bool) -> str:
    return "ci.kind IN ('real', 'proxy')" if include_proxies else "ci.kind = 'real'"
_ORDER_SQL = {
    "name": "name COLLATE NOCASE, released_at DESC",
    "mv": "cmc, name COLLATE NOCASE",
    "released": "released_at DESC, name COLLATE NOCASE",
}


@dataclass
class CardQuery:
    q: str | None = None             # card name words and/or Scryfall-style filters (see cards/syntax.py)
    text: str | None = None          # words matched against type line and rules text
    colors: str | None = None        # e.g. "WU", "C" = colorless
    color_mode: ColorMode = "include"
    identity: str | None = None      # color identity must fit inside these colors, e.g. "WU" ("C" = colorless)
    mv: list[int] = field(default_factory=list)  # 7 means 7+
    types: list[str] = field(default_factory=list)
    rarity: list[str] = field(default_factory=list)
    sets: list[str] = field(default_factory=list)
    format: str | None = None
    game: str | None = None          # paper | arena | mtgo
    owned: Owned | None = None       # owned = any printing in the collection (exact printing with unique=prints)
    deck: int | None = None          # deck being built: its own box counts as free for owned=free
    not_in_deck: int | None = None   # hide cards already in this deck (except basic lands)
    include_extras: bool = False
    include_proxies: bool = False    # the owned filter counts proxies as copies too
    tags: list[str] = field(default_factory=list)  # Scryfall function tags, each required (otag:)
    unique: Unique = "cards"
    order: Order = "name"
    page: int = 1
    page_size: int = 60


class InvalidQuery(ValueError):
    pass


def search_cards(conn: sqlite3.Connection, query: CardQuery) -> CardPage:
    try:
        syntax = parse_syntax(query.q or "", FORMATS)
    except QuerySyntaxError as exc:
        raise InvalidQuery(str(exc)) from exc
    where, params = _filters(query, syntax)
    where_sql = " AND ".join(where) or "1"
    page_size = max(1, min(query.page_size, MAX_PAGE_SIZE))
    page = max(1, query.page)
    paging = [page_size, (page - 1) * page_size]

    # Phase 1 sorts and pages only (id + sort keys); phase 2 loads full rows for one page.
    # Sorting full rows (images, faces) would drag ~4 KB per card through the sort.
    order_sql = _ORDER_SQL[query.order]
    keys = "c.id, c.name, c.cmc, c.released_at"
    if query.unique == "prints":
        total = conn.execute(f"SELECT COUNT(*) FROM cards c WHERE {where_sql}", params).fetchone()[0]
        ids_sql = f"SELECT {keys} FROM cards c WHERE {where_sql}"
    elif not _has_printing_filters(query) and not syntax.printing_level:
        # Card-level filters only: search the precomputed representative printing per card
        # (the Arena one when searching Arena cards). The default printing is a paper one
        # whenever the card exists on paper, so game=paper can use it too.
        rep = "o.arena_card_id" if query.game == "arena" else "o.default_card_id"
        ids_sql = f"SELECT {keys} FROM oracle_cards o JOIN cards c ON c.id = {rep} WHERE {where_sql}"
        total = conn.execute(f"SELECT COUNT(*) FROM ({ids_sql})", params).fetchone()[0]
    else:
        # Printing-level filters: among matching printings of each card prefer the default one.
        total = conn.execute(
            f"SELECT COUNT(DISTINCT c.oracle_id) FROM cards c WHERE {where_sql}", params
        ).fetchone()[0]
        ids_sql = f"""
            SELECT id, name, cmc, released_at FROM (
                SELECT {keys},
                       ROW_NUMBER() OVER (
                           PARTITION BY c.oracle_id
                           ORDER BY (c.id = o.default_card_id) DESC, c.released_at DESC, c.id
                       ) AS rn
                FROM cards c JOIN oracle_cards o ON o.oracle_id = c.oracle_id
                WHERE {where_sql}
            ) WHERE rn = 1
        """

    ids = [r[0] for r in conn.execute(
        f"SELECT id FROM ({ids_sql}) ORDER BY {order_sql} LIMIT ? OFFSET ?", params + paging
    )]
    return CardPage(total=total, page=page, page_size=page_size, items=card_summaries(conn, ids))


def card_summaries(conn: sqlite3.Connection, ids: list[str]) -> list[CardSummary]:
    """Summaries in the order of ids (unknown ids are skipped)."""
    if not ids:
        return []
    rows = conn.execute(
        f"SELECT {_SUMMARY_COLUMNS} FROM cards c LEFT JOIN sets s ON s.code = c.set_code"
        f" WHERE c.id IN ({', '.join('?' * len(ids))})",
        ids,
    ).fetchall()
    by_id = {r["id"]: r for r in rows}
    return [_summary(by_id[i]) for i in ids if i in by_id]


def get_card(conn: sqlite3.Connection, card_id: str) -> CardDetail | None:
    row = conn.execute(
        f"""
        SELECT {_SUMMARY_COLUMNS}, c.oracle_text, c.keywords, c.legalities, c.finishes,
               c.produced_mana, c.updated_at, c.arena_id, c.digital, c.promo,
               d.prices, d.card_faces, d.raw,
               (SELECT COUNT(*) FROM cards p WHERE p.oracle_id = c.oracle_id) AS printings_count
        FROM cards c
        LEFT JOIN sets s ON s.code = c.set_code
        LEFT JOIN card_details d ON d.id = c.id
        WHERE c.id = ?
        """,
        (card_id,),
    ).fetchone()
    if row is None:
        return None
    raw = _load(row["raw"], {})
    faces = _load(row["card_faces"], [])
    face_fields = CardFace.model_fields.keys()
    return CardDetail(
        **_summary(row).model_dump(),
        oracle_text=row["oracle_text"],
        power=raw.get("power"),
        toughness=raw.get("toughness"),
        loyalty=raw.get("loyalty"),
        flavor_text=raw.get("flavor_text"),
        keywords=_load(row["keywords"], []),
        legalities=_load(row["legalities"], {}),
        finishes=_load(row["finishes"], []),
        produced_mana=_load(row["produced_mana"], []),
        prices=_load(row["prices"], {}),
        prices_updated_at=row["updated_at"],
        arena_id=row["arena_id"],
        digital=bool(row["digital"]),
        promo=bool(row["promo"]),
        faces=[CardFace(**{k: v for k, v in f.items() if k in face_fields}) for f in faces],
        printings_count=row["printings_count"],
    )


def get_printings(conn: sqlite3.Connection, card_id: str) -> list[CardSummary] | None:
    row = conn.execute("SELECT oracle_id FROM cards WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        return None
    if row["oracle_id"] is None:
        cond, params = "c.id = ?", [card_id]
    else:
        cond, params = "c.oracle_id = ?", [row["oracle_id"]]
    rows = conn.execute(
        f"SELECT {_SUMMARY_COLUMNS} FROM cards c LEFT JOIN sets s ON s.code = c.set_code"
        f" WHERE {cond} ORDER BY c.released_at DESC, s.name, CAST(c.collector_number AS INTEGER), c.collector_number",
        params,
    ).fetchall()
    return [_summary(r) for r in rows]


def list_sets(conn: sqlite3.Connection) -> list[SetInfo]:
    rows = conn.execute(
        """
        SELECT s.code, s.name, s.set_type, s.released_at, s.digital, s.arena_code, s.icon_path,
               COALESCE(n.cnt, 0) AS card_count
        FROM sets s
        LEFT JOIN (SELECT set_code, COUNT(*) AS cnt FROM cards GROUP BY set_code) n ON n.set_code = s.code
        ORDER BY s.released_at DESC, s.name
        """
    ).fetchall()
    return [
        SetInfo(
            code=r["code"], name=r["name"], set_type=r["set_type"], released_at=r["released_at"],
            digital=bool(r["digital"]), arena_code=r["arena_code"], card_count=r["card_count"],
            has_icon=r["icon_path"] is not None,
        )
        for r in rows
    ]


def fts_prefix_query(text: str, columns: tuple[str, ...]) -> str | None:
    """'giada fo' -> '{name} : ("giada"* AND "fo"*)'; None if there are no searchable words."""
    words = re.findall(r"\w+", text)
    if not words:
        return None
    terms = " AND ".join('"' + w.replace('"', '""') + '"*' for w in words)
    return f"{{{' '.join(columns)}}} : ({terms})"


def _has_printing_filters(q: CardQuery) -> bool:
    """Filters whose result differs between printings of the same card."""
    return bool(q.sets or q.rarity or q.game == "mtgo")


def _filters(q: CardQuery, syntax: ParsedSyntax) -> tuple[list[str], list[Any]]:
    where: list[str] = []
    params: list[Any] = []

    for text, columns in ((syntax.name_text, ("name",)), (q.text, ("type_line", "oracle_text"))):
        if text and (match := fts_prefix_query(text, columns)):
            where.append("c.rowid IN (SELECT rowid FROM cards_fts WHERE cards_fts MATCH ?)")
            params.append(match)

    for sql, clause_params in syntax.clauses:
        where.append(sql)
        params += clause_params

    if q.colors:
        letters = q.colors.upper()
        if bad := set(letters) - set(COLORS + "C"):
            raise InvalidQuery(f"unknown colors: {''.join(sorted(bad))}")
        chosen = [c for c in COLORS if c in letters]
        if q.color_mode == "identity":
            _identity_filter(chosen, where, params)
        else:
            for color in chosen:
                where.append("EXISTS (SELECT 1 FROM json_each(c.colors) WHERE value = ?)")
                params.append(color)
            if q.color_mode == "exact" or "C" in letters:
                where.append("json_array_length(COALESCE(c.colors, '[]')) = ?")
                params.append(len(chosen))

    if q.identity is not None:
        letters = q.identity.upper()
        if bad := set(letters) - set(COLORS + "C"):
            raise InvalidQuery(f"unknown colors: {''.join(sorted(bad))}")
        _identity_filter([c for c in COLORS if c in letters], where, params)

    if q.mv:
        parts = []
        exact = sorted({v for v in q.mv if 0 <= v < 7})
        if exact:
            parts.append(f"CAST(c.cmc AS INTEGER) IN ({', '.join('?' * len(exact))})")
            params += exact
        if any(v >= 7 for v in q.mv):
            parts.append("c.cmc >= 7")
        if parts:
            where.append("(" + " OR ".join(parts) + ")")

    for tag in q.tags:
        where.append("c.oracle_id IN (SELECT oracle_id FROM card_tags WHERE tag = ?)")
        params.append(tag)

    for type_word in q.types:
        where.append("c.type_line LIKE ?")
        params.append(f"%{type_word}%")

    if q.rarity:
        where.append(f"c.rarity IN ({', '.join('?' * len(q.rarity))})")
        params += [r.lower() for r in q.rarity]

    if q.sets:
        where.append(f"c.set_code IN ({', '.join('?' * len(q.sets))})")
        params += [s.lower() for s in q.sets]

    if q.format:
        if q.format not in FORMATS:
            raise InvalidQuery(f"unknown format: {q.format}")
        # Format name is whitelisted above, so it is safe in the JSON path.
        where.append(f"json_extract(c.legalities, '$.{q.format}') IN ('legal', 'restricted')")

    if q.game:
        where.append("EXISTS (SELECT 1 FROM json_each(c.games) WHERE value = ?)")
        params.append(q.game)

    kinds = _owned_kinds(q.include_proxies)
    owned_oracles = f"SELECT x.oracle_id FROM collection_items ci JOIN cards x ON x.id = ci.card_id WHERE {kinds}"
    if q.owned == "free":
        # Copies not sitting in another deck's box (loose, in binders, or in this deck's box).
        free = (
            " AND (ci.location_id IS NULL OR ci.location_id NOT IN"
            " (SELECT location_id FROM decks WHERE location_id IS NOT NULL AND id IS NOT ?))"
        )
        if q.unique == "prints":
            where.append(f"c.id IN (SELECT ci.card_id FROM collection_items ci WHERE {kinds}{free})")
        else:
            where.append(f"c.oracle_id IN ({owned_oracles}{free})")
        params.append(q.deck)
    elif q.owned:
        negate = "NOT " if q.owned == "missing" else ""
        if q.unique == "prints":
            where.append(f"c.id {negate}IN (SELECT ci.card_id FROM collection_items ci WHERE {kinds})")
        else:
            where.append(f"c.oracle_id {negate}IN ({owned_oracles})")

    if q.not_in_deck is not None:
        where.append(
            "(c.type_line LIKE 'Basic Land%' OR c.oracle_id NOT IN (SELECT x.oracle_id FROM deck_cards dc"
            " JOIN cards x ON x.id = dc.card_id WHERE dc.deck_id = ? AND dc.board IN ('main', 'commander', 'companion')))"
        )
        params.append(q.not_in_deck)

    if not q.include_extras:
        where.append(f"COALESCE(c.layout, '') NOT IN ({', '.join('?' * len(EXTRA_LAYOUTS))})")
        params += EXTRA_LAYOUTS

    return where, params


def _identity_filter(colors: list[str], where: list[str], params: list[Any]) -> None:
    """Card's color identity must fit inside `colors` (colorless always fits)."""
    # NOT IN (NULL) would match nothing, so an empty choice uses a never-matching value.
    placeholders = ", ".join("?" * len(colors)) or "''"
    where.append(f"NOT EXISTS (SELECT 1 FROM json_each(c.color_identity) WHERE value NOT IN ({placeholders}))")
    params += colors


def _summary(row: sqlite3.Row) -> CardSummary:
    return CardSummary(
        id=row["id"],
        oracle_id=row["oracle_id"],
        name=row["name"],
        printed_name=row["printed_name"],
        lang=row["lang"],
        layout=row["layout"],
        mana_cost=row["mana_cost"],
        cmc=row["cmc"],
        type_line=row["type_line"],
        rarity=row["rarity"],
        set_code=row["set_code"],
        set_name=row["set_name"],
        collector_number=row["collector_number"],
        released_at=row["released_at"],
        colors=_load(row["colors"], []),
        color_identity=_load(row["color_identity"], []),
        games=_load(row["games"], []),
        artist=row["artist"],
        image_faces=row["image_faces"],
        owned=row["owned"],
        owned_printing=row["owned_printing"],
    )


def _load(value: str | None, default: Any) -> Any:
    return json.loads(value) if value else default
