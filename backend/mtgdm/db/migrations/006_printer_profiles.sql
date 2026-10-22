-- Printer profiles for proxy printing (mtgdm.printing). The raw measurements and the card size of
-- the calibration page are kept, so the factors can always be recomputed from them.
CREATE TABLE printer_profiles (
    id                INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    paper             TEXT NOT NULL DEFAULT 'a4' CHECK (paper IN ('a4', 'letter')),
    scale_x           REAL NOT NULL DEFAULT 1.0,
    scale_y           REAL NOT NULL DEFAULT 1.0,
    offset_x_mm       REAL NOT NULL DEFAULT 0.0,
    offset_y_mm       REAL NOT NULL DEFAULT 0.0,
    measured_a_mm     REAL,
    measured_b_mm     REAL,
    measured_left_mm  REAL,
    measured_top_mm   REAL,
    card_w_mm         REAL,
    card_h_mm         REAL,
    is_default        INTEGER NOT NULL DEFAULT 0,
    calibrated_at     TEXT,
    note              TEXT
);
