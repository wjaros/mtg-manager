"""Settings › Where to buy: the free-delivery threshold per seller (Allegro Smart!: 49.90 PLN since
2 March 2026; it changes over time), the currency prices are typed in, shipping below the threshold, and
for the comparison with CardTrader Zero its shipping fee and exchange rates typed in by hand (no rate API:
a few groszy don't change where it's cheaper). Kept in meta, in the backup."""

import json
import sqlite3

from pydantic import BaseModel, Field

from mtgdm.scryfall.bulk import get_meta, set_meta

KEY = "purchase_settings"


class PurchaseSettings(BaseModel):
    free_delivery_threshold: float = Field(default=49.90, ge=0)
    currency: str = Field(default="PLN", min_length=1, max_length=8)
    default_shipping_cost: float | None = Field(default=None, ge=0)  # below the threshold; None: unknown
    cardtrader_shipping: float = Field(default=18.0, ge=0)  # one CardTrader Zero parcel
    cardtrader_shipping_currency: str = Field(default="USD", min_length=1, max_length=8)
    # Units of `currency` per unit of another currency ({"EUR": 4.25, "USD": 3.9}), typed in by hand.
    rates: dict[str, float] = {}


def get_settings(conn: sqlite3.Connection) -> PurchaseSettings:
    raw = get_meta(conn, KEY)
    if not raw:
        return PurchaseSettings()
    try:
        return PurchaseSettings.model_validate(json.loads(raw))
    except ValueError:
        return PurchaseSettings()


def save_settings(conn: sqlite3.Connection, settings: PurchaseSettings) -> PurchaseSettings:
    with conn:
        return store_settings(conn, settings)


def store_settings(conn: sqlite3.Connection, settings: PurchaseSettings) -> PurchaseSettings:
    """No transaction of its own."""
    settings = settings.model_copy(update={
        "currency": settings.currency.strip().upper(),
        "cardtrader_shipping_currency": settings.cardtrader_shipping_currency.strip().upper(),
        "rates": {k.strip().upper(): v for k, v in settings.rates.items() if k.strip() and v > 0},
    })
    set_meta(conn, KEY, settings.model_dump_json())
    return settings


def convert(amount: float, currency: str | None, settings: PurchaseSettings) -> float | None:
    """An amount in the settings' currency; None when its rate isn't set."""
    if currency is None or currency.upper() == settings.currency:
        return amount
    rate = settings.rates.get(currency.upper())
    return amount * rate if rate else None
