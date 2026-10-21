"""Deck statistics. Counted over the cards that are played: main + commander."""

import json
import re
import sqlite3
from collections import Counter

from pydantic import BaseModel

from mtgdm.decks.service import DeckNotFound
from mtgdm.scryfall.bulk import META_UPDATED_AT, get_meta

COLORS = ["W", "U", "B", "R", "G"]
MV_BUCKETS = ["0", "1", "2", "3", "4", "5", "6", "7+"]
CARD_TYPES = ["Creature", "Instant", "Sorcery", "Enchantment", "Artifact", "Planeswalker", "Battle", "Land"]
RARITIES = ["common", "uncommon", "rare", "mythic", "special", "bonus"]
_SYMBOL_RE = re.compile(r"\{([^}]+)\}")


class CurveBucket(BaseModel):
    mv: str
    total: int
    by_color: dict[str, int]  # W/U/B/R/G, M = multicolor, C = colorless


class ColorBalance(BaseModel):
    color: str
    pips: int            # mana symbols of this color in costs
    land_sources: int    # lands that can produce it
    other_sources: int   # nonland sources (rocks, dorks, rituals...)


class Price(BaseModel):
    eur: float
    usd: float
    missing_eur: float   # cards not in the collection (paper decks)
    missing_usd: float
    unpriced: int        # cards without a price
    as_of: str | None    # date of the Scryfall data the prices come from


class DeckStats(BaseModel):
    total: int
    lands: int
    nonlands: int
    average_mv: float | None  # without lands
    curve: list[CurveBucket]
    types: dict[str, int]          # each type a card has
    primary_types: dict[str, int]  # one type per card
    rarity: dict[str, int]
    colors: list[ColorBalance]
    categories: dict[str, int]
    price: Price
    wildcards: dict[str, int]      # Arena wildcards per rarity to craft the deck (basic lands are free)


def deck_stats(conn: sqlite3.Connection, deck_id: int) -> DeckStats:
    rows = conn.execute(
        """
        SELECT dc.quantity, dc.category, c.oracle_id, c.layout, c.type_line, c.mana_cost, c.cmc, c.colors,
               c.rarity, c.produced_mana, c.games, d.prices,
               (SELECT rarity FROM cards a WHERE a.id = o.arena_card_id) AS arena_rarity,
               (SELECT COALESCE(SUM(ci.quantity), 0) FROM collection_items ci JOIN cards x ON x.id = ci.card_id
                WHERE x.oracle_id = c.oracle_id) AS owned
        FROM deck_cards dc
        JOIN cards c ON c.id = dc.card_id
        LEFT JOIN card_details d ON d.id = c.id
        LEFT JOIN oracle_cards o ON o.oracle_id = c.oracle_id
        WHERE dc.deck_id = ? AND dc.board IN ('main', 'commander')
        """,
        (deck_id,),
    ).fetchall()
    deck = conn.execute("SELECT platform FROM decks WHERE id = ?", (deck_id,)).fetchone()
    if deck is None:
        raise DeckNotFound(deck_id)
    platform = deck["platform"]

    total = lands = mv_sum = 0
    curve = {b: Counter() for b in MV_BUCKETS}
    types, primary, rarity, categories = Counter(), Counter(), Counter(), Counter()
    pips, land_sources, other_sources = Counter(), Counter(), Counter()
    wildcards = Counter()
    eur = usd = missing_eur = missing_usd = 0.0
    unpriced = 0
    needed: Counter[str] = Counter()
    owned: dict[str, int] = {}

    for r in rows:
        qty = r["quantity"]
        front = (r["type_line"] or "").split("//")[0]
        is_land = "Land" in front
        total += qty
        rarity[r["rarity"] or "common"] += qty
        if r["category"]:
            categories[r["category"]] += qty
        for t in CARD_TYPES:
            if t in front:
                types[t] += qty
        primary[next((t for t in CARD_TYPES if t in front), "Other")] += qty

        produced = json.loads(r["produced_mana"] or "[]")
        for color in COLORS:
            if color in produced:
                (land_sources if is_land else other_sources)[color] += qty

        if is_land:
            lands += qty
        else:
            mv = r["cmc"] or 0
            mv_sum += mv * qty
            bucket = "7+" if mv >= 7 else str(int(mv))
            colors = json.loads(r["colors"] or "[]")
            group = colors[0] if len(colors) == 1 else ("M" if colors else "C")
            curve[bucket][group] += qty
            for color, count in _pips(_castable_cost(r["layout"], r["mana_cost"])).items():
                pips[color] += count * qty

        prices = json.loads(r["prices"] or "{}")
        card_eur, card_usd = _price(prices, "eur"), _price(prices, "usd")
        if card_eur is None and card_usd is None:
            unpriced += qty
        eur += (card_eur or 0) * qty
        usd += (card_usd or 0) * qty
        needed[r["oracle_id"]] += qty
        owned[r["oracle_id"]] = r["owned"]
        if not ("Basic" in front and is_land):
            wildcards[r["arena_rarity"] or r["rarity"] or "common"] += qty

    # Missing cost: copies the collection lacks, priced like the deck's printings.
    if platform == "paper":
        for r in rows:
            short = max(0, needed[r["oracle_id"]] - owned[r["oracle_id"]])
            if not short:
                continue
            take = min(short, r["quantity"])
            needed[r["oracle_id"]] -= take
            prices = json.loads(r["prices"] or "{}")
            missing_eur += (_price(prices, "eur") or 0) * take
            missing_usd += (_price(prices, "usd") or 0) * take

    nonlands = total - lands
    return DeckStats(
        total=total,
        lands=lands,
        nonlands=nonlands,
        average_mv=round(mv_sum / nonlands, 2) if nonlands else None,
        curve=[
            CurveBucket(mv=b, total=sum(curve[b].values()), by_color={k: curve[b][k] for k in [*COLORS, "M", "C"]})
            for b in MV_BUCKETS
        ],
        types={t: types[t] for t in CARD_TYPES},
        primary_types=dict(primary),
        rarity={r: rarity[r] for r in RARITIES if rarity[r]},
        colors=[
            ColorBalance(color=c, pips=pips[c], land_sources=land_sources[c], other_sources=other_sources[c])
            for c in COLORS
        ],
        categories=dict(categories),
        price=Price(
            eur=round(eur, 2), usd=round(usd, 2),
            missing_eur=round(missing_eur, 2), missing_usd=round(missing_usd, 2),
            unpriced=unpriced, as_of=get_meta(conn, META_UPDATED_AT),
        ),
        wildcards={r: wildcards[r] for r in ("common", "uncommon", "rare", "mythic") if wildcards[r]},
    )


def _castable_cost(layout: str | None, mana_cost: str | None) -> str:
    """Front face only, except split cards whose halves are both castable from hand."""
    if not mana_cost:
        return ""
    return mana_cost if layout == "split" else mana_cost.split(" // ")[0]


def _pips(cost: str) -> Counter[str]:
    """{2}{W}{W} -> W:2; hybrid {W/U} counts for both colors, Phyrexian {W/P} for its color."""
    counts: Counter[str] = Counter()
    for symbol in _SYMBOL_RE.findall(cost):
        for part in symbol.split("/"):
            if part in COLORS:
                counts[part] += 1
    return counts


def _price(prices: dict, currency: str) -> float | None:
    value = prices.get(currency) or prices.get(f"{currency}_foil")
    try:
        return float(value) if value else None
    except ValueError:
        return None
