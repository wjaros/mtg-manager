-- Scan review: attributes chosen per recognized card before it is added to
-- the collection, and how the scan was processed.
ALTER TABLE scans ADD COLUMN original_name TEXT;
ALTER TABLE scans ADD COLUMN ocr_engine TEXT;
ALTER TABLE scans ADD COLUMN error TEXT;
ALTER TABLE scans ADD COLUMN committed_at TEXT;

ALTER TABLE scan_items ADD COLUMN ocr_text TEXT;
ALTER TABLE scan_items ADD COLUMN ocr_language TEXT;
ALTER TABLE scan_items ADD COLUMN quantity INTEGER NOT NULL DEFAULT 1;
ALTER TABLE scan_items ADD COLUMN finish TEXT NOT NULL DEFAULT 'nonfoil';
ALTER TABLE scan_items ADD COLUMN language TEXT;
ALTER TABLE scan_items ADD COLUMN condition TEXT NOT NULL DEFAULT 'NM';
ALTER TABLE scan_items ADD COLUMN location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL;

CREATE INDEX idx_scans_created_at ON scans(created_at);
