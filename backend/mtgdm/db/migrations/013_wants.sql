-- Cards to buy (the shopping list, exported for Cardmarket's wants), by oracle id: any printing will do.
-- A row is added by hand (deck_id NULL) or holds a deck's missing copies (one row per deck and card,
-- replaced when the deck's missing cards are added again). owned_at_add = real copies owned when the row
-- was set: copies added to the collection since then count as bought.
CREATE TABLE wants (
    id           INTEGER PRIMARY KEY,
    oracle_id    TEXT NOT NULL,
    deck_id      INTEGER REFERENCES decks(id) ON DELETE CASCADE,
    quantity     INTEGER NOT NULL CHECK (quantity > 0),
    owned_at_add INTEGER NOT NULL DEFAULT 0,
    added_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX idx_wants_oracle_deck ON wants(oracle_id, IFNULL(deck_id, 0));
CREATE INDEX idx_wants_deck ON wants(deck_id);
