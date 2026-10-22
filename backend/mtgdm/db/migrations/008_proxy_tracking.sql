-- Proxy tracking. Printed proxy PDFs are recorded (print_jobs: what was printed, to mark as proxies
-- or print again), and collection items get a kind: 'real' copies are owned; 'proxy' copies stand in
-- for a card in a deck's box and never count as owned. Existing items are real.
CREATE TABLE print_jobs (
    id          INTEGER PRIMARY KEY,
    deck_id     INTEGER REFERENCES decks(id) ON DELETE SET NULL,
    profile_id  INTEGER REFERENCES printer_profiles(id) ON DELETE SET NULL,
    title       TEXT NOT NULL,
    paper       TEXT NOT NULL,
    style       TEXT NOT NULL DEFAULT 'image',
    duplex      TEXT NOT NULL DEFAULT 'off',
    items       TEXT NOT NULL,               -- JSON [{card_id, qty, faces}]
    card_count  INTEGER NOT NULL,            -- copies printed (both faces of a card count once)
    page_count  INTEGER,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    marked_at   TEXT                         -- when its cards were marked as proxies
);

ALTER TABLE collection_items ADD COLUMN kind TEXT NOT NULL DEFAULT 'real' CHECK (kind IN ('real', 'proxy'));
ALTER TABLE collection_items ADD COLUMN printed_at TEXT;
ALTER TABLE collection_items ADD COLUMN print_job_id INTEGER REFERENCES print_jobs(id) ON DELETE SET NULL;
CREATE INDEX idx_collection_items_kind ON collection_items(kind);
