"""The basket planner: a deck's chosen offers grouped per seller, each with its progress to free delivery
(Allegro Smart!: a minimum order per single seller), suggestions to fill a seller up, a proposed basket
that minimises cards + shipping, and a comparison with CardTrader Zero (one parcel, one fee).

A seller's threshold and shipping cost: a purchase source of the same name (a source that is one seller),
else the source the offer came from (a marketplace's own rules), else the global settings."""

import json
import sqlite3
from dataclasses import dataclass

from pydantic import BaseModel

from mtgdm.purchase.settings import PurchaseSettings, convert
from mtgdm.purchase.shopping import Offer, ShoppingList, ShoppingRow, seller_key, shopping_list, usable
from mtgdm.purchase.sources import PurchaseSource, list_sources

EPSILON = 1e-6
MAX_ROUNDS = 200


class BasketCard(BaseModel):
    oracle_id: str
    name: str
    qty: int
    offer_id: int
    unit_price: float
    price: float  # qty × unit price
    url: str | None
    short: bool   # the seller has fewer copies than needed


class Suggestion(BaseModel):
    """A card still needed that this seller offers too: moving it here helps reach the threshold."""
    oracle_id: str
    name: str
    qty: int
    offer_id: int
    price: float                  # here, for qty copies
    current_price: float | None   # where it's chosen now (None: not chosen yet)
    current_seller: str | None
    diff: float | None            # price - current_price


class SellerBasket(BaseModel):
    seller: str
    cards: list[BasketCard]
    subtotal: float
    threshold: float
    missing: float        # to the threshold (0 when reached)
    reached: bool
    shipping: float | None  # 0 when reached; None: unknown
    suggestions: list[Suggestion]


class Unassigned(BaseModel):
    oracle_id: str
    name: str
    qty: int
    offers: int  # offers noted for the card (none chosen)


class Totals(BaseModel):
    cards: float
    shipping: float
    shipping_unknown: int  # parcels whose shipping cost isn't known (not in shipping)
    parcels: int
    total: float


class Basket(BaseModel):
    currency: str
    sellers: list[SellerBasket]  # with chosen cards, by name
    unassigned: list[Unassigned]  # cards still to buy without a chosen offer
    summary: Totals


class ChoiceChange(BaseModel):
    oracle_id: str
    name: str
    offer_id: int
    from_seller: str | None
    to_seller: str
    price: float  # for qty copies, at to_seller


class BasketProposal(BaseModel):
    choices: dict[str, int]  # oracle id -> offer id, for every card with an offer
    changes: list[ChoiceChange]
    current: Totals  # the chosen offers as they are (cards without one left out)
    proposed: Totals


@dataclass(frozen=True)
class SellerTerms:
    threshold: float
    shipping: float | None


class Terms:
    def __init__(self, settings: PurchaseSettings, sources: list[PurchaseSource]):
        self.settings = settings
        self.by_id = {s.id: s for s in sources}
        self.by_name = {seller_key(s.name): s for s in sources}

    def of(self, seller: str, offers: list[Offer]) -> SellerTerms:
        threshold, shipping = None, None
        for source in [self.by_name.get(seller_key(seller))] + [self.by_id.get(o.source_id) for o in offers
                                                                   if o.source_id is not None]:
            if source is None:
                continue
            threshold = threshold if threshold is not None else source.free_delivery_threshold
            shipping = shipping if shipping is not None else source.shipping_cost
        return SellerTerms(
            threshold=threshold if threshold is not None else self.settings.free_delivery_threshold,
            shipping=shipping if shipping is not None else self.settings.default_shipping_cost,
        )


def _pending(shopping: ShoppingList) -> list[ShoppingRow]:
    return [r for r in shopping.rows if not r.done]


def _totals(assigned: dict[str, tuple[ShoppingRow, Offer]], terms: Terms) -> Totals:
    by_seller: dict[str, list[tuple[ShoppingRow, Offer]]] = {}
    for row, offer in assigned.values():
        by_seller.setdefault(seller_key(offer.seller_name), []).append((row, offer))
    cards = shipping = 0.0
    unknown = 0
    for items in by_seller.values():
        subtotal = sum(o.price * r.qty for r, o in items)
        cards += subtotal
        seller_terms = terms.of(items[0][1].seller_name, [o for _, o in items])
        if subtotal + EPSILON < seller_terms.threshold:
            if seller_terms.shipping is None:
                unknown += 1
            else:
                shipping += seller_terms.shipping
    return Totals(cards=round(cards, 2), shipping=round(shipping, 2), shipping_unknown=unknown,
                  parcels=len(by_seller), total=round(cards + shipping, 2))


def basket(conn: sqlite3.Connection, deck_id: int) -> Basket:
    shopping = shopping_list(conn, deck_id)
    terms = Terms(shopping.settings, list_sources(conn))
    rows = _pending(shopping)
    chosen = {r.oracle_id: (r, o) for r in rows for o in r.offers if o.chosen}

    by_seller: dict[str, list[tuple[ShoppingRow, Offer]]] = {}
    for row, offer in chosen.values():
        by_seller.setdefault(seller_key(offer.seller_name), []).append((row, offer))

    sellers = []
    for key, items in by_seller.items():
        name = items[0][1].seller_name
        seller_terms = terms.of(name, [o for _, o in items])
        subtotal = round(sum(o.price * r.qty for r, o in items), 2)
        reached = subtotal + EPSILON >= seller_terms.threshold
        suggestions = []
        if not reached:
            for row in rows:
                here = [o for o in row.offers if seller_key(o.seller_name) == key and usable(o, row.qty)]
                current = chosen.get(row.oracle_id)
                if not here or (current and seller_key(current[1].seller_name) == key):
                    continue
                best = min(here, key=lambda o: o.price)
                price = round(best.price * row.qty, 2)
                current_price = round(current[1].price * row.qty, 2) if current else None
                suggestions.append(Suggestion(
                    oracle_id=row.oracle_id, name=row.name, qty=row.qty, offer_id=best.id, price=price,
                    current_price=current_price, current_seller=current[1].seller_name if current else None,
                    diff=round(price - current_price, 2) if current_price is not None else None,
                ))
            suggestions.sort(key=lambda s: (s.diff is not None, s.diff if s.diff is not None else s.price))
        sellers.append(SellerBasket(
            seller=name,
            cards=sorted((BasketCard(oracle_id=r.oracle_id, name=r.name, qty=r.qty, offer_id=o.id, unit_price=o.price,
                                     price=round(o.price * r.qty, 2), url=o.url, short=not usable(o, r.qty))
                          for r, o in items), key=lambda c: c.name.lower()),
            subtotal=subtotal, threshold=seller_terms.threshold,
            missing=0.0 if reached else round(seller_terms.threshold - subtotal, 2), reached=reached,
            shipping=0.0 if reached else seller_terms.shipping, suggestions=suggestions,
        ))
    sellers.sort(key=lambda s: s.seller.casefold())
    unassigned = [Unassigned(oracle_id=r.oracle_id, name=r.name, qty=r.qty, offers=len(r.offers))
                  for r in rows if r.oracle_id not in chosen]
    return Basket(currency=shopping.settings.currency, sellers=sellers, unassigned=unassigned,
                  summary=_totals(chosen, terms))


# --- the proposed basket -----------------------------------------------------------------------


def _cost(choice: dict[str, Offer], rows: dict[str, ShoppingRow], terms: Terms) -> float:
    """Cards + shipping of sellers below their threshold (unknown shipping counts 0: it can't be weighed)."""
    subtotals: dict[str, float] = {}
    offers_of: dict[str, list[Offer]] = {}
    for oracle_id, offer in choice.items():
        key = seller_key(offer.seller_name)
        subtotals[key] = subtotals.get(key, 0.0) + offer.price * rows[oracle_id].qty
        offers_of.setdefault(key, []).append(offer)
    total = 0.0
    for key, subtotal in subtotals.items():
        seller_terms = terms.of(offers_of[key][0].seller_name, offers_of[key])
        total += subtotal
        if subtotal + EPSILON < seller_terms.threshold:
            total += seller_terms.shipping or 0.0
    return total


def optimise(rows: list[ShoppingRow], terms: Terms) -> dict[str, Offer]:
    """One offer per card minimising cards + shipping: the cheapest per card first, then moves that lower
    the total: one card to another offer, filling a seller (its cheapest-to-move cards one by one), or
    emptying a seller (each of its cards to its next best offer elsewhere). Greedy, enough for dozens of
    cards and a few sellers."""
    options = {r.oracle_id: [o for o in r.offers if usable(o, r.qty)] for r in rows}
    options = {k: v for k, v in options.items() if v}
    by_id = {r.oracle_id: r for r in rows}
    choice = {k: min(v, key=lambda o: (o.price, not o.chosen)) for k, v in options.items()}
    cost = _cost(choice, by_id, terms)

    for _ in range(MAX_ROUNDS):
        best_cost, best_choice = cost, None
        for candidate in _moves(choice, options, by_id):
            c = _cost(candidate, by_id, terms)
            if c < best_cost - EPSILON:
                best_cost, best_choice = c, candidate
        if best_choice is None:
            break
        choice, cost = best_choice, best_cost
    return choice


def _moves(choice: dict[str, Offer], options: dict[str, list[Offer]], rows: dict[str, ShoppingRow]):
    for oracle_id, offers in options.items():
        for offer in offers:
            if offer.id != choice[oracle_id].id:
                yield {**choice, oracle_id: offer}
    sellers = {seller_key(o.seller_name) for offers in options.values() for o in offers}
    for seller in sellers:
        # Fill: the cards this seller offers but that are chosen elsewhere, cheapest extra cost first.
        extra = []
        for oracle_id, offers in options.items():
            if seller_key(choice[oracle_id].seller_name) == seller:
                continue
            here = [o for o in offers if seller_key(o.seller_name) == seller]
            if here:
                best = min(here, key=lambda o: o.price)
                extra.append(((best.price - choice[oracle_id].price) * rows[oracle_id].qty, oracle_id, best))
        extra.sort(key=lambda e: e[0])
        moved = dict(choice)
        for _, oracle_id, offer in extra:
            moved[oracle_id] = offer
            yield dict(moved)
        # Empty: every card of this seller to its cheapest offer elsewhere.
        emptied = dict(choice)
        for oracle_id, offer in choice.items():
            if seller_key(offer.seller_name) != seller:
                continue
            elsewhere = [o for o in options[oracle_id] if seller_key(o.seller_name) != seller]
            if not elsewhere:
                break
            emptied[oracle_id] = min(elsewhere, key=lambda o: o.price)
        else:
            if emptied != choice:
                yield emptied


def propose(conn: sqlite3.Connection, deck_id: int) -> BasketProposal:
    shopping = shopping_list(conn, deck_id)
    terms = Terms(shopping.settings, list_sources(conn))
    rows = _pending(shopping)
    by_id = {r.oracle_id: r for r in rows}
    current = {r.oracle_id: (r, o) for r in rows for o in r.offers if o.chosen}
    choice = optimise(rows, terms)
    changes = [
        ChoiceChange(oracle_id=k, name=by_id[k].name, offer_id=o.id,
                     from_seller=current[k][1].seller_name if k in current else None, to_seller=o.seller_name,
                     price=round(o.price * by_id[k].qty, 2))
        for k, o in choice.items() if k not in current or current[k][1].id != o.id
    ]
    changes.sort(key=lambda c: c.name.lower())
    return BasketProposal(
        choices={k: o.id for k, o in choice.items()}, changes=changes, current=_totals(current, terms),
        proposed=_totals({k: (by_id[k], o) for k, o in choice.items()}, terms),
    )


# --- CardTrader Zero side by side ------------------------------------------------------------


class CardTraderCard(BaseModel):
    oracle_id: str
    name: str
    qty: int
    copies: int          # copies the fetched offers have (up to qty)
    price: float | None  # for those copies, in the settings' currency; None: no rate for the currency
    cheaper: bool = False  # than the chosen offer (mixed option: goes to CardTrader)


class Option(BaseModel):
    cards: float
    shipping: float
    shipping_unknown: int
    parcels: int
    total: float
    complete: bool  # every card still to buy is covered


class Comparison(BaseModel):
    currency: str
    fetched_at: str | None       # of the CardTrader offers; None: never fetched for this deck
    rate_missing: list[str]      # currencies without an exchange rate in the settings
    cardtrader_cards: list[CardTraderCard]
    not_on_cardtrader: list[str]  # cards without (enough) CardTrader Zero offers
    sellers: Option               # the chosen offers (cards without one: not counted)
    cardtrader: Option | None     # everything CardTrader Zero has, one parcel
    mixed: Option | None          # cheaper cards to CardTrader, as long as no seller drops below its threshold
    to_cardtrader: list[str]      # oracle ids the mixed option sends to CardTrader


def comparison(conn: sqlite3.Connection, deck_id: int) -> Comparison:
    shopping = shopping_list(conn, deck_id)
    settings = shopping.settings
    terms = Terms(settings, list_sources(conn))
    rows = _pending(shopping)
    quotes = {r["oracle_id"]: r for r in conn.execute(
        "SELECT oracle_id, offers, currency, fetched_at FROM cardtrader_quotes WHERE deck_id = ?", (deck_id,))}
    fetched_at = max((q["fetched_at"] for q in quotes.values()), default=None)
    rate_missing: set[str] = set()

    ct: dict[str, CardTraderCard] = {}
    not_found = []
    for row in rows:
        quote = quotes.get(row.oracle_id)
        offers = json.loads(quote["offers"]) if quote else []
        copies = sum(o["quantity"] for o in offers)
        if quote is None or copies < row.qty:
            not_found.append(row.name)
            continue
        left, cents = row.qty, 0
        for o in offers:
            take = min(left, o["quantity"])
            cents += take * o["price_cents"]
            left -= take
        price = convert(cents / 100, quote["currency"], settings)
        if price is None:
            rate_missing.add(quote["currency"])
        ct[row.oracle_id] = CardTraderCard(oracle_id=row.oracle_id, name=row.name, qty=row.qty, copies=row.qty,
                                           price=round(price, 2) if price is not None else None)
    ct_shipping = convert(settings.cardtrader_shipping, settings.cardtrader_shipping_currency, settings)
    if ct_shipping is None:
        rate_missing.add(settings.cardtrader_shipping_currency)

    chosen = {r.oracle_id: (r, o) for r in rows for o in r.offers if o.chosen}
    sellers_totals = _totals(chosen, terms)
    sellers_option = Option(**sellers_totals.model_dump(), complete=len(chosen) == len(rows))

    if not quotes or rate_missing:
        return Comparison(currency=settings.currency, fetched_at=fetched_at, rate_missing=sorted(rate_missing),
                          cardtrader_cards=sorted(ct.values(), key=lambda c: c.name.lower()),
                          not_on_cardtrader=not_found, sellers=sellers_option, cardtrader=None, mixed=None,
                          to_cardtrader=[])
    assert ct_shipping is not None
    ct_cards = round(sum(c.price or 0 for c in ct.values()), 2)
    cardtrader_option = Option(cards=ct_cards, shipping=ct_shipping if ct else 0.0, shipping_unknown=0,
                               parcels=1 if ct else 0, total=round(ct_cards + (ct_shipping if ct else 0.0), 2),
                               complete=not not_found)

    # Mixed: cards without a chosen offer go to CardTrader when it has them; a chosen card goes there when
    # cheaper, biggest saving first, unless that drops its seller below the free-delivery threshold.
    to_ct = {k for k in ct if k not in chosen}
    keep = dict(chosen)
    subtotal: dict[str, float] = {}
    for row, offer in chosen.values():
        key = seller_key(offer.seller_name)
        subtotal[key] = subtotal.get(key, 0.0) + offer.price * row.qty
    savings = sorted(
        ((offer.price * row.qty - ct[k].price, k) for k, (row, offer) in chosen.items()
         if k in ct and ct[k].price is not None and ct[k].price < offer.price * row.qty - EPSILON),
        reverse=True,
    )
    for _, k in savings:
        row, offer = keep[k]
        key = seller_key(offer.seller_name)
        seller_terms = terms.of(offer.seller_name, [o for r, o in keep.values() if seller_key(o.seller_name) == key])
        line = offer.price * row.qty
        below_already = subtotal[key] + EPSILON < seller_terms.threshold
        if below_already or subtotal[key] - line + EPSILON >= seller_terms.threshold:
            subtotal[key] -= line
            del keep[k]
            to_ct.add(k)
            ct[k].cheaper = True
    rest = _totals(keep, terms)
    ct_part = round(sum(ct[k].price or 0 for k in to_ct), 2)
    ct_ship = ct_shipping if to_ct else 0.0
    mixed = Option(cards=round(rest.cards + ct_part, 2), shipping=round(rest.shipping + ct_ship, 2),
                   shipping_unknown=rest.shipping_unknown, parcels=rest.parcels + (1 if to_ct else 0),
                   total=round(rest.total + ct_part + ct_ship, 2), complete=len(keep) + len(to_ct) == len(rows))
    return Comparison(currency=settings.currency, fetched_at=fetched_at, rate_missing=[],
                      cardtrader_cards=sorted(ct.values(), key=lambda c: c.name.lower()), not_on_cardtrader=not_found,
                      sellers=sellers_option, cardtrader=cardtrader_option, mixed=mixed, to_cardtrader=sorted(to_ct))
