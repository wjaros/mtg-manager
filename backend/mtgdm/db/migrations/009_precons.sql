-- Official preconstructed decks (MTGJSON deck files): the list of every product deck, and the cards
-- of those loaded (Commander decks at every sync, others when imported). Cards are referenced by
-- Scryfall id without a foreign key: a deck may list a printing the local card data doesn't have;
-- name, set code and number are kept to fall back on.
CREATE TABLE precons (
    file_name    TEXT PRIMARY KEY,   -- MTGJSON's deck id, e.g. LoreholdSpirit_SOC
    code         TEXT NOT NULL,      -- MTGJSON set code of the product (upper case)
    name         TEXT NOT NULL,
    type         TEXT NOT NULL,      -- e.g. "Commander Deck", "Theme Deck"
    release_date TEXT,
    commanders   TEXT,               -- JSON list of commander names (loaded decks)
    card_count   INTEGER,            -- copies in the deck (loaded decks)
    loaded_at    TEXT                -- when its cards were fetched; NULL = list entry only
);
CREATE INDEX idx_precons_type ON precons(type);

CREATE TABLE precon_cards (
    file_name TEXT NOT NULL REFERENCES precons(file_name) ON DELETE CASCADE,
    board     TEXT NOT NULL CHECK (board IN ('commander', 'main', 'sideboard')),
    card_id   TEXT,                  -- Scryfall id
    name      TEXT NOT NULL,
    set_code  TEXT,
    number    TEXT,
    quantity  INTEGER NOT NULL
);
CREATE INDEX idx_precon_cards_file ON precon_cards(file_name);
CREATE INDEX idx_precon_cards_card ON precon_cards(card_id);
