-- Two-sided printing: how far the printer puts the back side off the front (measured on the duplex
-- test page, as seen from the front: + right / down), and the flip mode it was measured with.
ALTER TABLE printer_profiles ADD COLUMN back_offset_x_mm REAL NOT NULL DEFAULT 0;
ALTER TABLE printer_profiles ADD COLUMN back_offset_y_mm REAL NOT NULL DEFAULT 0;
ALTER TABLE printer_profiles ADD COLUMN back_offset_duplex TEXT CHECK (back_offset_duplex IN ('long', 'short'));
