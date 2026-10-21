-- Deck history: saved snapshots of a deck's contents. deck_cards stays the working copy (saved on
-- every change); changes since the latest snapshot are shown as unsaved.
CREATE TABLE deck_versions (
    id         INTEGER PRIMARY KEY,
    deck_id    INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    number     INTEGER NOT NULL,
    note       TEXT,
    format     TEXT NOT NULL,
    platform   TEXT NOT NULL,
    cards      TEXT NOT NULL,  -- JSON: [{card_id, quantity, board, category}]
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (deck_id, number)
);

-- Existing decks start their history with their current contents.
INSERT INTO deck_versions(deck_id, number, note, format, platform, cards)
SELECT d.id, 1, 'Stan początkowy', d.format, d.platform,
       (SELECT json_group_array(json_object('card_id', card_id, 'quantity', quantity, 'board', board,
                                            'category', category))
        FROM (SELECT * FROM deck_cards WHERE deck_id = d.id ORDER BY rowid))
FROM decks d;
