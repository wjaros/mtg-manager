"""Subset of Scryfall search syntax for the name search box:

    t:angel  o:"enters the battlefield"  c:wu  c=r  id<=wr  mv>=5  r:mythic  s:who  f:brawl  otag:ramp
    -t:creature  (negation)   "exact phrase" / plain words (card name)

Plain words and quoted phrases are returned as name text; every key:value becomes a SQL clause on
the cards table aliased `c`.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from mtgdm.i18n import tr

COLORS = "WUBRG"
COLOR_NAMES = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
    "colorless": "C", "multicolor": "M", "multicolored": "M",
}
RARITY_ORDER = ["common", "uncommon", "rare", "mythic"]
RARITY_ALIASES = {"c": "common", "u": "uncommon", "r": "rare", "m": "mythic", "s": "special", "b": "bonus"}

KEYS = {
    "t": "type", "type": "type",
    "o": "oracle", "oracle": "oracle",
    "c": "color", "color": "color", "colour": "color",
    "id": "identity", "identity": "identity", "ci": "identity", "commander": "identity",
    "mv": "mv", "cmc": "mv", "manavalue": "mv",
    "r": "rarity", "rarity": "rarity",
    "s": "set", "set": "set", "e": "set", "edition": "set",
    "f": "format", "format": "format", "legal": "format",
    "name": "name",
    "otag": "tag", "oracletag": "tag", "function": "tag",
    "tag": "usertag", "mytag": "usertag",
}
# Keys whose result depends on the printing, not only on the card.
PRINTING_KEYS = {"rarity", "set"}

_TOKEN_RE = re.compile(
    r'(?P<neg>-)?(?P<key>[a-zA-Z]+)(?P<op><=|>=|!=|:|=|<|>)(?P<value>"[^"]*"|[^\s"]+)'
    r'|"(?P<phrase>[^"]*)"'
    r"|(?P<word>\S+)"
)


class QuerySyntaxError(ValueError):
    """Invalid search syntax (message is shown to the user)."""


@dataclass
class ParsedSyntax:
    name_text: str = ""
    clauses: list[tuple[str, list[Any]]] = field(default_factory=list)
    printing_level: bool = False

    @property
    def empty(self) -> bool:
        return not self.name_text and not self.clauses


def parse_syntax(text: str, formats: frozenset[str]) -> ParsedSyntax:
    parsed = ParsedSyntax()
    words: list[str] = []
    for m in _TOKEN_RE.finditer(text or ""):
        if m.group("phrase") is not None:
            words.append(m.group("phrase"))
            continue
        if m.group("word") is not None:
            words.append(m.group("word"))
            continue
        key = KEYS.get(m.group("key").lower())
        if key is None:
            raise QuerySyntaxError(tr("unknown_filter", key=m.group("key")))
        value = m.group("value").strip('"')
        if not value:
            raise QuerySyntaxError(tr("empty_filter", text=m.group(0)))
        sql, params = _clause(key, m.group("op"), value, formats)
        if m.group("neg"):
            sql = f"NOT ({sql})"
        parsed.clauses.append((sql, params))
        parsed.printing_level |= key in PRINTING_KEYS
    parsed.name_text = " ".join(words)
    return parsed


def bare_words(text: str) -> list[re.Match[str]]:
    """The query's words without a key (they search card names), with their positions."""
    return [m for m in _TOKEN_RE.finditer(text or "") if m.group("word") is not None]


def _clause(key: str, op: str, value: str, formats: frozenset[str]) -> tuple[str, list[Any]]:
    v = value.lower()
    if key == "type":
        return "c.type_line LIKE ?", [f"%{value}%"]
    if key == "usertag":  # the user's own tags (mtgdm.cards.user_tags); the column ignores case
        return "c.oracle_id IN (SELECT oracle_id FROM user_tags WHERE tag = ?)", [value]
    if key == "oracle":
        return "c.oracle_text LIKE ?", [f"%{value}%"]
    if key == "name":
        return "c.name LIKE ?", [f"%{value}%"]
    if key == "tag":  # Scryfall's function tags (only those the app counts, see mtgdm.scryfall.tags)
        return "c.oracle_id IN (SELECT oracle_id FROM card_tags WHERE tag = ?)", [v]
    if key == "set":
        return "c.set_code = ?", [v]
    if key == "format":
        if v not in formats:
            raise QuerySyntaxError(tr("unknown_format", value=value))
        return f"json_extract(c.legalities, '$.{v}') IN ('legal', 'restricted')", []
    if key == "mv":
        try:
            number = float(v)
        except ValueError:
            raise QuerySyntaxError(tr("mv_number", value=value)) from None
        sql_op = {"": "=", ":": "=", "=": "=", "!=": "!=", "<": "<", ">": ">", "<=": "<=", ">=": ">="}[op]
        return f"c.cmc {sql_op} ?", [number]
    if key == "rarity":
        rarity = RARITY_ALIASES.get(v, v)
        if rarity not in RARITY_ORDER + ["special", "bonus"]:
            raise QuerySyntaxError(tr("unknown_rarity", value=value))
        if op in (":", "=", "!="):
            return f"c.rarity {'!=' if op == '!=' else '='} ?", [rarity]
        if rarity not in RARITY_ORDER:
            raise QuerySyntaxError(tr("rarity_compare"))
        index = RARITY_ORDER.index(rarity)
        allowed = [r for i, r in enumerate(RARITY_ORDER) if _compare(i, op, index)]
        return f"c.rarity IN ({', '.join('?' * len(allowed)) or 'NULL'})", allowed
    if key in ("color", "identity"):
        return _color_clause(key, op, v)
    raise QuerySyntaxError(tr("unsupported_filter", key=key))


def _color_clause(key: str, op: str, value: str) -> tuple[str, list[Any]]:
    column = "c.colors" if key == "color" else "c.color_identity"
    letters = COLOR_NAMES.get(value, value).upper()
    if letters == "M":
        return f"json_array_length(COALESCE({column}, '[]')) >= 2", []
    if bad := set(letters) - set(COLORS + "C"):
        raise QuerySyntaxError(tr("unknown_colors", colors="".join(sorted(bad))))
    chosen = [c for c in COLORS if c in letters]
    if not chosen:  # "c" / "colorless": no colors at all
        sql = f"json_array_length(COALESCE({column}, '[]')) = 0"
        return (f"NOT ({sql})", []) if op == "!=" else (sql, [])
    # Scryfall: c:X means "at least X", id:X means "fits in X".
    if op == ":":
        op = ">=" if key == "color" else "<="
    contains = [f"EXISTS (SELECT 1 FROM json_each({column}) WHERE value = ?)" for _ in chosen]
    length = f"json_array_length(COALESCE({column}, '[]'))"
    subset = f"NOT EXISTS (SELECT 1 FROM json_each({column}) WHERE value NOT IN ({', '.join('?' * len(chosen)) or "''"}))"
    if op in ("=", "!="):
        sql = " AND ".join(contains + [f"{length} = ?"])
        params: list[Any] = [*chosen, len(chosen)]
        return (f"NOT ({sql})", params) if op == "!=" else (sql, params)
    if op == ">=":
        return (" AND ".join(contains) or "1"), chosen
    if op == ">":
        return " AND ".join(contains + [f"{length} > ?"]), [*chosen, len(chosen)]
    if op == "<=":
        return subset, chosen
    if op == "<":
        return f"{subset} AND {length} < ?", [*chosen, len(chosen)]
    raise QuerySyntaxError(tr("unsupported_operator", op=op))


def _compare(a: int, op: str, b: int) -> bool:
    return {"<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
