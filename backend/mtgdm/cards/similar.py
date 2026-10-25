"""Cards similar to a card, computed on the fly (nothing is stored).

Candidates are cards whose rules text reads alike (an FTS5 query of the card's adjacent word pairs)
and cards sharing the card's rarest Tagger tags. They are scored by shared tags (each weighted by
how rare it is, so "cast-tax" counts far more than "single-target-instant-sorcery"), by text and by
mana value. Only cards within the chosen color identity (by default the card's own), of a main type
the card has (instants and sorceries count as one), and legal somewhere (or in the deck's format)."""

import json
import math
import re
import sqlite3
from typing import Any

from pydantic import BaseModel

from mtgdm.cards.models import CardSummary
from mtgdm.cards.search import COLORS, EXTRA_LAYOUTS, FORMATS, card_summaries, identity_filter
from mtgdm.scryfall.tags import SYNCED_KEY

WEIGHTS = {"tags": 0.5, "text": 0.3, "mv": 0.2}
TEXT_CANDIDATES = 300
RARE_TAGS = 8              # the card's rarest tags bring in candidates...
RARE_TAG_MAX_CARDS = 1500  # ...unless so common that they say little
OWNED_LIMIT = 24
OWNED_SQL = ("c.oracle_id IN (SELECT x.oracle_id FROM collection_items ci JOIN cards x ON x.id = ci.card_id"
             " WHERE ci.kind = 'real')")
TYPE_GROUPS = (
    ("Creature",), ("Instant", "Sorcery"), ("Artifact",), ("Enchantment",), ("Planeswalker",), ("Land",), ("Battle",),
)
# Words too common to make a phrase on their own ("of the" says nothing, "the battlefield" does).
STOP_WORDS = frozenset("""a an the to of and or its it that this is are be for with on in from as at by if then
    you your may each any up than those these their them they his her one""".split())


class SimilarCard(BaseModel):
    card: CardSummary  # the card's default printing
    score: float       # 0-1


class SimilarCards(BaseModel):
    colors: list[str]           # color identity searched within
    owned: list[SimilarCard]    # with real copies in the collection (ranked apart: never crowded out)
    others: list[SimilarCard]


class DeckNotFound(Exception):
    pass


def similar_cards(conn: sqlite3.Connection, card_id: str, colors: list[str] | None = None, deck_id: int | None = None,
                  limit: int = 60) -> SimilarCards | None:
    card = conn.execute(
        "SELECT oracle_id, name, oracle_text, type_line, cmc, color_identity FROM cards WHERE id = ?", (card_id,)
    ).fetchone()
    if card is None:
        return None
    identity = [c for c in COLORS if c in (colors if colors is not None else json.loads(card["color_identity"] or "[]"))]
    where, params, arena = _filters(conn, card, identity, deck_id)
    signals = _Signals(conn, card)
    owned = signals.ranked([*where, OWNED_SQL], params, OWNED_LIMIT)
    others = signals.ranked([*where, f"NOT {OWNED_SQL}"], params, limit)

    printing = "COALESCE(arena_card_id, default_card_id)" if arena else "default_card_id"
    printings = _chunked(conn, f"SELECT oracle_id, {printing} FROM oracle_cards WHERE oracle_id IN ({{}})",
                         [o for _, o in owned + others])
    summaries = {s.oracle_id: s for s in card_summaries(conn, list(printings.values()))}

    def items(ranked: list[tuple[float, str]]) -> list[SimilarCard]:
        return [SimilarCard(card=summaries[o], score=round(score, 3)) for score, o in ranked if o in summaries]

    return SimilarCards(colors=identity, owned=items(owned), others=items(others))


class _Signals:
    """What a card is compared by: its rules text and its Tagger tags."""

    def __init__(self, conn: sqlite3.Connection, card: sqlite3.Row):
        self.conn = conn
        self.card = card
        self.df, self.tagged = _tag_counts(conn)
        self.tags = _tags_of(conn, [card["oracle_id"]]).get(card["oracle_id"], set())

    def idf(self, tag: str) -> float:
        return math.log(self.tagged / self.df.get(tag, self.tagged))

    def ranked(self, where: list[str], params: list[Any], limit: int) -> list[tuple[float, str]]:
        """(score, oracle id) of the best candidates matching `where`, best first."""
        text = _text_matches(self.conn, self.card, where, params)
        candidates = set(text) | _tag_matches(self.conn, self.tags, self.df, where, params)
        if not candidates:
            return []
        tags = _tags_of(self.conn, list(candidates))
        mana = _mana_values(self.conn, list(candidates))
        best_text = min(text.values()) if text else -1.0  # bm25: more negative is better
        weights = {name: w for name, w in WEIGHTS.items()
                   if (name != "tags" or self.tags) and (name != "text" or text)}
        scored = []
        for oracle_id in candidates:
            theirs = tags.get(oracle_id, set())
            union = sum(self.idf(t) for t in self.tags | theirs)
            parts = {
                "tags": sum(self.idf(t) for t in self.tags & theirs) / union if union else 0.0,
                "text": text[oracle_id] / best_text if oracle_id in text else 0.0,
                "mv": 1 / (1 + abs((mana.get(oracle_id) or 0) - (self.card["cmc"] or 0))),
            }
            scored.append((sum(w * parts[name] for name, w in weights.items()) / sum(weights.values()), oracle_id))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return scored[:limit]


def _filters(conn: sqlite3.Connection, card: sqlite3.Row, identity: list[str],
             deck_id: int | None) -> tuple[list[str], list[Any], bool]:
    """WHERE parts over `c` (a card's default printing, joined through oracle_cards `o`); the third
    value says the deck is an Arena one."""
    where = ["c.oracle_id != ?", f"COALESCE(c.layout, '') NOT IN ({', '.join('?' * len(EXTRA_LAYOUTS))})"]
    params: list[Any] = [card["oracle_id"], *EXTRA_LAYOUTS]
    identity_filter(identity, where, params)
    groups = [g for g in TYPE_GROUPS if any(t in (card["type_line"] or "") for t in g)]
    if groups:
        types = [t for g in groups for t in g]
        where.append("(" + " OR ".join("c.type_line LIKE ?" for _ in types) + ")")
        params += [f"%{t}%" for t in types]
    arena = False
    if deck_id is not None:
        deck = conn.execute("SELECT format, platform FROM decks WHERE id = ?", (deck_id,)).fetchone()
        if deck is None:
            raise DeckNotFound(deck_id)
        if deck["format"] in FORMATS:  # whitelisted, so safe in the JSON path
            where.append(f"json_extract(c.legalities, '$.{deck['format']}') IN ('legal', 'restricted')")
        else:  # freeform
            where.append("""(c.legalities LIKE '%"legal"%' OR c.legalities LIKE '%"restricted"%')""")
        arena = deck["platform"] == "arena"
        if arena:
            where.append("o.arena_card_id IS NOT NULL")
        where.append("c.oracle_id NOT IN (SELECT x.oracle_id FROM deck_cards dc JOIN cards x ON x.id = dc.card_id"
                     " WHERE dc.deck_id = ? AND dc.board IN ('main', 'commander', 'companion'))")
        params.append(deck_id)
    else:
        where.append("""(c.legalities LIKE '%"legal"%' OR c.legalities LIKE '%"restricted"%')""")
    return where, params, arena


def _text_matches(conn: sqlite3.Connection, card: sqlite3.Row, where: list[str], params: list[Any]) -> dict[str, float]:
    """Oracle id -> bm25 rank of the cards whose rules text shares the most word pairs with this one."""
    phrases = _phrases(card["oracle_text"] or "", card["name"])
    if not phrases:
        return {}
    query = "oracle_text : (" + " OR ".join(f'"{p}"' for p in phrases) + ")"
    rows = conn.execute(
        f"""SELECT c.oracle_id, bm25(cards_fts, 0, 0, 1) AS rank
            FROM cards_fts JOIN cards c ON c.rowid = cards_fts.rowid JOIN oracle_cards o ON o.default_card_id = c.id
            WHERE cards_fts MATCH ? AND {' AND '.join(where)} ORDER BY rank LIMIT ?""",
        (query, *params, TEXT_CANDIDATES),
    )
    return {r["oracle_id"]: r["rank"] for r in rows}


def _phrases(text: str, name: str) -> list[str]:
    """Adjacent word pairs within each sentence, without reminder text and the card's own name."""
    text = re.sub(r"\([^)]*\)", " ", text.replace(name, " "))
    pairs: list[str] = []
    for sentence in re.split(r"[.:;\n]", text):
        words = re.findall(r"[a-z0-9]+", sentence.lower())
        pairs += [f"{a} {b}" for a, b in zip(words, words[1:], strict=False) if not (a in STOP_WORDS and b in STOP_WORDS)]
    return list(dict.fromkeys(pairs))


def _tag_matches(conn: sqlite3.Connection, own_tags: set[str], df: dict[str, int], where: list[str],
                 params: list[Any]) -> set[str]:
    rare = sorted((t for t in own_tags if df.get(t, 0) <= RARE_TAG_MAX_CARDS), key=lambda t: df.get(t, 0))[:RARE_TAGS]
    if not rare:
        return set()
    rows = conn.execute(
        f"""SELECT DISTINCT c.oracle_id FROM oracle_taggings t JOIN oracle_cards o ON o.oracle_id = t.oracle_id
            JOIN cards c ON c.id = o.default_card_id
            WHERE t.tag_id IN ({', '.join('?' * len(rare))}) AND {' AND '.join(where)}""",
        (*rare, *params),
    )
    return {r[0] for r in rows}


_counts_cache: dict[tuple[str, str | None], tuple[dict[str, int], int]] = {}


def _tag_counts(conn: sqlite3.Connection) -> tuple[dict[str, int], int]:
    """Cards per tag and tagged cards in all: a full scan (~0.4 s), so kept until the next tag sync."""
    synced = conn.execute("SELECT value FROM meta WHERE key = ?", (SYNCED_KEY,)).fetchone()
    key = (conn.execute("PRAGMA database_list").fetchone()["file"], synced[0] if synced else None)
    if key not in _counts_cache:
        df = {r[0]: r[1] for r in conn.execute("SELECT tag_id, COUNT(*) FROM oracle_taggings GROUP BY tag_id")}
        tagged = conn.execute("SELECT COUNT(DISTINCT oracle_id) FROM oracle_taggings").fetchone()[0]
        _counts_cache.clear()
        _counts_cache[key] = (df, max(tagged, 1))
    return _counts_cache[key]


def _tags_of(conn: sqlite3.Connection, oracle_ids: list[str]) -> dict[str, set[str]]:
    tags: dict[str, set[str]] = {}
    for i in range(0, len(oracle_ids), 500):
        chunk = oracle_ids[i:i + 500]
        for oracle_id, tag_id in conn.execute(
            f"SELECT oracle_id, tag_id FROM oracle_taggings WHERE oracle_id IN ({', '.join('?' * len(chunk))})", chunk
        ):
            tags.setdefault(oracle_id, set()).add(tag_id)
    return tags


def _mana_values(conn: sqlite3.Connection, oracle_ids: list[str]) -> dict[str, float]:
    return _chunked(conn, "SELECT o.oracle_id, c.cmc FROM oracle_cards o JOIN cards c ON c.id = o.default_card_id"
                          " WHERE o.oracle_id IN ({})", oracle_ids)


def _chunked(conn: sqlite3.Connection, sql: str, keys: list[str]) -> dict[str, Any]:
    """Two-column rows as a dict, for a long list of keys (the `{}` in sql takes the placeholders)."""
    result: dict[str, Any] = {}
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        result.update((r[0], r[1]) for r in conn.execute(sql.format(", ".join("?" * len(chunk))), chunk))
    return result
