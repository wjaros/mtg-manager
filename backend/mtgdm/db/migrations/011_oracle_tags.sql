-- Scryfall Tagger's oracle tags from the oracle_tags bulk file (replacing one search per tag):
-- every tag, its place in the hierarchy and the cards tagged with it directly. A tag's cards include
-- those of its descendants ("removal" has none of its own, "spot-removal" below it has thousands).
-- card_tags keeps the few functions the app counts, derived from these at each sync.
CREATE TABLE oracle_tags (
    id          TEXT PRIMARY KEY,  -- stable UUID; slugs may change ("board-wipe" became "sweeper")
    slug        TEXT NOT NULL,
    label       TEXT NOT NULL,
    description TEXT
) WITHOUT ROWID;
CREATE INDEX idx_oracle_tags_slug ON oracle_tags(slug);

CREATE TABLE oracle_tag_parents (
    tag_id    TEXT NOT NULL REFERENCES oracle_tags(id) ON DELETE CASCADE,
    parent_id TEXT NOT NULL REFERENCES oracle_tags(id) ON DELETE CASCADE,
    PRIMARY KEY (tag_id, parent_id)
) WITHOUT ROWID;
CREATE INDEX idx_oracle_tag_parents_parent ON oracle_tag_parents(parent_id);

-- Only cards the local card data has (by oracle id, no foreign key: oracle_cards is rebuilt).
-- ~240k rows, ~23 MB; no index by tag (another ~21 MB) until something looks cards up by tag.
CREATE TABLE oracle_taggings (
    oracle_id TEXT NOT NULL,
    tag_id    TEXT NOT NULL REFERENCES oracle_tags(id) ON DELETE CASCADE,
    weight    TEXT NOT NULL,  -- very_strong | strong | median | weak
    PRIMARY KEY (oracle_id, tag_id)
) WITHOUT ROWID;
