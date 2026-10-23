-- Scryfall's functional oracle tags (Tagger, community-made) for a few common roles: ramp, card
-- draw, removal, ... Fetched with the card data sync (they aren't in the bulk files); by oracle id.
CREATE TABLE card_tags (
    oracle_id TEXT NOT NULL,
    tag       TEXT NOT NULL,
    PRIMARY KEY (oracle_id, tag)
) WITHOUT ROWID;
CREATE INDEX idx_card_tags_tag ON card_tags(tag);
