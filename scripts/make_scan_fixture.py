#!/usr/bin/env python3
"""Download card images used to build synthetic photos for scan tests (no network in tests).

    cd backend && uv run python ../scripts/make_scan_fixture.py

Needs a synced database (mtgdm sync). Writes backend/tests/fixtures/scans/cards/<id>.jpg and
manifest.json with the ground truth (name, set, collector number, frame).
"""

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from mtgdm.config import load_settings  # noqa: E402
from mtgdm.db import connect  # noqa: E402
from mtgdm.scryfall import ScryfallClient  # noqa: E402
from mtgdm.scryfall.images import ImageCache  # noqa: E402

OUTPUT = ROOT / "backend" / "tests" / "fixtures" / "scans" / "cards"
SIZE = "large"  # 672x936: the collector line must stay readable after synthetic degradation

# Different frames (1993, 2003, 2015, 2024 layout), borderless, split, double-faced, basic land.
PRINTINGS = [
    ("Swords to Plowshares", "ice", "54"),
    ("Lightning Bolt", "m10", "146"),
    ("Seal Away", "dom", "31"),
    ("Serra Angel", "dom", "33"),
    ("Ajani's Pridemate", "war", "4"),
    ("Fire // Ice", "mh2", "290"),
    ("Delver of Secrets // Insectile Aberration", "mid", "47"),
    ("Lightning Bolt", "2x2", "117"),
    ("Calix, Guided by Fate", "mat", "26"),
    ("Sol Ring", "cmm", "410"),
    ("The Fourth Doctor", "who", "2"),
    ("Giada, Font of Hope", "fdn", "141"),
    ("Giada, Font of Hope", "fdn", "298"),
    ("Plains", "fdn", "272"),
]


def main() -> int:
    settings = load_settings()
    conn = connect(settings.db_path)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    with ScryfallClient() as client:
        cache = ImageCache(settings.images_dir, client)
        for name, set_code, number in PRINTINGS:
            row = conn.execute(
                """
                SELECT c.id, c.oracle_id, c.layout, json_extract(d.raw, '$.frame') AS frame, c.border_color
                FROM cards c JOIN card_details d ON d.id = c.id
                WHERE c.name = ? AND c.set_code = ? AND c.collector_number = ?
                """,
                (name, set_code, number),
            ).fetchone()
            if row is None:
                print(f"missing in database: {name} ({set_code} {number})", file=sys.stderr)
                return 1
            source = cache.get(conn, row["id"], SIZE, 0)
            shutil.copy(source, OUTPUT / f"{row['id']}.jpg")
            manifest.append({
                "id": row["id"], "oracle_id": row["oracle_id"], "name": name, "set": set_code,
                "collector_number": number, "layout": row["layout"], "frame": row["frame"],
                "border_color": row["border_color"],
            })
    (OUTPUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    size = sum(p.stat().st_size for p in OUTPUT.glob("*.jpg"))
    print(f"Wrote {len(manifest)} images ({size / 1e6:.1f} MB) to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
