# CLAUDE.md

Local MTG collection / deckbuilding / scanning app: FastAPI backend + React frontend, shipped as a desktop
window app (pywebview) for macOS and Windows. Features: README.md; user guide: `docs/{pl,en}/`.
Every Python module opens with a docstring saying what it does and why: read it before changing the module.
Changes end with a working app and tests.

## Language
Code, comments, API and DB names, commit messages in English. UI texts in Polish and English, never inline:
- frontend: `frontend/src/i18n/pl.ts` is the source of keys, `en.ts` is typed by it (a missing key fails the
  build); used as `t.section.key`
- backend messages shown in the UI (validation, import warnings, errors): `mtgdm/i18n.py`, `tr("key", ...)`;
  the language comes from Accept-Language (the frontend sends its own; default Polish)

## Layout
- `backend/` – Python 3.12, `uv`, package `mtgdm` (flat, no `src/`)
  - `__main__.py` – CLI `mtgdm app | serve | sync | check-window` (the last only loads the window toolkit, for
    the smoke test); `app.py` – app factory, serves `frontend/dist` with an SPA fallback
  - `config.py` – data dir via platformdirs (`MTGDM_DATA_DIR`, `MTGDM_FRONTEND_DIST`, `MTGDM_SEEDS_DIR`);
    bundled resource paths (FROZEN branch) must match the PyInstaller spec
  - `api/` – thin FastAPI routers under `/api`, one file per area (`cards`, `decks`, `collection`, `wants`,
    `printing`, `scans`, `precons`, `importing` `/import`, `backup`, `sync`, `prefs`, `updates`, `cardtrader`,
    `images`, `health`); `deps.py`: `Db` (one connection per request), `AppSettings`. Deck-scoped endpoints
    live with their area: `/decks/{id}/missing|holdings|collection` in `collection.py`, `/decks/{id}/wants`
    in `wants.py`, `/decks/{id}/proxy-candidates|tokens|proxies` in `printing.py`, `/decks/{id}/missing/precons`
    in `precons.py`. Request/response models in each package's `models.py` (or next to the logic)
  - `db/` – `connect()` (WAL), `migrate()`; `migrations/NNN_name.sql` applied on startup, tracked in
    `schema_version`. Tables: `meta` (key/value: settings, tokens, `ui:` prefs); cards: `sets`, `cards` +
    `cards_fts`, `card_details`, `oracle_cards`, `card_tags`, `oracle_tags`, `oracle_tag_parents`,
    `oracle_taggings`, `user_tags`; yours: `locations`, `collection_items`, `decks`, `deck_cards`,
    `deck_versions`, `wants`; `scans`, `scan_items`; `printer_profiles`, `print_jobs`; `precons`, `precon_cards`
  - `scryfall/` – `client.py` (headers, rate limits), `sets.py`, `bulk.py` (`default_cards` import, rebuilds
    `oracle_cards`), `sync.py` (stages; `mtgdm sync`), `manager.py` (background sync + SSE progress),
    `images.py` (image cache, `/api/images/...`), `tags.py` (Tagger's `oracle_tags` bulk, weekly: all tags with
    their hierarchy – a tag's cards include its descendants' – and the card functions the app counts (ramp,
    draw, removal…) pinned by tag id since slugs change, derived into `card_tags`)
  - `cards/` – `search.py` (FTS5 + filters), `syntax.py` (Scryfall-style query; `otag:`, `tag:`),
    `user_tags.py` (the user's tags per oracle id, in the backup), `similar.py` (rules-text phrase match +
    shared Tagger tags; context menu → Similar cards)
  - `decks/` – `service.py` (storage), `textformat.py` (Arena list parser), `matcher.py` (line → printing;
    warnings, never silent fallbacks), `importer.py`, `export.py`, `validation.py` (format rules → issues,
    `allowed_copies`), `stats.py`, `pdf.py` (one card per page, Pillow), `compare.py` (two decks by oracle id:
    copies, price, whether a card fits each deck; tab Compare), `versions.py` (history snapshots)
  - `collection/` – `service.py` (copies, locations; "I own this deck" fills the deck's box location),
    `missing.py` (missing cards + exports), `wants.py` (shopping list per oracle id; real copies added after a
    row count as bought, via `owned_at_add`), `usage.py` (where a card is, for the deckbuilder hover),
    `moxfield.py` (CSV, Cardmarket ↔ US condition scale), `export.py` (Arena-style list, CSV)
  - `printing/` – proxies: `candidates.py` (cards a deck's box lacks), `layout.py` (pure mm geometry +
    calibration; images scaled uniformly, frames/marks per axis), `render.py` (reportlab; a system font with
    Polish letters, else Helvetica without diacritics), `profiles.py`, `text_cards.py`, `tokens.py` (a deck's or
    any cards' tokens, from `all_parts`; the test fixture has none, tests add them), `history.py` (print jobs → proxies in a box),
    `jobs.py` (background job, PDF downloaded from a link)
  - `scan/` – `detect.py` (find + straighten, 1 card or up to 9 on a page) → `ocr/` (Apple Vision on macOS,
    RapidOCR) → `reader.py` (lines → name / number / set / artist / year) → `match.py` (set+number, fuzzy name,
    image hash); `pipeline.py`, `service.py` (scans as records, PDF pages, review, commit), `synth.py`
    (synthetic photos and A4 pages for tests)
  - external services, each with its own client and politeness rules (details in the docstrings):
    `mtgjson/` (precon card lists only, joined by Scryfall id; last sync stage, its failure doesn't fail the
    sync), `cardtrader/` (user's token in `meta`, never in backups; the shopping list as one wishlist,
    recreated on each send since the API can't edit one; API facts in `docs/ideas/cardtrader.md`),
    `spellbook/` (Commander Spellbook combos, ≥1 s between requests, cached in memory for a day),
    `updates.py` (GitHub releases; notify only, no self-update: the macOS app is unsigned)
  - `backup.py` (JSON backup of collection, locations, decks, wants, user tags; cards matched by id, then
    set+number, then name), `cloud_backup.py` (written to a synced folder when the data changed; a newer
    file from another machine is offered on start, never overwritten), `prefs.py` (UI prefs as `ui:` keys in
    meta, not in backups; the interface scale is applied as the web view's own zoom)
- `backend/tests/` – pytest; fixtures in `conftest.py`: `client` (empty DB), `card_settings` (a copy of a DB
  with the fixture cards: `TestClient(create_app(card_settings))`), `db`; fixture data in `tests/fixtures/`
  (Scryfall cut made by `scripts/make_fixture.py --decklists ../seeds/*.txt`), helpers in `tests/helpers.py`.
  HTTP is mocked with `httpx.MockTransport` passed to the client (e.g. `create_app(..., scryfall=...)`)
- `frontend/` – React 19 + TypeScript + Vite, no state library, no test runner (build + lint are the checks)
  - `src/App.tsx` – sidebar + hash routing (`routeFromHash`): `#/` CollectionView (search), `#/collection/items/
    {id|none}` CollectionItemsView, `#/collection/locations|proxies|wants` LocationsView / ProxiesView /
    WantsView, `#/decks` DecksView, `#/decks/{id}[/stats|combos|missing|history|compare]` DeckBuilderView,
    `#/import` ImportView, `#/scan` ScanView, `#/settings` SettingsView (all in `src/views/`)
  - `src/api/client.ts` – `api.*` calls (one per endpoint, sends Accept-Language), type aliases of the
    generated `schema.d.ts` (never edit it), URL builders for downloads and images
  - deckbuilder: `views/DeckBuilderView.tsx` + `hooks/useDeck.ts` (deck state and actions); tabs are
    `components/Deck{StatsPanel,CombosPanel,ComparePanel,HistoryPanel}.tsx`, `MissingPanel.tsx`; the deck
    itself `DeckList.tsx` / `DeckVisual.tsx` / `DeckPreview.tsx`, grouping and sorting in `src/decks.ts`
  - shared: `CardGrid`, `CardDetailPanel`, `Filters` (+ `src/filters.ts` → query), `ContextMenu`,
    `HoverPreview` / `hooks/useHoverPreview`, `ProxyDialog`, `PrintingPanel`, `ExportDialog`, charts in
    `components/charts/`; small stores with a hook: `printQueue.ts`, `wants.ts`; `prefs.ts`, `theme.ts`
  - styles: one `src/index.css` (tokens on `:root`, see Rules)
- `packaging/` + `scripts/build_*` – PyInstaller (macOS + Windows); see Packaging below
- `docs/` – user guide, Jekyll-ready (`docs/ideas/` = developer notes, excluded); `seeds/` – example decklists
  offered in Import (`seeds/collection/`: non-deck products; a trailing `# note` becomes the item's note)

## A typical change touches
- backend logic in its domain module + a route in `api/<area>.py` + tests in `backend/tests/test_<area>*.py`
- new/changed API model → `scripts/gen_api_types.sh` → `api.*` in `frontend/src/api/client.ts`
- UI text → `frontend/src/i18n/pl.ts` + `en.ts`; backend message → `MESSAGES` in `mtgdm/i18n.py` (pl + en)
- new table/column → `db/migrations/0NN_*.sql`; if it is user data, also `backup.py` (+ its test)
- user-visible behavior → `docs/pl/<page>.md` + `docs/en/<page>.md` (and README.md if it lists it)
- a new or moved module, router, table, view or component, a changed command, or a gotcha you had to dig
  out of the code → this file, in the same commit. It is the agents' map: keep it accurate and dense (what a
  file holds and what isn't obvious; the how belongs in the module docstring), and drop what no longer exists

## Commands
- Tests: `cd backend && uv run pytest` (CI adds `-X warn_default_encoding`)
- Python lint: `cd backend && uvx ruff check mtgdm tests ../scripts`
- Frontend checks: `cd frontend && npm run build && npm run lint`
- After changing API models: `scripts/gen_api_types.sh` (no server needed)
- Dev: `scripts/dev.sh` (backend :8765 with reload, Vite :5173 proxying `/api`)
- Window app: `cd frontend && npm run build && cd ../backend && uv run mtgdm app`
- Card data: `cd backend && uv run python -m mtgdm sync` (~2 min, ~700 MB DB; needs network)
- Docs screenshots: `cd frontend && npm run build && cd ../backend && uv run --with playwright python
  ../scripts/docs_screenshots.py [--only stats,history] [--lang pl]` (runs on a copy of the app's data; a new
  shot goes into SHOTS, keep the decks it uses findable by name in DECKS)
- Scan accuracy: `cd backend && uv run python ../scripts/scan_benchmark.py --engine rapidocr` (`--pages 20`)
- Smoke test of a built app: `python scripts/smoke_test.py <executable>`; CI: `.github/workflows/build.yml`
- Release: bump `__version__` in `backend/mtgdm/__init__.py`, merge into master; CI tags `v<version>` and
  publishes. Release notes are made from the commit messages (`scripts/release_notes.py`): write commit
  titles and bodies for users. Packages are built for PRs, releases and manual runs only

## Rules
- Tests never touch the network: fixtures + mocked HTTP.
- Schema change = a new migration file (next number); never edit an applied one. Migrations run with foreign
  keys off (a table rebuild must not cascade) and must leave no broken reference. Deck formats are not a DB
  CHECK: add them to `DeckFormat` (`decks/models.py`) and the validator.
- Always pass `encoding="utf-8"` to text file I/O (Windows defaults to cp1252); CI enforces it.
- A feature change updates the user guide in both languages (`docs/pl/` and `docs/en/`, same file names,
  ASCII anchors; screenshots in `docs/images/{pl,en}/`, 1440×900 WebP) and README.md when it lists the feature.
- New dependency: GPLv3-compatible only (MIT, BSD, Apache-2.0, MPL-2.0 yes; GPL-2.0-only no); add it to
  THIRD_PARTY_NOTICES.md.
- Frontend: remembered UI choices go through `src/prefs.ts` (`getPref` / `setPref`), never localStorage (the
  window's web view is private and on a random port, so browser storage is lost on restart).
- Colors are tokens on `:root` (dark) with a light set under `:root[data-theme='light']`; no hex colors in
  rules, a tint is `color-mix(in srgb, var(--token) N%, transparent)`; check new UI in both themes. Chart
  colors are `--series-*` in `src/index.css`, validated with the dataviz palette validator: don't add hues
  without re-validating.

## Scryfall (https://scryfall.com/docs/api)
- api.scryfall.com: own `User-Agent: MTGDeckManager/<version>` and `Accept` headers, 100 ms between requests,
  500 ms before `/cards/search`, `/named`, `/random`, `/collection` (`ENDPOINT_INTERVALS` in the client);
  a 429 locks the app out for 30 s, repeated ones risk a ban: prefer bulk files. `*.scryfall.io` (bulk, images) has no rate limit.
- Card data from the `default_cards` bulk file (gzipped JSONL via `jsonl_download_uri`, streamed, never loaded
  whole; no `A-` Alchemy cards in it); refresh weekly or after a set release.
- Images cached locally, never hotlinked, cropped, filtered or watermarked.
- Prices are up to a day old: show them as estimates with their date. Never paywall or republish raw data.

## Data notes
- `collection_items.kind`: 'proxy' copies stand in for a card in a deck's box and never count as owned
  (owned filters, stats, missing, exports, validation): filter `kind = 'real'` in new queries.
- `cards` is kept narrow (full scans); bulky JSON lives in `card_details` (1:1).
- `oracle_cards` = one row per card with `default_card_id` / `arena_card_id` (both prefer regular booster
  printings in a plain frame), rebuilt after each sync.
- A card in search results shows the printing owned in most copies (`owned_printings` in `cards/search.py`),
  not on Arena or with printing filters.
- `deck_cards` is the source of truth; `decks.commander/partner/companion_card_id` are derived. `deck_versions`
  holds snapshots; "unsaved" = diff vs the latest one, per card name + board (a printing swap isn't a removal).
- Scryfall `arena_code` can collide with another set's `code` (me1 → `med`): resolve set codes by `code` first.

## Packaging
- The bundle uses a minimal OpenCV (`scripts/build_opencv.py`: core/imgproc/imgcodecs, same version as
  uv.lock, cached in `build/opencv-slim/`); a cv2 function from another module needs adding to its `MODULES`
  (BUILD_LIST). Dev and tests use the PyPI wheel.
- HEIC only on macOS via ImageIO (`scan/imageio_mac.py`); libheif wheels carry GPL x265, not bundled.
- The macOS bundle ships Apple Vision only (`MTGDM_BUNDLE_RAPIDOCR=1` adds RapidOCR; it needs PyYAML, don't
  exclude `yaml` then).
- Windows: pywebview → pythonnet → WebView2. Explorer marks files from a downloaded zip and .NET won't load
  them: the app drops the mark from its DLLs before loading pythonnet; the smoke test marks the bundle.
