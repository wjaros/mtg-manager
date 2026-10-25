"""Cards similar to a card, computed on the fly (nothing is stored).

Candidates are cards whose rules text reads alike (an FTS5 query of the card's adjacent word pairs)
and cards sharing the card's rarest Tagger tags. Their relevance comes from shared tags and text;
mana value only scales it, and too little relevance leaves a card out. A tag counts with its
ancestors ("burn-creature" is also "removal-burn", "removal-creature", ...), so related tags share
some weight, and each is weighted by how rare it is ("cast-tax" counts far more than "removal").
Tag families that say nothing about what a card does (cycles, draft signposts, names, ...) are
ignored. Only cards within the chosen color identity (by default the card's own), of a main type the
card has (instants and sorceries count as one), and legal somewhere (or in the deck's format)."""

import json
import math
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from mtgdm.cards.models import CardSummary
from mtgdm.cards.search import COLORS, EXTRA_LAYOUTS, FORMATS, card_summaries, identity_filter
from mtgdm.scryfall.tags import SYNCED_KEY

WEIGHTS = {"tags": 0.6, "text": 0.4}  # relevance; a missing signal leaves the other alone
MV_WEIGHT = 0.2         # score = relevance * (1 - MV_WEIGHT + MV_WEIGHT * mana value closeness)
MIN_RELEVANCE = 0.15
OWNED_MIN_SCORE = 0.15  # owned cards: at least this score...
OWNED_MIN_SHARE = 0.3   # ...and this share of the best score found (owned or not)
TEXT_CANDIDATES = 300
RARE_TAGS = 8              # the card's rarest tags bring in candidates...
RARE_TAG_MAX_CARDS = 1500  # ...unless so common that they say little
OWNED_LIMIT = 24
OWNED_SQL = ("c.oracle_id IN (SELECT x.oracle_id FROM collection_items ci JOIN cards x ON x.id = ci.card_id"
             " WHERE ci.kind = 'real')")
# Tagger families saying nothing about what a card does, by root tag id; their descendants too.
NON_FUNCTIONAL_TAGS = frozenset({
    "1adda1a4-e23d-4212-a4da-58303a20e00c",  # cycle (a third of all tags)
    "79bfc75b-78e1-46ba-9527-3ebaff284aad",  # draft-signpost
    "5a0a0531-5462-477d-add9-886148c4413f",  # card-names
    "a3909e64-69d4-442e-8da1-fffa309492b8",  # alliteration
    "97dc6a1e-f6d5-46b6-afee-df9cd1c865c1",  # meme
    "bc363109-3735-4d44-9b0c-cb2d3ed14e7f",  # un-design
    "a48e9cf5-08eb-466f-9ace-3a66c4c6c69a",  # type-errata
    "aa1d20fe-4b9b-4f0f-ada7-db0df9ddaf2e",  # digital-only-mechanics
    "1f17b570-e7c3-44d7-a215-04eaa50d7110",  # face-commander
    "18871a0d-8f9d-43de-baac-9a21301ec5c5",  # alt-commander
})
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
    owned_text = _text_matches(conn, card, [*where, OWNED_SQL], params)
    others_text = _text_matches(conn, card, [*where, f"NOT {OWNED_SQL}"], params)
    # Text is scored against the best match of both lists: the best owned one alone may be weak.
    reference = min([*owned_text.values(), *others_text.values()], default=-1.0)  # bm25: lower is better
    owned = signals.ranked([*where, OWNED_SQL], params, owned_text, reference, OWNED_LIMIT)
    others = signals.ranked([*where, f"NOT {OWNED_SQL}"], params, others_text, reference, limit)
    # A small collection has few close matches: its best ones aren't necessarily good ones.
    best = max((score for score, _ in owned[:1] + others[:1]), default=0.0)
    owned = [(score, o) for score, o in owned if score >= max(OWNED_MIN_SCORE, OWNED_MIN_SHARE * best)]

    printing = "COALESCE(arena_card_id, default_card_id)" if arena else "default_card_id"
    printings = _chunked(conn, f"SELECT oracle_id, {printing} FROM oracle_cards WHERE oracle_id IN ({{}})",
                         [o for _, o in owned + others])
    summaries = {s.oracle_id: s for s in card_summaries(conn, list(printings.values()))}

    def items(ranked: list[tuple[float, str]]) -> list[SimilarCard]:
        return [SimilarCard(card=summaries[o], score=round(score, 3)) for score, o in ranked if o in summaries]

    return SimilarCards(colors=identity, owned=items(owned), others=items(others))


class _Signals:
    """What a card is compared by: its rules text and its functional Tagger tags (with ancestors)."""

    def __init__(self, conn: sqlite3.Connection, card: sqlite3.Row):
        self.conn = conn
        self.card = card
        self.tag_data = _tag_data(conn)
        self.direct = _direct_tags(conn, [card["oracle_id"]]).get(card["oracle_id"], set()) - self.tag_data.excluded
        self.tags = self.tag_data.lift(self.direct)
        self.has_text = bool(_phrases(card["oracle_text"] or "", card["name"]))

    def ranked(self, where: list[str], params: list[Any], text: dict[str, float], text_reference: float,
               limit: int) -> list[tuple[float, str]]:
        """(score, oracle id) of the best candidates matching `where` (`text`: their text matches),
        best first."""
        data = self.tag_data
        candidates = set(text) | _tag_matches(self.conn, self.direct, data.df, where, params)
        if not candidates:
            return []
        tags = {o: data.lift(direct) for o, direct in _direct_tags(self.conn, list(candidates)).items()}
        mana = _mana_values(self.conn, list(candidates))
        weights = {name: w for name, w in WEIGHTS.items()
                   if (name != "tags" or self.tags) and (name != "text" or self.has_text)}
        scored = []
        for oracle_id in candidates:
            theirs = tags.get(oracle_id, set())
            union = sum(data.idf(t) for t in self.tags | theirs)
            parts = {
                "tags": sum(data.idf(t) for t in self.tags & theirs) / union if union else 0.0,
                "text": text[oracle_id] / text_reference if oracle_id in text else 0.0,
            }
            relevance = sum(w * parts[name] for name, w in weights.items()) / sum(weights.values())
            if relevance < MIN_RELEVANCE:
                continue
            closeness = 1 / (1 + abs((mana.get(oracle_id) or 0) - (self.card["cmc"] or 0)))
            scored.append((relevance * (1 - MV_WEIGHT + MV_WEIGHT * closeness), oracle_id))
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
    """Adjacent word pairs within each sentence, without reminder text and the card's own name; a
    one-word line (a keyword: "Flying") is a term of its own. Pairs of mana symbols ("{R}{W}" in a
    cost) are left out."""
    text = re.sub(r"\([^)]*\)", " ", text.replace(name, " "))
    terms: list[str] = []
    for sentence in re.split(r"[.:;\n]", text):
        words = re.findall(r"[a-z0-9]+", sentence.lower())
        if len(words) == 1:
            terms.append(words[0])
        terms += [f"{a} {b}" for a, b in zip(words, words[1:], strict=False)
                  if not (a in STOP_WORDS and b in STOP_WORDS) and not (len(a) == 1 and len(b) == 1)]
    return list(dict.fromkeys(terms))


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


@dataclass
class _TagData:
    lifted: dict[str, frozenset[str]]  # a functional tag with its functional ancestors
    excluded: frozenset[str]           # non-functional tags
    df: dict[str, int]                 # cards per tag, those of its descendants included
    tagged: int                        # cards with a functional tag

    def lift(self, direct: set[str]) -> set[str]:
        return set().union(*(self.lifted.get(t, ()) for t in direct))

    def idf(self, tag: str) -> float:
        return math.log(self.tagged / self.df.get(tag, self.tagged))


_tag_data_cache: dict[tuple[str, str | None], _TagData] = {}


def _tag_data(conn: sqlite3.Connection) -> _TagData:
    """Built from all taggings (~1 s), so kept until the next tag sync."""
    synced = conn.execute("SELECT value FROM meta WHERE key = ?", (SYNCED_KEY,)).fetchone()
    key = (conn.execute("PRAGMA database_list").fetchone()["file"], synced[0] if synced else None)
    if key not in _tag_data_cache:
        _tag_data_cache.clear()
        _tag_data_cache[key] = _load_tag_data(conn)
    return _tag_data_cache[key]


def _load_tag_data(conn: sqlite3.Connection) -> _TagData:
    parents: dict[str, list[str]] = {}
    children: dict[str, list[str]] = {}
    for tag_id, parent_id in conn.execute("SELECT tag_id, parent_id FROM oracle_tag_parents"):
        parents.setdefault(tag_id, []).append(parent_id)
        children.setdefault(parent_id, []).append(tag_id)
    excluded = _reach(NON_FUNCTIONAL_TAGS, children)
    lifted = {tag_id: frozenset() if tag_id in excluded else frozenset(_reach({tag_id}, parents) - excluded)
              for (tag_id,) in conn.execute("SELECT id FROM oracle_tags")}
    df: Counter[str] = Counter()
    tagged = 0
    current, tags = None, set()
    for oracle_id, tag_id in conn.execute("SELECT oracle_id, tag_id FROM oracle_taggings ORDER BY oracle_id"):
        if oracle_id != current:
            df.update(tags)
            tagged += bool(tags)
            current, tags = oracle_id, set()
        tags |= lifted.get(tag_id, frozenset())
    df.update(tags)
    tagged += bool(tags)
    return _TagData(lifted, frozenset(excluded), dict(df), max(tagged, 1))


def _reach(start: set[str] | frozenset[str], links: dict[str, list[str]]) -> set[str]:
    """The tags given and all reachable through links (parents or children); cycles are fine."""
    seen: set[str] = set()
    stack = list(start)
    while stack:
        tag_id = stack.pop()
        if tag_id not in seen:
            seen.add(tag_id)
            stack += links.get(tag_id, [])
    return seen


def _direct_tags(conn: sqlite3.Connection, oracle_ids: list[str]) -> dict[str, set[str]]:
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
