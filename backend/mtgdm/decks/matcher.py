"""Resolve parsed decklist lines to card printings. Never falls back silently:
every deviation from what the line asked for becomes a warning in the report."""

import json
import re
import sqlite3
from dataclasses import dataclass

from mtgdm.cards.search import EXTRA_LAYOUTS, card_summaries, fts_prefix_query
from mtgdm.decks.textformat import ParsedLine
from mtgdm.i18n import tr

ALCHEMY_PREFIX = "A-"


@dataclass
class Match:
    card_id: str | None
    warnings: list[str]
    suggestions: list[str]


class NameIndex:
    """Lower-cased card names (full and front face) -> oracle_id, built once per import.

    Tokens, emblems and art cards can share a name with a real card (the token "Ajani's
    Pridemate"), so they are indexed first and real cards overwrite them."""

    def __init__(self, conn: sqlite3.Connection):
        self.full: dict[str, str] = {}
        self.front: dict[str, str] = {}
        extras = ", ".join(f"'{layout}'" for layout in EXTRA_LAYOUTS)
        rows = conn.execute(
            f"""
            SELECT o.oracle_id, o.name FROM oracle_cards o JOIN cards c ON c.id = o.default_card_id
            ORDER BY COALESCE(c.layout, '') IN ({extras}) DESC
            """
        )
        for oracle_id, name in rows:
            self.full[name.lower()] = oracle_id
            if " // " in name:
                self.front[name.split(" // ")[0].lower()] = oracle_id

    def lookup(self, name: str) -> str | None:
        key = name.lower().strip()
        return self.full.get(key) or self.front.get(key) or self.front.get(key.split(" // ")[0])


class Matcher:
    def __init__(self, conn: sqlite3.Connection, platform: str = "paper", preferred_sets: list[str] | None = None):
        self.conn = conn
        self.platform = platform
        self.preferred_sets = [s.lower() for s in preferred_sets or []]
        self.names = NameIndex(conn)

    def match(self, line: ParsedLine) -> Match:
        warnings: list[str] = []
        name = line.name
        oracle_id = self.names.lookup(name)

        if oracle_id is None and name.startswith(ALCHEMY_PREFIX):
            # Scryfall has no rebalanced Alchemy cards; use the original card.
            oracle_id = self.names.lookup(name[len(ALCHEMY_PREFIX):])
            if oracle_id:
                warnings.append(tr("alchemy", name=name, original=name[len(ALCHEMY_PREFIX):]))
        if oracle_id is None:
            oracle_id = self._by_printed_name(name)
            if oracle_id:
                warnings.append(tr("printed_name", name=name))
        if oracle_id is None:
            return Match(None, warnings, self._suggest(name))

        card_id = None
        if line.set_code:
            card_id = self._by_set(oracle_id, line.set_code, line.collector_number, warnings)
        if card_id is None:
            card_id = self._default_printing(oracle_id)
        self._check_platform(card_id, oracle_id, explicit=line.set_code is not None, warnings=warnings)
        if self.platform == "arena" and not line.set_code:
            card_id = self._arena_printing(card_id, oracle_id)
        return Match(card_id, warnings, [])

    # --- printing selection -------------------------------------------------

    def _by_set(self, oracle_id: str, set_code: str, number: str | None, warnings: list[str]) -> str | None:
        """Printing in the given set. Scryfall codes win over Arena codes, but only if the set
        actually has this card (me1's Arena code 'med' is also the Scryfall code of another set)."""
        candidates = [r[0] for r in self.conn.execute(
            "SELECT code FROM sets WHERE code = ? UNION ALL SELECT code FROM sets WHERE arena_code = ? AND code != ?",
            (set_code, set_code, set_code),
        )]
        for code in candidates:
            printings = self.conn.execute(
                "SELECT id, collector_number FROM cards WHERE oracle_id = ? AND set_code = ?"
                " ORDER BY booster DESC, promo, CAST(collector_number AS INTEGER), collector_number",
                (oracle_id, code),
            ).fetchall()
            if not printings:
                continue
            if number is None:
                return printings[0]["id"]
            for p in printings:
                if p["collector_number"] == number:
                    return p["id"]
            wanted = _normalize_number(number)
            for p in printings:
                if _normalize_number(p["collector_number"]) == wanted:
                    return p["id"]
            chosen = printings[0]
            warnings.append(tr("no_number_in_set", number=number, set=set_code.upper(), used=chosen["collector_number"]))
            return chosen["id"]
        warnings.append(tr("not_in_set", set=set_code.upper()))
        return None

    def _default_printing(self, oracle_id: str) -> str:
        for set_code in self.preferred_sets:
            row = self.conn.execute(
                "SELECT id FROM cards WHERE oracle_id = ? AND set_code = ?"
                " ORDER BY booster DESC, promo, CAST(collector_number AS INTEGER) LIMIT 1",
                (oracle_id, set_code),
            ).fetchone()
            if row:
                return row["id"]
        row = self.conn.execute(
            "SELECT default_card_id FROM oracle_cards WHERE oracle_id = ?", (oracle_id,)
        ).fetchone()
        return row["default_card_id"]

    def _arena_printing(self, card_id: str, oracle_id: str) -> str:
        if "arena" in self._games(card_id):
            return card_id
        row = self.conn.execute("SELECT arena_card_id FROM oracle_cards WHERE oracle_id = ?", (oracle_id,)).fetchone()
        return row["arena_card_id"] or card_id

    def _check_platform(self, card_id: str, oracle_id: str, explicit: bool, warnings: list[str]) -> None:
        games = self._games(card_id)
        if self.platform == "arena":
            has_arena = self.conn.execute(
                "SELECT arena_card_id IS NOT NULL FROM oracle_cards WHERE oracle_id = ?", (oracle_id,)
            ).fetchone()[0]
            if not has_arena:
                warnings.append(tr("card_not_on_arena"))
            elif explicit and "arena" not in games:
                warnings.append(tr("printing_not_on_arena"))
        elif "paper" not in games:
            warnings.append(tr("digital_card"))

    # --- helpers ------------------------------------------------------------

    def _games(self, card_id: str) -> list[str]:
        row = self.conn.execute("SELECT games FROM cards WHERE id = ?", (card_id,)).fetchone()
        return json.loads(row["games"] or "[]") if row else []

    def _by_printed_name(self, name: str) -> str | None:
        row = self.conn.execute(
            "SELECT oracle_id FROM cards WHERE printed_name = ? COLLATE NOCASE AND oracle_id IS NOT NULL LIMIT 1",
            (name,),
        ).fetchone()
        return row["oracle_id"] if row else None

    def _suggest(self, name: str, limit: int = 3) -> list[str]:
        match = fts_prefix_query(name.removeprefix(ALCHEMY_PREFIX), ("name",))
        if not match:
            return []
        rows = self.conn.execute(
            """
            SELECT DISTINCT o.name FROM cards_fts f
            JOIN cards c ON c.rowid = f.rowid
            JOIN oracle_cards o ON o.oracle_id = c.oracle_id
            WHERE cards_fts MATCH ? LIMIT ?
            """,
            (match, limit),
        ).fetchall()
        return [r[0] for r in rows]


def _normalize_number(number: str) -> str:
    """'061a' -> '61': mtg.wtf and others add face letters or leading zeros."""
    stripped = re.sub(r"[a-z★†]+$", "", number.lower()).lstrip("0")
    return stripped or "0"


def summaries_by_id(conn: sqlite3.Connection, ids: list[str]):
    return {c.id: c for c in card_summaries(conn, list(dict.fromkeys(ids)))}
