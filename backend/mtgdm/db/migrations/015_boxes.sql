-- Boxes of small decks (a Beginner Box's ten 20-card decks): a container in the decks list. Its decks
-- are ordinary decks with box_id set: box_role 'part' = one of the box's own decks, 'combined' = a deck
-- made from parts (a copy, edited on its own; box_parts = JSON list of the part deck ids it came from).
-- When owned, the box's cards sit in the box's location (kind 'box'); its decks have no location of
-- their own (a shared one would count its copies once per deck).
CREATE TABLE boxes (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    set_code    TEXT,                -- lower case, Scryfall style
    product_key TEXT,                -- the MTGJSON product it was imported from, e.g. tla-beginner-box
    location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

ALTER TABLE decks ADD COLUMN box_id INTEGER REFERENCES boxes(id) ON DELETE SET NULL;
ALTER TABLE decks ADD COLUMN box_role TEXT CHECK (box_role IN ('part', 'combined'));
ALTER TABLE decks ADD COLUMN box_parts TEXT;
CREATE INDEX idx_decks_box ON decks(box_id);
