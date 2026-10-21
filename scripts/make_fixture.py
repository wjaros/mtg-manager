#!/usr/bin/env python3
"""Cut a small Scryfall fixture out of a downloaded default_cards bulk file.

Tests must not hit the network, so they import this subset of real card objects.
Run after `mtgdm sync` (which keeps the bulk file in <data dir>/bulk/):

    cd backend && uv run python ../scripts/make_fixture.py [--bulk PATH] [--decklists ../seeds/*.txt ../seeds/collection/*.txt]

Cards in NAMES keep their newest MAX_PRINTINGS printings, cards from decklists the newest
DECKLIST_PRINTINGS plus one Arena printing; all keep every printing from KEEP_SETS.
Link fields are dropped to keep the fixture small.
"""

import argparse
import gzip
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from mtgdm.config import load_settings  # noqa: E402
from mtgdm.db import connect  # noqa: E402
from mtgdm.decks.textformat import parse_decklist  # noqa: E402
from mtgdm.scryfall.bulk import BULK_TYPE, iter_bulk_file  # noqa: E402

OUTPUT = ROOT / "backend" / "tests" / "fixtures" / "scryfall" / "cards.jsonl.gz"
SETS_OUTPUT = OUTPUT.with_name("sets.json")
SET_COLUMNS = ("code", "arena_code", "mtgo_code", "name", "set_type", "released_at", "digital")
# Sets needed by tests even without fixture cards in them (Arena code collisions).
EXTRA_SETS = {"med"}
MAX_PRINTINGS = 8
DECKLIST_PRINTINGS = 2
KEEP_SETS = {"fdn", "who", "soc", "mat", "dom", "snc", "sos", "me1", "med"}
# Exact printings needed by tests: the Moxfield collection CSV example (tests/fixtures/moxfield).
KEEP_PRINTINGS = {("c21", "9"), ("oc21", "9"), ("tmp", "1"), ("2x2", "36")}
DROP_FIELDS = {
    "all_parts", "purchase_uris", "related_uris", "uri", "scryfall_uri", "rulings_uri",
    "prints_search_uri", "set_uri", "set_search_uri", "scryfall_set_uri",
}

# Cards used by tests: search, multi-face layouts, defaults, Arena availability.
NAMES = [
    "Giada, Font of Hope",
    "Errant and Giada",
    "Luxior, Giada's Gift",
    "Serra Angel",
    "Seal Away",
    "Calix, Guided by Fate",
    "Fire // Ice",
    "Twice Upon a Time // Unlikely Meeting",
    "Kirol, History Buff // Pack a Punch",
    "Delver of Secrets // Insectile Aberration",
    "Haywire Mite",
    "Sol Ring",
    "Command Tower",
    "Lightning Bolt",
    "Plains",
    "Snow-Covered Forest",
    "The Fourth Doctor",
    "Sarah Jane Smith",
    "Quintorius, History Chaser",
    # Arena code collision: me1 has arena_code 'med', which is also the Scryfall code of another set.
    "Swords to Plowshares",
    "Forest",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bulk", type=Path, default=load_settings().bulk_dir / f"{BULK_TYPE}.data")
    parser.add_argument("--names-file", type=Path, help="extra card names, one per line")
    parser.add_argument("--decklists", type=Path, nargs="*", default=[], help="decklist files whose cards to include")
    parser.add_argument("--extras", type=int, default=2, help="how many tokens/art cards to include")
    args = parser.parse_args()

    names = set(NAMES)
    if args.names_file:
        names |= {line.strip() for line in args.names_file.read_text(encoding="utf-8").splitlines() if line.strip()}
    deck_names: set[str] = set()
    keep_printings = set(KEEP_PRINTINGS)
    for path in args.decklists:
        lines = parse_decklist(path.read_text(encoding="utf-8")).lines
        deck_names |= {line.name for line in lines}
        # Printings a list names exactly (set + number) must exist for its import test.
        keep_printings |= {(line.set_code, line.collector_number) for line in lines if line.set_code and line.collector_number}
    deck_names -= names
    # Decklists may use a front-face name ("Kirol, History Buff") for "Kirol, History Buff // Pack a Punch".
    wanted = names | deck_names

    def wanted_name(card: dict) -> str | None:
        if card["name"] in wanted:
            return card["name"]
        front = card["name"].split(" // ")[0]
        return card["name"] if front in wanted else None

    # Printings shown on the scan fixture images must exist for the scan tests.
    scan_manifest = OUTPUT.parent.parent / "scans" / "cards" / "manifest.json"
    scan_ids = {c["id"] for c in json.loads(scan_manifest.read_text(encoding="utf-8"))} if scan_manifest.is_file() else set()
    wanted |= {c["name"] for c in json.loads(scan_manifest.read_text(encoding="utf-8"))} if scan_ids else set()

    by_name: dict[str, list[dict]] = {}
    extras: list[dict] = []
    kept_printings: list[dict] = []
    for card in iter_bulk_file(args.bulk):
        if (card.get("set"), card.get("collector_number")) in keep_printings:
            kept_printings.append({k: v for k, v in card.items() if k not in DROP_FIELDS})
        elif name := wanted_name(card):
            by_name.setdefault(name, []).append({k: v for k, v in card.items() if k not in DROP_FIELDS})
        elif card.get("layout") in ("token", "art_series") and len(extras) < args.extras and card.get("set", "").removeprefix("t") in KEEP_SETS:
            extras.append({k: v for k, v in card.items() if k not in DROP_FIELDS})

    found_fronts = {n.split(" // ")[0] for n in by_name} | by_name.keys()
    missing = wanted - found_fronts
    if missing:
        print(f"Not found in bulk data: {', '.join(sorted(missing))}", file=sys.stderr)

    selected: list[dict] = []
    for name in sorted(by_name):
        printings = sorted(by_name[name], key=lambda c: (c.get("released_at", ""), c["id"]), reverse=True)
        limit = MAX_PRINTINGS if name in names else DECKLIST_PRINTINGS
        kept = printings[:limit] + [c for c in printings[limit:] if c["set"] in KEEP_SETS or c["id"] in scan_ids]
        if not any("arena" in c.get("games", []) for c in kept):
            kept += [c for c in printings if "arena" in c.get("games", [])][:1]
        selected += kept
    selected += kept_printings + extras

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps the file byte-identical when the content does not change.
    with gzip.GzipFile(OUTPUT, "wb", mtime=0) as raw, io.TextIOWrapper(raw, encoding="utf-8") as f:
        for card in selected:
            f.write(json.dumps(card, ensure_ascii=False, separators=(",", ":")) + "\n")
    print(f"Wrote {len(selected)} printings of {len(by_name)} cards (+{len(extras)} extras) to {OUTPUT}")

    # Set metadata (Arena codes etc.) comes from the database filled by `mtgdm sync`.
    set_codes = {c["set"] for c in selected} | EXTRA_SETS
    conn = connect(load_settings().db_path)
    rows = conn.execute(
        f"SELECT {', '.join(SET_COLUMNS)} FROM sets WHERE code IN ({', '.join('?' * len(set_codes))}) ORDER BY code",
        sorted(set_codes),
    ).fetchall()
    conn.close()
    SETS_OUTPUT.write_text(json.dumps([dict(r) for r in rows], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} sets to {SETS_OUTPUT}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
