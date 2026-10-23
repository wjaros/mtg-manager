# CLAUDE.md

Local MTG collection / deckbuilding / scanning app (see README.md). Changes end with a working app and tests.
Code, comments, API and DB names in English. UI texts in Polish and English, never inline:
frontend `src/i18n/pl.ts` (source of keys) + `en.ts` (typed by pl, a missing key fails the build), used as `t.section.key`;
backend messages for the UI (validation, import warnings, errors) in `mtgdm/i18n.py` via `tr("key", ...)`,
language from the request's Accept-Language (the frontend sends its own; default Polish).

## Layout
- `backend/` – Python 3.12, FastAPI, managed with `uv`. Package `mtgdm` (flat layout, no `src/`).
  - `mtgdm/__main__.py` – CLI `mtgdm app | serve | sync`
  - `mtgdm/app.py` – app factory; serves `frontend/dist` (SPA fallback) when it exists
  - `mtgdm/config.py` – data dir via platformdirs; override with `MTGDM_DATA_DIR`, `MTGDM_FRONTEND_DIST`
  - `mtgdm/db/migrations/NNN_name.sql` – numbered SQL migrations, applied on startup, tracked in `schema_version`
  - `mtgdm/scryfall/` – API client (headers, rate limit), sets + `default_cards` bulk sync (`mtgdm sync`)
  - `mtgdm/mtgjson/` – MTGJSON (MIT) for precon card lists only (Scryfall stays the card source; joined by Scryfall id):
    `precons.py` syncs DeckList.json + Commander decks as the last sync stage (failure doesn't fail the sync),
    others on demand; a precon becomes import text with exact printings; `browse_precons` (owned / value per
    Commander precon) and `precons_for_missing` (precons covering a deck's missing cards, basics left out)
  - `mtgdm/spellbook/` – Commander Spellbook `find-my-combos` (own UA, ≥1 s between requests, 429 back-off; answers
    cached in memory per card list for a day, nothing stored): a deck's combos and those one card away, cards mapped
    to local printings (`GET /api/decks/{id}/combos`, deckbuilder tab Combo)
  - `mtgdm/cards/` – search (FTS5 + filters), card detail, printings; `syntax.py` – Scryfall-style query syntax
  - `mtgdm/scan/` – card scanning: `detect.py` (find + straighten; single card or up to 9 on a page), `ocr/` (Apple Vision on macOS, RapidOCR),
    `reader.py` (OCR lines -> name / number / set / artist / year), `match.py` (set+number, fuzzy name, image hash),
    `pipeline.py` (auto/single/page, manual grid), `service.py` (scans as records, PDF pages, review, commit),
    `synth.py` (synthetic photos and A4 pages for tests)
  - `mtgdm/backup.py` – JSON backup of collection, locations and decks (cards by id, then set+number, then name)
  - `mtgdm/updates.py` – new version check (GitHub releases API, cached in meta, skip a version); notify only,
    no self-update (unsigned macOS app)
  - `mtgdm/cloud_backup.py` – the backup written to a chosen (synced) folder by a background thread when the data
    changed (hash without timestamps); a newer file from another machine id is offered on start (never overwritten)
  - `mtgdm/decks/` – deck storage (`deck_cards` is the source of truth; decks.commander/partner/companion_card_id are derived),
    `textformat.py` (Arena list parser), `matcher.py` (line → printing, warnings instead of silent fallbacks), `export.py`,
    `validation.py` (format rules → issues), `stats.py`, `pdf.py` (deck PDF, one card per page, Pillow)
    `versions.py` – deck history: `deck_cards` is the working copy (saved on every change), `deck_versions` holds
    snapshots; changes vs the latest snapshot = "unsaved" (diffed per card name + board, so a printing swap isn't a removal)
  - `mtgdm/collection/` – physical copies (`collection_items`) and locations; "I own this deck" puts a deck into its box location;
    `missing.py` – missing-cards report per deck + exports (text / CardMarket wants / CSV)
    `wants.py` – shopping list (`wants`, per oracle id: by hand or a deck's missing copies; real copies added
    after a row count as bought, via `owned_at_add`), Cardmarket / CSV export, in the backup
    `usage.py` – where a card is (copies per location / deck box, decks listing it) for the deckbuilder hover
    `moxfield.py` – Moxfield collection CSV export / import (condition scale mapping Cardmarket <-> US)
    `export.py` – collection export: Arena-style list (`4 Name (SET) 123`, Scryfall set codes) and CSV
  - `mtgdm/printing/` – proxy printing: `candidates.py` (cards a deck's box lacks), `layout.py` (pure mm geometry,
    calibration math; images are scaled uniformly, frames/marks per axis), `render.py` (reportlab; a system font with
    Polish letters, else Helvetica without diacritics), `profiles.py` (printer profiles, card size in meta),
    `text_cards.py` (text proxies: rules text per face, split/adventure halves on one card),
    `history.py` (print_jobs: recorded prints; marking their cards as proxies in a deck's box),
    `tokens.py` (tokens a deck makes, from all_parts; the test fixture has no all_parts, tests add them),
    `jobs.py` (background job: images first, then pages; the PDF is downloaded from a link)
  - `mtgdm/scryfall/tags.py` – card functions (ramp, draw, removal, …) from Scryfall Tagger through `/cards/search?q=otag:X&format=csv`,
    stored per oracle id in `card_tags`, refreshed weekly during sync; `otag:` in the query syntax, `functions` in deck stats
  - `mtgdm/scryfall/images.py` – image cache (`/api/images/...`); `manager.py` – background sync + SSE progress
- `frontend/` – React + TypeScript + Vite. `src/api/schema.d.ts` is generated, do not edit. Views in `src/views/`, hash routing (`#/collection/items/5`, `#/decks/12/missing`, `#/settings`).
- `packaging/` – PyInstaller spec (macOS + Windows), launcher and icons (`scripts/build_macos.sh`, `scripts/build_windows.ps1`);
  the bundle uses a minimal OpenCV (`scripts/build_opencv.py`: core/imgproc/imgcodecs, JPEG+PNG, same version as uv.lock,
  cached in `build/opencv-slim/`) put first on PYTHONPATH; dev and tests use the PyPI wheel. A new cv2 function from
  another module (e.g. features, photo) needs adding to BUILD_LIST there. HEIC only on macOS, through ImageIO
  (`scan/imageio_mac.py`): libheif wheels carry the GPL x265 encoder, not bundled on purpose
- License: GPL-3.0-or-later (LICENSE). Dependencies must be GPLv3-compatible (MIT, BSD, Apache-2.0, MPL-2.0 are;
  GPL-2.0-only is not). Third-party licenses in THIRD_PARTY_NOTICES.md (update it with new dependencies)
  bundled resource paths live in `mtgdm/config.py` (FROZEN branch) and must match the spec
- `seeds/` – example decklists (precons and products), offered in the Import view; `seeds/collection/` – lists of
  products that are not decks (imported into the collection: Import → Kolekcja → Lista kart). A trailing `# note` on a
  list line becomes the collection item's note (e.g. "printing unverified")
- `scripts/` – `dev.sh`, `gen_api_types.sh`, `make_fixture.py` (cuts `backend/tests/fixtures/scryfall/{cards.jsonl.gz,sets.json}` out of real data; run with `--decklists ../seeds/*.txt`)

## Scryfall rules (https://scryfall.com/docs/api)
- Every request to api.scryfall.com: own `User-Agent: MTGDeckManager/<version>` and `Accept` headers, 50–100 ms between
  requests, back off on 429. Files on `*.scryfall.io` (bulk, images) have no rate limit.
- Card data comes from the `default_cards` bulk file (streamed, never loaded whole); refresh weekly or after a set release.
- Images are cached locally and never hotlinked, cropped (copyright / artist line), filtered or watermarked.
- Prices in bulk data are up to a day old: show them as estimates with their date. Never paywall or republish raw data.

## Data notes
- `collection_items.kind`: 'real' copies are owned; 'proxy' copies stand in for a card in a deck's box and must never
  count as owned (search owned filters, stats, missing, exports, validation): filter `kind = 'real'` in new queries.
- `cards` is kept narrow (searched by full scans); bulky JSON lives in `card_details` (1:1).
- `oracle_cards` = one row per card with `default_card_id` / `arena_card_id` (both prefer regular booster printings in a plain frame), rebuilt after each sync.
- Scryfall bulk is gzipped JSONL now (`jsonl_download_uri`); there are no `A-` (Alchemy rebalanced) cards in it.
- Scryfall `arena_code` can collide with another set's `code` (me1 → `med`): resolve set codes by `code` first.

## Commands
- Tests: `cd backend && uv run pytest`
- Sync Scryfall data: `cd backend && uv run python -m mtgdm sync` (~2 min, ~700 MB DB)
- Dev: `scripts/dev.sh` (backend :8765 with reload, Vite :5173 proxying `/api`)
- Window app: `cd frontend && npm run build && cd ../backend && uv run mtgdm app`
- After changing API models: `scripts/gen_api_types.sh`
- Frontend checks: `cd frontend && npm run build && npm run lint`
- Chart colors: `--series-*` in `frontend/src/index.css`, validated with the dataviz palette validator; don't add hues without re-validating.
- Smoke test of a built app: `python scripts/smoke_test.py <path to executable>`; CI: `.github/workflows/build.yml`
- Release: bump `__version__` in `backend/mtgdm/__init__.py` and merge into master; CI tags and publishes
  `v<version>` once all packages pass. Packages are built for PRs, releases and manual runs only (not for
  master pushes that don't release)
- Scan accuracy on synthetic photos: `cd backend && uv run python ../scripts/scan_benchmark.py --engine rapidocr`
  (pages: `--pages 20 --background white|black`; fixture images: `scripts/make_scan_fixture.py`); the macOS bundle ships Apple Vision only
  (`MTGDM_BUNDLE_RAPIDOCR=1` adds RapidOCR; it needs PyYAML via omegaconf, don't exclude `yaml` then)
- Python lint: `cd backend && uvx ruff check mtgdm tests ../scripts`

## Rules
- Tests never touch the network: use fixtures + mocked HTTP client.
- Schema changes = new migration file; never edit an applied migration. Migrations run with foreign keys off (a table
  rebuild must not cascade) and must leave no broken reference (checked before commit). Deck formats are not a DB
  CHECK (since 005): add them to `DeckFormat` and the validator.
- Always pass `encoding="utf-8"` to text file I/O (Windows defaults to cp1252); CI enforces it.
