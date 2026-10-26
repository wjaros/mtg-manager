"""Search sources: a marketplace's or a seller's search URL with {query} where the card's name goes.
The user makes one by searching something in the shop and replacing the phrase in the URL with {query}."""

import sqlite3
from typing import Literal
from urllib.parse import quote_plus, urlsplit

from pydantic import BaseModel

from mtgdm.decks.export import arena_name

QueryMode = Literal["name", "name_set"]
PLACEHOLDER = "{query}"
SAMPLE_CARD = "Sol Ring"


class PurchaseSource(BaseModel):
    id: int
    name: str
    url_template: str
    enabled: bool
    sort_order: int
    query_mode: QueryMode
    query_suffix: str
    note: str | None
    free_delivery_threshold: float | None  # None: the global setting
    shipping_cost: float | None


class PurchaseLink(BaseModel):
    source_id: int
    name: str
    url: str


class SourceNotFound(Exception):
    pass


class InvalidTemplate(ValueError):
    """key: the i18n message (template_https / template_placeholder)."""

    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


def validate_template(template: str) -> str:
    template = template.strip()
    parts = urlsplit(template)
    if parts.scheme != "https" or not parts.netloc:
        raise InvalidTemplate("template_https")
    if PLACEHOLDER not in template:
        raise InvalidTemplate("template_placeholder")
    return template


def search_query(name: str, layout: str | None = None, set_name: str | None = None,
                 mode: QueryMode = "name", suffix: str = "") -> str:
    """The phrase searched for: a double-faced card by its front face (a split card by its full name),
    with the set's name in name_set mode, then the suffix as typed (" mtg")."""
    query = arena_name(name, layout)
    if mode == "name_set" and set_name:
        query = f"{query} {set_name}"
    return (query + suffix).strip()


def build_search_url(template: str, name: str, layout: str | None = None, set_name: str | None = None,
                     mode: QueryMode = "name", suffix: str = "") -> str:
    """The template with {query} replaced by the URL-encoded phrase (spaces as +, Polish letters and
    apostrophes percent-encoded)."""
    template = validate_template(template)
    return template.replace(PLACEHOLDER, quote_plus(search_query(name, layout, set_name, mode, suffix)))


def _source(row: sqlite3.Row) -> PurchaseSource:
    return PurchaseSource(
        id=row["id"], name=row["name"], url_template=row["url_template"], enabled=bool(row["enabled"]),
        sort_order=row["sort_order"], query_mode=row["query_mode"], query_suffix=row["query_suffix"],
        note=row["note"], free_delivery_threshold=row["free_delivery_threshold"], shipping_cost=row["shipping_cost"],
    )


def list_sources(conn: sqlite3.Connection, enabled_only: bool = False) -> list[PurchaseSource]:
    return [_source(r) for r in conn.execute(
        "SELECT * FROM purchase_sources WHERE ? = 0 OR enabled = 1 ORDER BY sort_order, id", (int(enabled_only),)
    )]


def get_source(conn: sqlite3.Connection, source_id: int) -> PurchaseSource:
    row = conn.execute("SELECT * FROM purchase_sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise SourceNotFound(source_id)
    return _source(row)


FIELDS = ("name", "url_template", "enabled", "sort_order", "query_mode", "query_suffix", "note",
          "free_delivery_threshold", "shipping_cost")


def create_source(conn: sqlite3.Connection, values: dict) -> PurchaseSource:
    values = {k: v for k, v in values.items() if k in FIELDS}
    values["url_template"] = validate_template(values["url_template"])
    if "sort_order" not in values:
        values["sort_order"] = conn.execute("SELECT COALESCE(MAX(sort_order) + 1, 0) FROM purchase_sources").fetchone()[0]
    with conn:
        source_id = conn.execute(
            f"INSERT INTO purchase_sources({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
            list(values.values()),
        ).lastrowid
    return get_source(conn, source_id)


def update_source(conn: sqlite3.Connection, source_id: int, values: dict) -> PurchaseSource:
    get_source(conn, source_id)
    values = {k: v for k, v in values.items() if k in FIELDS}
    if "url_template" in values:
        values["url_template"] = validate_template(values["url_template"])
    if values:
        with conn:
            conn.execute(
                f"UPDATE purchase_sources SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                [*values.values(), source_id],
            )
    return get_source(conn, source_id)


def delete_source(conn: sqlite3.Connection, source_id: int) -> None:
    get_source(conn, source_id)
    with conn:
        conn.execute("DELETE FROM purchase_sources WHERE id = ?", (source_id,))


def source_url(source: PurchaseSource, name: str, layout: str | None = None, set_name: str | None = None) -> str:
    return build_search_url(source.url_template, name, layout, set_name, source.query_mode, source.query_suffix)


def links(sources: list[PurchaseSource], name: str, layout: str | None = None,
          set_name: str | None = None) -> list[PurchaseLink]:
    """One search link per source (the enabled ones, in order)."""
    return [PurchaseLink(source_id=s.id, name=s.name, url=source_url(s, name, layout, set_name))
            for s in sources if s.enabled]


def card_links(conn: sqlite3.Connection, card_id: str) -> list[PurchaseLink] | None:
    """Links for a printing (its set's name in name_set mode); None: no such card."""
    row = conn.execute(
        "SELECT c.name, c.layout, s.name AS set_name FROM cards c LEFT JOIN sets s ON s.code = c.set_code"
        " WHERE c.id = ?", (card_id,)
    ).fetchone()
    if row is None:
        return None
    return links(list_sources(conn, enabled_only=True), row["name"], row["layout"], row["set_name"])


# --- backup ------------------------------------------------------------------------------


def backup_sources(conn: sqlite3.Connection) -> list[dict]:
    return [s.model_dump(exclude={"id"}) for s in list_sources(conn)]


def restore_sources(conn: sqlite3.Connection, entries: list[dict], replace: bool) -> dict[str, int]:
    """Sources from a backup; returns {name: new id} for offers that name them. Without replace, a source
    with the same name and template is kept (the default Allegro one isn't doubled). No transaction of its own."""
    if replace:
        conn.execute("DELETE FROM purchase_sources")
    ids: dict[str, int] = {}
    for e in entries:
        template = validate_template(e["url_template"])
        row = conn.execute("SELECT id FROM purchase_sources WHERE name = ? AND url_template = ?",
                           (e["name"], template)).fetchone()
        values = {k: e[k] for k in FIELDS if k in e}
        values["url_template"] = template
        if row:
            conn.execute(f"UPDATE purchase_sources SET {', '.join(f'{k} = ?' for k in values)} WHERE id = ?",
                         [*values.values(), row[0]])
            ids[e["name"]] = row[0]
        else:
            ids[e["name"]] = conn.execute(
                f"INSERT INTO purchase_sources({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                list(values.values()),
            ).lastrowid
    return ids
