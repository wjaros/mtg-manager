"""Sync of Scryfall 'default_cards' bulk data into the cards table.

Scryfall serves it as gzipped JSON Lines (jsonl_download_uri, ~80 MB compressed, ~0.5 GB raw);
older API responses had a plain JSON array (download_uri). The file is saved to disk as-is and
streamed card by card, never loaded into memory as a whole.
"""

import gzip
import json
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import batched
from pathlib import Path
from typing import Any

import ijson

from mtgdm.scryfall.client import ScryfallClient
from mtgdm.scryfall.sets import Progress

BULK_TYPE = "default_cards"
BATCH_SIZE = 2000
META_UPDATED_AT = "cards_bulk_updated_at"

# Set types whose printings never become the default printing of a card.
NON_DEFAULT_SET_TYPES = ("memorabilia", "token", "funny", "minigame", "vanguard", "treasure_chest")
# Reprint collections whose printings should not be the default either (The List).
NON_DEFAULT_SETS = ("plst",)
# Frame effects of alternate-art treatments; plain printings are preferred as default.
SPECIAL_FRAME_EFFECTS = ("showcase", "extendedart", "inverted", "etched", "shatteredglass")

CARD_COLUMNS = (
    "id", "oracle_id", "name", "lang", "layout", "mana_cost", "cmc", "type_line", "oracle_text",
    "colors", "color_identity", "keywords", "legalities", "games", "arena_id", "set_code",
    "collector_number", "rarity", "finishes", "digital", "released_at", "produced_mana",
    "printed_name", "promo", "variation", "booster", "border_color", "frame_effects", "artist",
    "image_faces", "updated_at",
)
DETAIL_COLUMNS = ("id", "image_uris", "card_faces", "prices", "raw")

# Fields left out of cards.raw: copied into columns above, or links/ids we never use.
# Keeps the database ~40% smaller; the full object can always be re-read from the bulk file.
RAW_EXCLUDED_FIELDS = frozenset({
    "object", "id", "oracle_id", "name", "lang", "layout", "mana_cost", "cmc", "type_line",
    "oracle_text", "colors", "color_identity", "keywords", "legalities", "games", "arena_id",
    "set", "collector_number", "rarity", "finishes", "digital", "released_at", "produced_mana",
    "prices", "image_uris", "card_faces", "printed_name", "promo", "variation", "booster",
    "border_color", "frame_effects", "artist",
    "uri", "scryfall_uri", "rulings_uri", "prints_search_uri", "set_uri", "set_search_uri",
    "scryfall_set_uri", "related_uris", "purchase_uris",
})



def _upsert_sql(table: str, columns: tuple[str, ...]) -> str:
    return (
        f"INSERT INTO {table}({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))})"
        f" ON CONFLICT(id) DO UPDATE SET " + ", ".join(f"{c} = excluded.{c}" for c in columns if c != "id")
    )


_UPSERT_CARDS = _upsert_sql("cards", CARD_COLUMNS)
_UPSERT_DETAILS = _upsert_sql("card_details", DETAIL_COLUMNS)


@dataclass
class CardSyncResult:
    updated_at: str
    skipped: bool = False
    cards: int = 0
    removed: int = 0


def sync_cards(
    conn: sqlite3.Connection,
    client: ScryfallClient,
    bulk_dir: Path,
    *,
    force: bool = False,
    on_progress: Progress | None = None,
) -> CardSyncResult:
    """Download default_cards if Scryfall has a newer file than the last import, then import it."""
    info = client.bulk_data(BULK_TYPE)
    updated_at = info["updated_at"]
    if not force and get_meta(conn, META_UPDATED_AT) == updated_at:
        return CardSyncResult(updated_at=updated_at, skipped=True)

    path = download_bulk(client, info, bulk_dir, on_progress)
    return import_cards(conn, iter_bulk_file(path), updated_at, on_progress)


def download_bulk(
    client: ScryfallClient, info: dict[str, Any], bulk_dir: Path, on_progress: Progress | None = None,
    *, name: str = BULK_TYPE, stage: str = "download",
) -> Path:
    bulk_dir.mkdir(parents=True, exist_ok=True)
    url = info.get("jsonl_download_uri") or info["download_uri"]
    target = bulk_dir / f"{name}.data"
    tmp = target.with_suffix(".part")
    total = int(info.get("compressed_size") or info.get("size") or 0)
    done = 0
    try:
        with client.stream(url) as resp, tmp.open("wb") as f:
            total = int(resp.headers.get("Content-Length") or 0) or total
            # Raw bytes, no transparent decompression: iter_bulk_file detects gzip itself.
            for chunk in resp.iter_raw(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if on_progress:
                    on_progress(stage, done, total)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def import_cards(
    conn: sqlite3.Connection,
    cards: Iterable[dict[str, Any]],
    updated_at: str,
    on_progress: Progress | None = None,
) -> CardSyncResult:
    """Upsert cards in one transaction, drop vanished unreferenced ones, rebuild oracle_cards."""
    result = CardSyncResult(updated_at=updated_at)
    with conn:
        for batch in batched((card_row(c, updated_at) for c in cards), BATCH_SIZE):
            _ensure_sets(conn, batch)
            conn.executemany(_UPSERT_CARDS, [r.card for r in batch])
            conn.executemany(_UPSERT_DETAILS, [r.details for r in batch])
            result.cards += len(batch)
            if on_progress:
                on_progress("import", result.cards, 0)

        result.removed = conn.execute(
            """
            DELETE FROM cards WHERE updated_at IS NOT ?
              AND id NOT IN (SELECT card_id FROM deck_cards)
              AND id NOT IN (SELECT card_id FROM collection_items)
              AND id NOT IN (SELECT chosen_card_id FROM scan_items WHERE chosen_card_id IS NOT NULL)
            """,
            (updated_at,),
        ).rowcount
        rebuild_oracle_cards(conn)
        set_meta(conn, META_UPDATED_AT, updated_at)
    return result


@dataclass
class CardRows:
    card: tuple[Any, ...]                 # cards row in CARD_COLUMNS order
    details: tuple[Any, ...]              # card_details row in DETAIL_COLUMNS order
    set_info: tuple[str, str, str | None]  # (code, name, set_type) for placeholder sets


def card_row(card: dict[str, Any], updated_at: str) -> CardRows:
    """Map one Scryfall card object to its database rows."""
    faces = card.get("card_faces") or []
    front = faces[0] if faces else {}

    # Multi-faced cards (transform, MDFC, reversible) keep some fields only on faces.
    mana_cost = card.get("mana_cost")
    if mana_cost is None and faces:
        mana_cost = " // ".join(f.get("mana_cost", "") for f in faces)
    oracle_text = card.get("oracle_text")
    if oracle_text is None and faces:
        oracle_text = "\n//\n".join(f.get("oracle_text", "") for f in faces)
    colors = card.get("colors")
    if colors is None and faces:
        colors = sorted({c for f in faces for c in f.get("colors", [])}, key="WUBRG".index)

    values = {
        "id": card["id"],
        "oracle_id": card.get("oracle_id") or front.get("oracle_id"),
        "name": card["name"],
        "lang": card.get("lang", "en"),
        "layout": card.get("layout"),
        "mana_cost": mana_cost,
        "cmc": card.get("cmc"),
        "type_line": card.get("type_line") or " // ".join(f.get("type_line", "") for f in faces) or None,
        "oracle_text": oracle_text,
        "colors": _json(colors),
        "color_identity": _json(card.get("color_identity")),
        "keywords": _json(card.get("keywords")),
        "legalities": _json(card.get("legalities")),
        "games": _json(card.get("games")),
        "arena_id": card.get("arena_id"),
        "set_code": card["set"],
        "collector_number": card.get("collector_number"),
        "rarity": card.get("rarity"),
        "finishes": _json(card.get("finishes")),
        "digital": int(bool(card.get("digital"))),
        "released_at": card.get("released_at"),
        "produced_mana": _json(card.get("produced_mana")),
        "prices": _json(card.get("prices")),
        "image_uris": _json(card.get("image_uris")),
        "card_faces": _json(faces or None),
        "image_faces": 1 if card.get("image_uris") else sum(1 for f in faces if f.get("image_uris")),
        "printed_name": card.get("printed_name"),
        "promo": int(bool(card.get("promo"))),
        "variation": int(bool(card.get("variation"))),
        "booster": int(bool(card.get("booster"))),
        "border_color": card.get("border_color"),
        "frame_effects": _json(card.get("frame_effects")),
        "artist": card.get("artist") or front.get("artist"),
        "raw": _json({k: v for k, v in card.items() if k not in RAW_EXCLUDED_FIELDS}),
        "updated_at": updated_at,
    }
    return CardRows(
        card=tuple(values[c] for c in CARD_COLUMNS),
        details=tuple(values[c] for c in DETAIL_COLUMNS),
        set_info=(card["set"], card.get("set_name") or card["set"], card.get("set_type")),
    )


def rebuild_oracle_cards(conn: sqlite3.Connection) -> None:
    """Pick per oracle_id the default printing and the newest Arena printing."""
    excluded = ", ".join(f"'{t}'" for t in NON_DEFAULT_SET_TYPES)
    special = ", ".join(f"'{t}'" for t in SPECIAL_FRAME_EFFECTS)
    excluded_sets = ", ".join(f"'{t}'" for t in NON_DEFAULT_SETS)
    conn.execute("DELETE FROM oracle_cards")
    conn.execute(
        f"""
        INSERT INTO oracle_cards(oracle_id, name, default_card_id, arena_card_id)
        WITH flagged AS (
            SELECT c.oracle_id, c.name, c.id, c.released_at, c.collector_number,
                   c.lang = 'en' AS is_en,
                   EXISTS (SELECT 1 FROM json_each(c.games) WHERE value = 'paper') AS is_paper,
                   EXISTS (SELECT 1 FROM json_each(c.games) WHERE value = 'arena') AS is_arena,
                   c.promo = 0 AND c.variation = 0
                       AND COALESCE(s.set_type, '') NOT IN ({excluded})
                       AND c.set_code NOT IN ({excluded_sets}) AS is_regular,
                   c.booster AS is_booster,
                   COALESCE(c.border_color, '') != 'borderless'
                       AND NOT EXISTS (SELECT 1 FROM json_each(c.frame_effects) WHERE value IN ({special}))
                       AS is_plain
            FROM cards c LEFT JOIN sets s ON s.code = c.set_code
            WHERE c.oracle_id IS NOT NULL
        ),
        ranked AS (
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY oracle_id
                       -- regular English paper booster printings in a plain frame first, newest wins
                       ORDER BY is_en DESC, is_paper DESC, is_regular DESC, is_booster DESC,
                                is_plain DESC, released_at DESC,
                                CAST(collector_number AS INTEGER), id
                   ) AS rn_default,
                   ROW_NUMBER() OVER (
                       PARTITION BY oracle_id
                       -- same preferences as the default printing, among Arena printings
                       ORDER BY is_arena DESC, is_regular DESC, is_booster DESC, is_plain DESC,
                                released_at DESC, CAST(collector_number AS INTEGER), id
                   ) AS rn_arena
            FROM flagged
        )
        SELECT oracle_id,
               MAX(CASE WHEN rn_default = 1 THEN name END),
               MAX(CASE WHEN rn_default = 1 THEN id END),
               MAX(CASE WHEN rn_arena = 1 AND is_arena THEN id END)
        FROM ranked
        GROUP BY oracle_id
        """
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _ensure_sets(conn: sqlite3.Connection, batch: Iterable[CardRows]) -> None:
    """Insert placeholder rows for sets missing from the sets table (cards.set_code is a FK)."""
    conn.executemany(
        "INSERT INTO sets(code, name, set_type) VALUES (?, ?, ?) ON CONFLICT(code) DO NOTHING",
        list({r.set_info[0]: r.set_info for r in batch}.values()),
    )


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def iter_bulk_file(path: Path) -> Iterator[dict[str, Any]]:
    """Stream cards from a bulk file: gzipped or plain, JSON Lines or a JSON array."""
    with path.open("rb") as raw:
        gzipped = raw.read(2) == b"\x1f\x8b"
    with (gzip.open(path, "rb") if gzipped else path.open("rb")) as f:
        first = f.peek(64).lstrip()[:1]
        if first == b"[":
            yield from ijson.items(f, "item", use_float=True)
            return
        for line in f:
            line = line.strip().rstrip(b",")
            if line:
                yield json.loads(line)
