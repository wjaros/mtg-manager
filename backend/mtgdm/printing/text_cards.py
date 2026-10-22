"""What a text proxy shows: the card's rules text instead of its image (saves ink, needs no download).

Double-faced cards (an image per face) give a text per face; split, adventure and flip cards
(one image, several halves) show all halves on one card."""

import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class CardText:
    name: str
    mana_cost: str
    type_line: str
    oracle_text: str
    stats: str            # "3/3", loyalty "4", defense "5", or ""
    price: str            # "€0.16", "$0.23" or ""
    printing: str         # "DOM #31"


def card_texts(conn: sqlite3.Connection, keys: set[tuple[str, int]]) -> dict[tuple[str, int], CardText]:
    """Texts for (card id, face) pairs."""
    ids = sorted({card_id for card_id, _ in keys})
    if not ids:
        return {}
    rows = {
        r["id"]: r
        for r in conn.execute(
            f"""
            SELECT c.id, c.name, c.mana_cost, c.type_line, c.oracle_text, c.image_faces, c.set_code,
                   c.collector_number, d.card_faces, d.prices, json_extract(d.raw, '$.power') AS power,
                   json_extract(d.raw, '$.toughness') AS toughness, json_extract(d.raw, '$.loyalty') AS loyalty,
                   json_extract(d.raw, '$.defense') AS defense
            FROM cards c LEFT JOIN card_details d ON d.id = c.id
            WHERE c.id IN ({", ".join("?" * len(ids))})
            """,
            ids,
        )
    }
    result = {}
    for card_id, face in keys:
        row = rows.get(card_id)
        if row is not None:
            result[(card_id, face)] = _text(row, face)
    return result


def _text(row: sqlite3.Row, face: int) -> CardText:
    faces = json.loads(row["card_faces"]) if row["card_faces"] else []
    printing = f"{(row['set_code'] or '').upper()} #{row['collector_number']}"
    price = _price(json.loads(row["prices"]) if row["prices"] else {})
    if faces and (row["image_faces"] or 0) > 1 and face < len(faces):
        f = faces[face]
        return CardText(f.get("name", row["name"]), f.get("mana_cost", ""), f.get("type_line", ""),
                        f.get("oracle_text", ""), _stats(f), price if face == 0 else "", printing)
    if faces:
        # Split / adventure / flip: every half on one card.
        halves = [
            "\n".join(part for part in (f"{f.get('name', '')} {f.get('mana_cost', '')}".strip(), f.get("type_line", ""),
                                        f.get("oracle_text", "")) if part)
            for f in faces
        ]
        return CardText(row["name"], "", row["type_line"] or "",
                        "\n\n".join(halves), _stats(dict(row)) or _stats(faces[0]), price, printing)
    return CardText(row["name"], row["mana_cost"] or "", row["type_line"] or "", row["oracle_text"] or "",
                    _stats(dict(row)), price, printing)


def _stats(card: dict) -> str:
    if card.get("power") is not None and card.get("toughness") is not None:
        return f"{card['power']}/{card['toughness']}"
    return str(card.get("loyalty") or card.get("defense") or "")


def _price(prices: dict) -> str:
    for key, sign in (("eur", "€"), ("eur_foil", "€"), ("usd", "$"), ("usd_foil", "$")):
        if prices.get(key):
            return f"{sign}{prices[key]}"
    return ""
