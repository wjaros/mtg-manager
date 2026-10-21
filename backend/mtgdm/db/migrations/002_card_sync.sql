-- Columns needed to choose default printings and to credit artists next to images.
ALTER TABLE cards ADD COLUMN promo INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cards ADD COLUMN variation INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cards ADD COLUMN booster INTEGER NOT NULL DEFAULT 0;
ALTER TABLE cards ADD COLUMN border_color TEXT;
ALTER TABLE cards ADD COLUMN frame_effects TEXT;
ALTER TABLE cards ADD COLUMN artist TEXT;
-- 0 = no image, 1 = one image, 2+ = one image per face (transform / MDFC).
ALTER TABLE cards ADD COLUMN image_faces INTEGER NOT NULL DEFAULT 0;

-- Bulky per-printing data moved out of cards: search scans cards, and ~4 KB rows made every
-- full scan read ~0.5 GB. cards stays the narrow, filterable table.
CREATE TABLE card_details (
    id         TEXT PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE,
    image_uris TEXT,
    card_faces TEXT,
    prices     TEXT,
    raw        TEXT
);
ALTER TABLE cards DROP COLUMN image_uris;
ALTER TABLE cards DROP COLUMN card_faces;
ALTER TABLE cards DROP COLUMN prices;
ALTER TABLE cards DROP COLUMN raw;

CREATE INDEX idx_cards_updated_at ON cards(updated_at);

-- One row per oracle_id, rebuilt after every card sync (see mtgdm.scryfall.bulk).
CREATE TABLE oracle_cards (
    oracle_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    default_card_id TEXT NOT NULL,  -- newest regular paper printing
    arena_card_id   TEXT            -- newest printing available on Arena, if any
);
CREATE INDEX idx_oracle_cards_name ON oracle_cards(name);
