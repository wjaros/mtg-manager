import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.cards.models import CardSummary
from mtgdm.purchase import opener
from mtgdm.purchase.basket import Terms, optimise
from mtgdm.purchase.settings import PurchaseSettings
from mtgdm.purchase.shopping import Offer, ShoppingRow
from mtgdm.purchase.sources import InvalidTemplate, build_search_url
from tests.test_wants import card_id, make_deck

ALLEGRO = "https://allegro.pl/listing?string={query}"
BOLT = "Lightning Bolt"
SOL_RING = "Sol Ring"
SERRA = "Serra Angel"
SWORDS = "Swords to Plowshares"
GIADA = "Giada, Font of Hope"


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


# --- building the URL --------------------------------------------------------------------------


def test_build_search_url():
    assert build_search_url(ALLEGRO, SOL_RING) == "https://allegro.pl/listing?string=Sol+Ring"
    assert build_search_url(ALLEGRO, SOL_RING, suffix=" mtg") == "https://allegro.pl/listing?string=Sol+Ring+mtg"
    assert build_search_url(ALLEGRO, SOL_RING, set_name="Commander Masters", mode="name_set") == \
        "https://allegro.pl/listing?string=Sol+Ring+Commander+Masters"
    # name mode leaves the set out
    assert build_search_url(ALLEGRO, SOL_RING, set_name="Commander Masters") == \
        "https://allegro.pl/listing?string=Sol+Ring"
    # a double-faced card by its front face; a split card by its full name
    assert build_search_url(ALLEGRO, "Delver of Secrets // Insectile Aberration", "transform") == \
        "https://allegro.pl/listing?string=Delver+of+Secrets"
    assert build_search_url(ALLEGRO, "Fire // Ice", "split") == "https://allegro.pl/listing?string=Fire+%2F%2F+Ice"
    assert build_search_url(ALLEGRO, "Ajani's Pridemate") == "https://allegro.pl/listing?string=Ajani%27s+Pridemate"
    assert build_search_url(ALLEGRO, GIADA) == "https://allegro.pl/listing?string=Giada%2C+Font+of+Hope"
    assert build_search_url(ALLEGRO, "Żółć", suffix=" karta") == \
        "https://allegro.pl/listing?string=%C5%BB%C3%B3%C5%82%C4%87+karta"
    # {query} anywhere in the address, e.g. a shop's path
    assert build_search_url("https://shop.example.pl/szukaj/{query}/mtg", SOL_RING) == \
        "https://shop.example.pl/szukaj/Sol+Ring/mtg"


@pytest.mark.parametrize("template, key", [
    ("https://allegro.pl/listing?string=Sol", "template_placeholder"),
    ("http://allegro.pl/listing?string={query}", "template_https"),
    ("javascript:alert({query})", "template_https"),
    ("https:///{query}", "template_https"),
])
def test_bad_templates(template, key):
    with pytest.raises(InvalidTemplate) as exc:
        build_search_url(template, SOL_RING)
    assert exc.value.key == key


# --- sources -------------------------------------------------------------------------------------


def test_default_allegro_source(client):
    sources = client.get("/api/purchase-sources").json()
    assert [(s["name"], s["url_template"], s["enabled"], s["query_suffix"]) for s in sources] == [
        ("Allegro", ALLEGRO, True, " mtg")]
    allegro = sources[0]["id"]
    test = client.get(f"/api/purchase-sources/{allegro}/test").json()
    assert test["url"] == "https://allegro.pl/listing?string=Sol+Ring+mtg"

    bolt = card_id(client, BOLT)
    assert client.get(f"/api/cards/{bolt}/purchase-links").json() == [
        {"source_id": allegro, "name": "Allegro", "url": "https://allegro.pl/listing?string=Lightning+Bolt+mtg"}]

    # Edited, then disabled: no links.
    edited = client.patch(f"/api/purchase-sources/{allegro}", json={"query_suffix": " karta mtg"}).json()
    assert edited["query_suffix"] == " karta mtg" and edited["name"] == "Allegro"
    client.patch(f"/api/purchase-sources/{allegro}", json={"enabled": False})
    assert client.get(f"/api/cards/{bolt}/purchase-links").json() == []
    assert client.get("/api/purchase-sources").json()[0]["enabled"] is False


def test_source_crud(client):
    bad = client.post("/api/purchase-sources", json={"name": "Shop", "url_template": "https://shop.pl/?q=x"},
                      headers={"Accept-Language": "en"})
    assert bad.status_code == 422 and "{query}" in bad.json()["detail"]
    shop = client.post("/api/purchase-sources", json={
        "name": "Sklep", "url_template": "https://shop.pl/search?q={query}", "query_mode": "name_set",
        "free_delivery_threshold": 100, "shipping_cost": 12.5,
    }).json()
    assert shop["sort_order"] == 1 and shop["query_mode"] == "name_set"
    bolt = client.get("/api/cards", params={"q": f'!"{BOLT}"'}).json()["items"][0]
    links = client.get(f"/api/cards/{bolt['id']}/purchase-links").json()
    assert [link["name"] for link in links] == ["Allegro", "Sklep"]
    assert links[1]["url"] == f"https://shop.pl/search?q=Lightning+Bolt+{bolt['set_name'].replace(' ', '+')}"
    # null clears an override
    assert client.patch(f"/api/purchase-sources/{shop['id']}", json={"shipping_cost": None}).json()["shipping_cost"] is None
    assert client.patch(f"/api/purchase-sources/{shop['id']}", json={"url_template": "ftp://x/{query}"}).status_code == 422
    assert client.delete(f"/api/purchase-sources/{shop['id']}").status_code == 204
    assert client.delete(f"/api/purchase-sources/{shop['id']}").status_code == 404
    assert client.get("/api/cards/nope/purchase-links").status_code == 404


def test_open_urls_only_in_the_window_app(client, monkeypatch):
    assert client.get("/api/prefs").json()["open_urls"] is False
    assert client.post("/api/open-urls", json={"urls": ["https://allegro.pl/"]}).status_code == 404

    opened = []
    monkeypatch.setattr(opener, "_enabled", True)
    monkeypatch.setattr(opener, "open_urls", lambda urls: opened.extend(urls))
    assert client.get("/api/prefs").json()["open_urls"] is True
    assert client.post("/api/open-urls", json={"urls": ["https://a.pl/1", "https://a.pl/2"]}).status_code == 204
    assert opened == ["https://a.pl/1", "https://a.pl/2"]
    assert client.post("/api/open-urls", json={"urls": ["file:///etc/passwd"]}).status_code == 422


def test_opener_opens_in_order_with_a_delay():
    opened, slept = [], []
    opener.open_urls(["a", "b", "c"], opener=opened.append, sleep=slept.append).join()
    assert opened == ["a", "b", "c"] and slept == [opener.TAB_DELAY] * 2


# --- the shopping list ---------------------------------------------------------------------------


def shop(client, deck: int) -> dict[str, dict]:
    return {r["name"]: r for r in client.get(f"/api/decks/{deck}/shopping-list").json()["rows"]}


def test_shopping_list(client):
    # One Sol Ring owned of two; Serra Angel proxied in the deck's box; Bolt not owned at all.
    client.post("/api/collection", json={"card_id": card_id(client, SOL_RING)})
    deck = make_deck(client, "Giada", [(GIADA, 1), (SOL_RING, 2), (SERRA, 1)])
    client.post("/api/collection", json={"card_id": card_id(client, GIADA)})
    assert client.post(f"/api/decks/{deck}/proxies", json={"card_id": card_id(client, SERRA)}).status_code == 201

    rows = shop(client, deck)
    assert {n: (r["qty"], r["reason"], r["done"]) for n, r in rows.items()} == {
        SOL_RING: (1, "missing", False), SERRA: (1, "proxy", False)}
    assert rows[SERRA]["links"][0]["url"] == "https://allegro.pl/listing?string=Serra+Angel+mtg"

    # Done is kept per deck.
    other = make_deck(client, "Other", [(SERRA, 1)])
    serra = rows[SERRA]["oracle_id"]
    assert client.patch(f"/api/decks/{deck}/shopping-list/{serra}", json={"done": True}).status_code == 200
    assert shop(client, deck)[SERRA]["done"] is True
    assert shop(client, other)[SERRA]["done"] is False
    client.patch(f"/api/decks/{deck}/shopping-list/{serra}", json={"done": False})
    assert shop(client, deck)[SERRA]["done"] is False
    client.patch(f"/api/decks/{deck}/shopping-list/{serra}", json={"done": True})
    reset = client.delete(f"/api/decks/{deck}/shopping-list/done").json()
    assert not any(r["done"] for r in reset["rows"])
    assert client.get("/api/decks/999/shopping-list").status_code == 404


# --- offers and the basket -----------------------------------------------------------------------


def offer(client, deck: int, oracle_id: str, seller: str, price: float, **extra) -> dict:
    resp = client.post(f"/api/decks/{deck}/offers", json={"oracle_id": oracle_id, "seller_name": seller,
                                                          "price": price, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture
def deck(client):
    """Four cards to buy, one copy each."""
    return make_deck(client, "Giada", [(BOLT, 1), (SOL_RING, 1), (SERRA, 1), (SWORDS, 1)])


def oracle_ids(client, deck: int) -> dict[str, str]:
    return {n: r["oracle_id"] for n, r in shop(client, deck).items()}


def test_offers_and_choices(client, deck):
    ids = oracle_ids(client, deck)
    a = offer(client, deck, ids[BOLT], "Seller A", 3.0, url="https://allegro.pl/oferta/1")
    b = offer(client, deck, ids[BOLT], "  Seller   B ", 2.5)
    assert b["seller_name"] == "Seller B" and not a["chosen"]
    assert client.post(f"/api/decks/{deck}/offers", json={"oracle_id": ids[BOLT], "price": 1, "url": "ftp://x"}
                       ).status_code == 422  # no seller, and a bad link
    assert client.post(f"/api/decks/{deck}/offers", json={"oracle_id": ids[BOLT], "price": 1,
                                                          "seller_name": "A", "url": "javascript:x"}).status_code == 422
    # A source that is one seller names the offer.
    shop_source = client.post("/api/purchase-sources", json={"name": "Sklep X",
                                                             "url_template": "https://x.pl/?q={query}"}).json()
    assert offer(client, deck, ids[SERRA], "", 4.0, source_id=shop_source["id"])["seller_name"] == "Sklep X"
    assert "Sklep X" in client.get(f"/api/decks/{deck}/shopping-list").json()["sellers"]

    # Cheapest per card, then a choice moved by hand: one chosen per card.
    basket = client.post(f"/api/decks/{deck}/choices/cheapest").json()
    assert {s["seller"]: [c["name"] for c in s["cards"]] for s in basket["sellers"]} == {
        "Seller B": [BOLT], "Sklep X": [SERRA]}
    basket = client.put(f"/api/decks/{deck}/choices", json={"choices": {ids[BOLT]: a["id"]}}).json()
    assert [s["seller"] for s in basket["sellers"]] == ["Seller A", "Sklep X"]
    assert sum(o["chosen"] for o in shop(client, deck)[BOLT]["offers"]) == 1
    # Picking the cheapest for one card moves it back.
    client.post(f"/api/decks/{deck}/choices/cheapest", params={"oracle_id": ids[BOLT]})
    assert [o["seller_name"] for o in shop(client, deck)[BOLT]["offers"] if o["chosen"]] == ["Seller B"]
    # An offer edited, then deleted.
    assert client.patch(f"/api/offers/{a['id']}", json={"price": 1.0}).json()["price"] == 1.0
    assert client.delete(f"/api/offers/{a['id']}").status_code == 204
    assert client.delete(f"/api/offers/{a['id']}").status_code == 404
    assert client.put(f"/api/decks/{deck}/choices", json={"choices": {ids[BOLT]: a["id"]}}).status_code == 404


def test_seller_totals_and_thresholds(client, deck):
    ids = oracle_ids(client, deck)
    client.put("/api/purchase-settings", json={"free_delivery_threshold": 10, "default_shipping_cost": 9})
    offer(client, deck, ids[BOLT], "Seller A", 4.0, chosen=True)
    offer(client, deck, ids[SOL_RING], "Seller A", 3.0, chosen=True)
    offer(client, deck, ids[SERRA], "Seller B", 6.0, chosen=True)
    offer(client, deck, ids[SERRA], "Seller A", 6.5)
    basket = client.get(f"/api/decks/{deck}/basket").json()
    sellers = {s["seller"]: s for s in basket["sellers"]}
    a, b = sellers["Seller A"], sellers["Seller B"]
    assert (b["subtotal"], b["reached"], b["suggestions"]) == (6.0, False, [])
    assert (a["subtotal"], a["threshold"], a["missing"], a["reached"], a["shipping"]) == (7.0, 10, 3.0, False, 9)
    # Seller A also offers Serra Angel: +0.50 vs Seller B.
    assert [(s["name"], s["price"], s["current_seller"], s["diff"]) for s in a["suggestions"]] == [
        (SERRA, 6.5, "Seller B", 0.5)]
    assert basket["unassigned"] == [{"oracle_id": ids[SWORDS], "name": SWORDS, "qty": 1, "offers": 0}]
    assert basket["summary"] == {"cards": 13.0, "shipping": 18.0, "shipping_unknown": 0, "parcels": 2, "total": 31.0}

    # Following the suggestion: Seller A reaches the threshold, Seller B is gone.
    basket = client.put(f"/api/decks/{deck}/choices",
                        json={"choices": {ids[SERRA]: a["suggestions"][0]["offer_id"]}}).json()
    assert [(s["seller"], s["subtotal"], s["reached"], s["shipping"]) for s in basket["sellers"]] == [
        ("Seller A", 13.5, True, 0.0)]
    assert basket["summary"]["total"] == 13.5

    # A seller's own threshold (a source of the same name) overrides the global one.
    client.post("/api/purchase-sources", json={"name": "seller a", "url_template": "https://a.pl/?q={query}",
                                               "free_delivery_threshold": 20, "shipping_cost": 5})
    a = client.get(f"/api/decks/{deck}/basket").json()["sellers"][0]
    assert (a["threshold"], a["missing"], a["shipping"]) == (20, 6.5, 5)

    # Done cards leave the basket.
    client.patch(f"/api/decks/{deck}/shopping-list/{ids[BOLT]}", json={"done": True})
    names = [c["name"] for c in client.get(f"/api/decks/{deck}/basket").json()["sellers"][0]["cards"]]
    assert BOLT not in names


def _offer(oracle_id: str, seller: str, price: float, offer_id: int) -> Offer:
    return Offer(id=offer_id, oracle_id=oracle_id, source_id=None, seller_name=seller, price=price,
                 qty_available=None, url=None, note=None, chosen=False)


def test_optimise_moves_cards_to_reach_a_threshold():
    """Seller A is cheapest for 4 cards (40), B for two (8 + 8): B pays shipping (16 < 30). Moving both to
    A (+1 each) brings A to 58 and saves B's shipping (10); moving just one doesn't."""
    offers = {
        "a1": [_offer("a1", "A", 10, 1)], "a2": [_offer("a2", "A", 10, 2)],
        "a3": [_offer("a3", "A", 10, 3)], "a4": [_offer("a4", "A", 10, 4)],
        "b1": [_offer("b1", "B", 8, 5), _offer("b1", "A", 9, 6)],
        "b2": [_offer("b2", "B", 8, 7), _offer("b2", "A", 9, 8)],
        "solo": [_offer("solo", "C", 1, 9)],  # one offer only: stays put
    }
    rows = [_row(k, v) for k, v in offers.items()]
    terms = Terms(PurchaseSettings(free_delivery_threshold=50, default_shipping_cost=10), [])
    choice = optimise(rows, terms)
    assert {k: o.seller_name for k, o in choice.items()} == {
        "a1": "A", "a2": "A", "a3": "A", "a4": "A", "b1": "A", "b2": "A", "solo": "C"}

    # With cheap shipping it isn't worth it.
    terms = Terms(PurchaseSettings(free_delivery_threshold=50, default_shipping_cost=1), [])
    assert {k: o.seller_name for k, o in optimise(rows, terms).items()}["b1"] == "B"


def _row(oracle_id: str, offers: list[Offer]):
    card = CardSummary(id=oracle_id, oracle_id=oracle_id, name=oracle_id, printed_name=None, lang="en", layout="normal",
                       mana_cost=None, cmc=0, type_line=None, rarity=None, set_code="x", set_name="X",
                       collector_number="1", released_at=None, colors=[], color_identity=[], games=[], artist=None,
                       image_faces=1, owned=0, owned_printing=0)
    return ShoppingRow(oracle_id=oracle_id, name=oracle_id, card=card, qty=1, proxied=0, reason="missing", done=False,
                       links=[], offers=offers, price_eur=None)


def test_proposal_keeps_choices_until_accepted(client, deck):
    ids = oracle_ids(client, deck)
    client.put("/api/purchase-settings", json={"free_delivery_threshold": 20, "default_shipping_cost": 10})
    for name in (BOLT, SOL_RING, SERRA):
        offer(client, deck, ids[name], "A", 6.0)
    offer(client, deck, ids[SWORDS], "A", 5.0)
    swords_b = offer(client, deck, ids[SWORDS], "B", 4.0, chosen=True)
    proposal = client.get(f"/api/decks/{deck}/basket/proposal").json()
    assert proposal["proposed"]["total"] == 23.0 and proposal["proposed"]["parcels"] == 1
    assert proposal["current"] == {"cards": 4.0, "shipping": 10.0, "shipping_unknown": 0, "parcels": 1,
                                   "total": 14.0}  # only the chosen card counts so far
    assert [(c["name"], c["from_seller"], c["to_seller"]) for c in proposal["changes"]] == sorted(
        [(BOLT, None, "A"), (SOL_RING, None, "A"), (SERRA, None, "A"), (SWORDS, "B", "A")])
    # Not applied until accepted.
    assert [o["id"] for o in shop(client, deck)[SWORDS]["offers"] if o["chosen"]] == [swords_b["id"]]
    basket = client.put(f"/api/decks/{deck}/choices", json={"choices": proposal["choices"]}).json()
    assert basket["summary"]["total"] == 23.0


def test_shopping_survives_a_backup(client, deck):
    ids = oracle_ids(client, deck)
    client.put("/api/purchase-settings", json={"free_delivery_threshold": 60, "currency": "pln"})
    source = client.post("/api/purchase-sources", json={"name": "Sklep", "url_template": "https://s.pl/?q={query}",
                                                        "shipping_cost": 7}).json()
    offer(client, deck, ids[BOLT], "", 2.0, source_id=source["id"], chosen=True, url="https://s.pl/bolt")
    client.patch(f"/api/decks/{deck}/shopping-list/{ids[SERRA]}", json={"done": True})
    backup = client.get("/api/backup/export").json()
    assert backup["purchase_settings"]["currency"] == "PLN"

    assert client.post("/api/backup/import", params={"replace": True}, json=backup).status_code == 200
    restored = client.get("/api/decks").json()[0]["id"]
    rows = shop(client, restored)
    assert rows[SERRA]["done"] is True
    [bolt] = rows[BOLT]["offers"]
    sources = {s["name"]: s for s in client.get("/api/purchase-sources").json()}
    assert set(sources) == {"Allegro", "Sklep"} and sources["Sklep"]["shipping_cost"] == 7
    assert (bolt["seller_name"], bolt["chosen"], bolt["source_id"], bolt["url"]) == (
        "Sklep", True, sources["Sklep"]["id"], "https://s.pl/bolt")
    assert client.get("/api/purchase-settings").json()["free_delivery_threshold"] == 60

    # Added (not replacing): the default Allegro source isn't doubled.
    client.post("/api/backup/import", json=backup)
    assert [s["name"] for s in client.get("/api/purchase-sources").json()] == ["Allegro", "Sklep"]
