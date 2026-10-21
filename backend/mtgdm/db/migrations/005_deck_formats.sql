-- Deck formats are validated by the API (DeckFormat); the CHECK on decks.format made every new
-- format (pioneer) a table rebuild. Rebuild once without it. Foreign keys are off during
-- migrations, so dropping the old table does not cascade into deck_cards / deck_versions.
CREATE TABLE decks_new (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    format            TEXT NOT NULL DEFAULT 'freeform',
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
INSERT INTO decks_new SELECT id, name, format, platform, commander_card_id, partner_card_id, companion_card_id,
                             preferred_sets, location_id, description, created_at, updated_at FROM decks;
DROP TABLE decks;
ALTER TABLE decks_new RENAME TO decks;
