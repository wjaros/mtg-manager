-- Initial schema. JSON columns hold JSON text.

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE sets (
    code        TEXT PRIMARY KEY,
    arena_code  TEXT,
    mtgo_code   TEXT,
    name        TEXT NOT NULL,
    set_type    TEXT,
    released_at TEXT,
    digital     INTEGER NOT NULL DEFAULT 0,
    icon_path   TEXT
);
CREATE INDEX idx_sets_arena_code ON sets(arena_code);

-- One row per Scryfall printing (default_cards bulk).
CREATE TABLE cards (
    id               TEXT PRIMARY KEY,
    oracle_id        TEXT,
    name             TEXT NOT NULL,
    lang             TEXT NOT NULL DEFAULT 'en',
    layout           TEXT,
    mana_cost        TEXT,
    cmc              REAL,
    type_line        TEXT,
    oracle_text      TEXT,
    colors           TEXT,
    color_identity   TEXT,
    keywords         TEXT,
    legalities       TEXT,
    games            TEXT,
    arena_id         INTEGER,
    set_code         TEXT REFERENCES sets(code),
    collector_number TEXT,
    rarity           TEXT,
    finishes         TEXT,
    digital          INTEGER NOT NULL DEFAULT 0,
    released_at      TEXT,
    produced_mana    TEXT,
    prices           TEXT,
    image_uris       TEXT,
    card_faces       TEXT,
    printed_name     TEXT,
    raw              TEXT,
    updated_at       TEXT
);
CREATE INDEX idx_cards_oracle_id ON cards(oracle_id);
CREATE INDEX idx_cards_set_number ON cards(set_code, collector_number);
CREATE INDEX idx_cards_arena_id ON cards(arena_id);
CREATE INDEX idx_cards_name ON cards(name);

-- External-content FTS index kept in sync with cards by triggers.
CREATE VIRTUAL TABLE cards_fts USING fts5(
    name, type_line, oracle_text,
    content = 'cards', content_rowid = 'rowid',
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER cards_fts_ai AFTER INSERT ON cards BEGIN
    INSERT INTO cards_fts(rowid, name, type_line, oracle_text)
    VALUES (new.rowid, new.name, new.type_line, new.oracle_text);
END;

CREATE TRIGGER cards_fts_ad AFTER DELETE ON cards BEGIN
    INSERT INTO cards_fts(cards_fts, rowid, name, type_line, oracle_text)
    VALUES ('delete', old.rowid, old.name, old.type_line, old.oracle_text);
END;

CREATE TRIGGER cards_fts_au AFTER UPDATE ON cards BEGIN
    INSERT INTO cards_fts(cards_fts, rowid, name, type_line, oracle_text)
    VALUES ('delete', old.rowid, old.name, old.type_line, old.oracle_text);
    INSERT INTO cards_fts(rowid, name, type_line, oracle_text)
    VALUES (new.rowid, new.name, new.type_line, new.oracle_text);
END;

CREATE TABLE locations (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'other' CHECK (kind IN ('deck', 'binder', 'box', 'other'))
);

CREATE TABLE scans (
    id         INTEGER PRIMARY KEY,
    file_path  TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('single', 'page')),
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    status     TEXT NOT NULL DEFAULT 'pending'
);

CREATE TABLE scan_items (
    id             INTEGER PRIMARY KEY,
    scan_id        INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
    crop_path      TEXT,
    bbox           TEXT,
    ocr_name       TEXT,
    ocr_set        TEXT,
    ocr_number     TEXT,
    candidates     TEXT,
    chosen_card_id TEXT REFERENCES cards(id),
    confidence     REAL,
    status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected'))
);
CREATE INDEX idx_scan_items_scan_id ON scan_items(scan_id);

CREATE TABLE collection_items (
    id           INTEGER PRIMARY KEY,
    card_id      TEXT NOT NULL REFERENCES cards(id),
    quantity     INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    finish       TEXT NOT NULL DEFAULT 'nonfoil' CHECK (finish IN ('nonfoil', 'foil', 'etched')),
    language     TEXT NOT NULL DEFAULT 'en',
    condition    TEXT NOT NULL DEFAULT 'NM' CHECK (condition IN ('M', 'NM', 'EX', 'GD', 'LP', 'PL', 'PO')),
    location_id  INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    source       TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'scan', 'import')),
    scan_item_id INTEGER REFERENCES scan_items(id) ON DELETE SET NULL,
    note         TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_collection_items_card_id ON collection_items(card_id);
CREATE INDEX idx_collection_items_location_id ON collection_items(location_id);

CREATE TABLE decks (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    format            TEXT NOT NULL DEFAULT 'freeform'
                      CHECK (format IN ('brawl', 'standardbrawl', 'commander', 'historic', 'standard', 'freeform')),
    platform          TEXT NOT NULL DEFAULT 'paper' CHECK (platform IN ('paper', 'arena')),
    commander_card_id TEXT REFERENCES cards(id),
    partner_card_id   TEXT REFERENCES cards(id),
    companion_card_id TEXT REFERENCES cards(id),
    preferred_sets    TEXT,
    location_id       INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    description       TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE deck_cards (
    deck_id  INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    card_id  TEXT NOT NULL REFERENCES cards(id),
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    board    TEXT NOT NULL DEFAULT 'main' CHECK (board IN ('main', 'commander', 'companion', 'sideboard', 'maybe')),
    category TEXT,
    PRIMARY KEY (deck_id, card_id, board)
);
