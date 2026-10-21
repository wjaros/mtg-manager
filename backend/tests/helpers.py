"""Shared test data: a real subset of Scryfall default_cards (scripts/make_fixture.py)."""

import json
from functools import cache
from pathlib import Path

from mtgdm.scryfall.bulk import iter_bulk_file

FIXTURE = Path(__file__).parent / "fixtures" / "scryfall" / "cards.jsonl.gz"
SETS_FIXTURE = FIXTURE.with_name("sets.json")
SEEDS_DIR = Path(__file__).resolve().parents[2] / "seeds"


@cache
def _cards_json() -> str:
    return json.dumps(list(iter_bulk_file(FIXTURE)))


def fixture_cards() -> list[dict]:
    """Fresh copy of the fixture cards (tests may mutate them)."""
    return json.loads(_cards_json())


def fixture_sets() -> list[dict]:
    return json.loads(SETS_FIXTURE.read_text(encoding="utf-8"))


def insert_fixture_sets(conn) -> None:
    rows = fixture_sets()
    with conn:
        conn.executemany(
            "INSERT INTO sets(code, arena_code, mtgo_code, name, set_type, released_at, digital)"
            " VALUES (:code, :arena_code, :mtgo_code, :name, :set_type, :released_at, :digital)",
            rows,
        )
