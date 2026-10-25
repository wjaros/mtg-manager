-- The user's own tags on cards ("wincon", "pet card", ...): per card (oracle id, every printing),
-- several per card, alike in any case. No foreign key: oracle_cards is rebuilt at each sync.
CREATE TABLE user_tags (
    oracle_id TEXT NOT NULL,
    tag       TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (oracle_id, tag)
) WITHOUT ROWID;
CREATE INDEX idx_user_tags_tag ON user_tags(tag);
