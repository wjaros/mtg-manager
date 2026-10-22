# Idea: keep my data in a cloud folder

Status: idea, not planned yet.

## What I want

Keep my collection and decks in a folder that a cloud drive syncs, such as `~/Documents` (iCloud
Drive) or OneDrive. The data would then be backed up automatically and available on a second
computer (e.g. Mac at home, Windows elsewhere) without exporting and importing backups by hand.

## What there is today

- Everything lives in one data directory (`mtgdm/config.py`, `platformdirs`; override with
  `MTGDM_DATA_DIR`): `db.sqlite`, `images/`, `bulk/`, `scans/`, `logs/`, `print/`.
- `db.sqlite` mixes two kinds of data:
  - **Scryfall card data:** ~650 MB, can be downloaded again at any time (`mtgdm sync`).
  - **My own data:** tiny. Today that is 290 collection items, 4 locations, 4 decks with 281 cards,
    deck versions and 1 printer profile, plus settings in `meta` (card size).
- *Settings → Backup* already writes all of my own data as one JSON file and restores it. Cards
  are referenced by Scryfall id, then set and number, then name, so a backup survives changes in
  the card data.

## Why not just put the data directory in iCloud or OneDrive

- **Size:** 650 MB of database plus image and bulk caches would sync after every weekly Scryfall
  update, for data that can be downloaded again.
- **SQLite in a synced folder is risky:** WAL mode keeps `db.sqlite-wal` and `-shm` next to the
  database. A sync client can upload the three files at different moments, or merge two
  machines' copies, which leaves an inconsistent or corrupted database. Both iCloud and OneDrive
  can also evict files to "online only".
- **Two machines writing at once:** sync clients resolve conflicts by keeping both files
  ("db 2.sqlite"), so changes from one side silently disappear.

## Proposed approach

### Step 1: automatic backups to a chosen folder

- *Settings → Backup*: pick a folder (e.g. `~/Documents/MTG Deck Manager`). After each change
  (debounced, e.g. 30 s), or on quit, write the JSON backup there: one small file, written
  atomically (temporary file, then rename).
- On start, if the backup in that folder is newer than the local data and was written by another
  machine, offer to load it. This is the existing restore with replace.
- Keep the last few files (e.g. `backup-<date>.json`) as history.
- This is safe with any sync client: a single JSON file, written whole, and read only on request.

### Step 2 (optional): my data in its own database in the cloud folder

- Split the database: `cards.sqlite` (Scryfall data, local, can be downloaded again) and
  `user.sqlite` (collection, locations, decks, versions, scans, printer profiles, settings),
  joined with `ATTACH`.
  - Foreign keys from user tables to `cards(id)` can't cross databases. Today's backup already
    copes with cards that can't be found, so the same "resolve by id, then set and number, then
    name" logic would be needed when the card data changes.
- `user.sqlite` lives in the cloud folder, in `journal_mode=DELETE`, not WAL, so it is one file.
- A lock file (`user.lock`: machine name and time) allows one writer. A second machine opens the
  data read-only, or asks to take over when the lock is old.
- Even so, a sync client can still produce conflict copies. Detect them (`user 2.sqlite`, OneDrive's
  `-<PC name>` names) and offer to resolve them.

Recommendation: do step 1. It covers backup and moving between computers with little code and
no new risks. Step 2 only pays off if both machines are used at the same time.

## Open questions

- Is automatic "load the newer backup on start" enough, or should it always ask?
- Should scans (photos) sync too? They can be large, and today they are only kept until committed.
- iCloud on Windows and OneDrive on Mac: the folder picker has to accept any path the sync client
  creates.
