-- Where to buy: search links per card (no API, no scraping: the browser opens a search) and a planner
-- of baskets per seller from offers the user notes down by hand.

-- A search on a marketplace or a seller's shop: url_template is https and holds {query}, filled with the
-- card's name (name_set: and its set's name) plus query_suffix. free_delivery_threshold / shipping_cost
-- override the global settings for this seller (NULL: the global ones).
CREATE TABLE purchase_sources (
    id                      INTEGER PRIMARY KEY,
    name                    TEXT NOT NULL,
    url_template            TEXT NOT NULL,
    enabled                 INTEGER NOT NULL DEFAULT 1,
    sort_order              INTEGER NOT NULL DEFAULT 0,
    query_mode              TEXT NOT NULL DEFAULT 'name' CHECK (query_mode IN ('name', 'name_set')),
    query_suffix            TEXT NOT NULL DEFAULT '',
    note                    TEXT,
    free_delivery_threshold REAL,
    shipping_cost           REAL
);
INSERT INTO purchase_sources(name, url_template, sort_order, query_suffix)
VALUES ('Allegro', 'https://allegro.pl/listing?string={query}', 0, ' mtg');

-- A deck's shopping list: cards ticked as bought or ordered (by oracle id).
CREATE TABLE shopping_done (
    deck_id   INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    oracle_id TEXT NOT NULL,
    PRIMARY KEY (deck_id, oracle_id)
) WITHOUT ROWID;

-- Offers seen at sellers, noted down per deck and card; at most one chosen per card.
CREATE TABLE offer_notes (
    id            INTEGER PRIMARY KEY,
    deck_id       INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    oracle_id     TEXT NOT NULL,
    source_id     INTEGER REFERENCES purchase_sources(id) ON DELETE SET NULL,
    seller_name   TEXT NOT NULL,
    price         REAL NOT NULL CHECK (price >= 0),
    qty_available INTEGER CHECK (qty_available IS NULL OR qty_available >= 0),
    url           TEXT,
    note          TEXT,
    chosen        INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_offer_notes_deck ON offer_notes(deck_id, oracle_id);
CREATE UNIQUE INDEX idx_offer_notes_chosen ON offer_notes(deck_id, oracle_id) WHERE chosen = 1;

-- The cheapest CardTrader Zero offers for each card of a deck's shopping list, as last fetched (not in
-- backups): offers = JSON [{product_id, blueprint_id, quantity, price_cents, seller, set_code}], cheapest
-- first, enough for the copies needed when there are; currency of their prices.
CREATE TABLE cardtrader_quotes (
    deck_id    INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    oracle_id  TEXT NOT NULL,
    offers     TEXT NOT NULL DEFAULT '[]',
    currency   TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (deck_id, oracle_id)
) WITHOUT ROWID;
