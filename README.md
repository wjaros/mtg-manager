[![Build](https://github.com/wjaros/mtg-manager/actions/workflows/build.yml/badge.svg?branch=master)](https://github.com/wjaros/mtg-manager/actions/workflows/build.yml)

# MTG Deck Manager

A local desktop app for Magic: The Gathering players with a paper collection and an Arena account:
keep track of your cards (by scanning them), build and validate decks, see what a deck still needs, and
export decks to MTG Arena, Moxfield or a phone-friendly PDF. Everything runs on your computer; card
data comes from [Scryfall](https://scryfall.com) and works offline once downloaded.

![Deckbuilder](docs/screenshots/deckbuilder.webp)

## Features

**Collection.** Every card printing from Scryfall, searchable by name or with Scryfall-style filters
(`t:angel mv<=3 id:wr`). Physical copies with printing, finish, language, condition and location
(binders, boxes, deck boxes). Open any card and you see where each of your copies lies, e.g. "1×
DOM #31 · NM · Giada, Font of Hope" means it sits in that deck's box, so you know where to take it from.
Filter the search to the cards you own or to the ones you're missing.

![Collection](docs/screenshots/collection.webp)

**Deckbuilder.** Arena-style deckbuilder for Commander, Brawl, Standard Brawl, Historic, Standard,
Pioneer and freeform decks:
- the card pool shows only cards that fit the deck (commander identity, format, Arena availability);
- format validation runs as you build;
- mana value columns;
- statistics: curve, colours, types, categories and the price of what's missing.

Hovering a card shows how many copies the deck has, how many you own and where they are (e.g. in
another deck's box). Singleton duplicates are greyed out.

![Statistics](docs/screenshots/stats.webp)

**Version history.** Decks save as you edit. *Save version* takes a snapshot, and everything since
the last snapshot is highlighted: added cards in green, removed ones struck through in red, swapped
printings in yellow. You can compare versions, restore one or discard unsaved changes.

![History](docs/screenshots/history.webp)

**What's missing.** In a paper deck, each card's quantity is coloured by where its copies are:
- *missing*: you don't own enough copies;
- *in another deck*: your copies sit in another deck's box (the tooltip names the deck);
- *not in box*: you own it, but it isn't in this deck's box.

Missing cards are greyed out in the mana columns. The *Missing* tab lists what to buy, with
estimated prices. Copies built into your other decks can count as unavailable, so the list covers
having both decks at once. Copy the list into a CardMarket wants list or download it as CSV.

![Missing cards](docs/screenshots/missing.webp)

**Scanning.** Drop photos of single cards, flatbed scans of whole pages (up to 9 cards, e.g. a binder
page) or PDFs. Cards are found, straightened and recognized by name, collector line and art. You
review the result and choose finish, condition and location before anything reaches the collection.

![Scanning](docs/screenshots/scan.webp)

**Import and export.**
- Decklists: paste from MTG Arena or Moxfield, with a match report before saving (exact printings,
  warnings, suggestions).
- Collections: product contents as a card list, or Moxfield's collection CSV.
- Exports:
  - MTG Arena (printings that aren't on Arena are swapped);
  - Moxfield collection CSV;
  - Arena-style lists and CSV;
  - a deck as a PDF with one card per page, for browsing on a phone;
  - a full JSON backup.

![Import](docs/screenshots/import.webp)

**Proxy printing.** From a paper deck, *Proxies* lists the cards you can't put in its box: the ones
you don't own and the ones sitting in another deck's box. Pick the quantities and printings, add
any card by hand, and get a PDF of 3 × 3 card-size proxies with crop marks (A4 or Letter; double-faced
cards print both faces). Printers scale pages slightly, so *Settings → Printing* calibrates each
printer: print a calibration page, measure two lengths with a ruler, and later prints come out at
real card size. Card images are printed unaltered, for personal playtesting only.

The interface is in Polish and English (Settings → Language).

## Install

Download the latest build from [Releases](https://github.com/wjaros/mtg-manager/releases):

- **macOS:** `…-arm64.dmg` for Apple Silicon (M1–M4), `…-x86_64.dmg` for Intel. The app is not
  notarized: open it the first time with right click → Open.
- **Windows:** `…-windows-x64.zip`. Unpack it and run `MTG Deck Manager.exe` (needs the Edge
  WebView2 runtime, built into Windows 11 and current Windows 10).

On first start, open **Settings → Download card data** (about 80 MB; the import takes 2–3 minutes).
Refresh it now and then: the app suggests it when Scryfall has newer data.

## Scanning tips

- **Flatbed scanner:**
  - black-bordered cards with the lid closed (white background);
  - white-bordered cards with the lid open in a dark room (black background);
  - a small gap between cards helps.
- **Missed cards on a page:** use *Missed some cards? Grid…* (rows × columns, optionally over a
  selected area).
- **Photos:** one card per photo, from above, on a contrasting matte background, in diffuse light
  without reflections on the card or sleeve. HEIC (iPhone) photos work on macOS. On Windows, set
  the iPhone to save JPG (Settings → Camera → Formats → Most Compatible).
- **OCR:** Apple Vision on macOS; RapidOCR (bundled models, offline) on Windows and Linux.

## Development

Requirements: [uv](https://docs.astral.sh/uv/) (installs Python 3.12), Node.js.

```sh
cd frontend && npm install && npm run build && cd ..
cd backend && uv sync
uv run mtgdm sync                                  # download Scryfall data (~2 min)
uv run mtgdm app                                   # native window (pywebview)
uv run mtgdm serve --host 0.0.0.0 --port 8765      # or as a web server
```

- Live reload: `scripts/dev.sh`, then open http://localhost:5173 (Vite proxies `/api` to the backend).
- Tests: `cd backend && uv run pytest`. Lint: `uvx ruff check mtgdm tests ../scripts` and
  `cd frontend && npm run lint`.
- Project layout and conventions: [CLAUDE.md](CLAUDE.md).

Stack: Python 3.12, FastAPI and SQLite (FTS5) in the backend; React, TypeScript and Vite in the
frontend; OpenCV and Apple Vision / RapidOCR for scanning; pywebview for the window; PyInstaller
for packaging.

## Building the apps

### macOS

```sh
scripts/build_macos.sh
```

Builds `dist/MTG Deck Manager.app` and `dist/MTG-Deck-Manager-<version>-<arch>.dmg` for the Mac it runs
on. The first build compiles a minimal OpenCV (`scripts/build_opencv.py`): a few minutes, cached in
`build/opencv-slim/`, needs the Xcode command line tools. The app is signed ad hoc for local use.

**Signing for distribution (Developer ID + notarization).** Anyone with an Apple Developer account
can sign and notarize a built app:

```sh
security find-identity -v -p codesigning            # find "Developer ID Application: … (TEAMID)"
xcrun notarytool store-credentials mtgdm-notary --apple-id YOU@EXAMPLE.COM --team-id TEAMID
SIGN_IDENTITY="Developer ID Application: … (TEAMID)" NOTARY_PROFILE=mtgdm-notary \
  scripts/sign_macos.sh "dist/MTG Deck Manager.app" MTG-Deck-Manager.dmg
```

The script does the following:
- signs every binary with the hardened runtime;
- notarizes and staples the app;
- builds, signs, notarizes and staples the DMG.

The result opens on any Mac with a double click. On rejection the script prints Apple's notary log.

### Windows

Needs uv, Node.js and Visual Studio's C++ build tools (for the minimal OpenCV):

```powershell
powershell -File scripts\build_windows.ps1
```

Builds `dist\MTG Deck Manager\MTG Deck Manager.exe` and a zip of that folder.

### CI and releases

`.github/workflows/build.yml` runs the tests on Linux and Windows. It then builds and smoke-tests the
macOS arm64, macOS x86_64 and Windows x64 packages (`scripts/smoke_test.py`).

To release, bump `__version__` in `backend/mtgdm/__init__.py`, commit, and push a matching tag:

```sh
git tag v0.2.0 && git push origin v0.2.0
```

The tag build publishes a GitHub Release with the DMGs and the Windows zip attached.

## Data

The data directory holds the database, image cache, scans and logs:
- macOS: `~/Library/Application Support/MTGDeckManager/`
- Windows: `%APPDATA%\MTGDeckManager\`

Override it with `MTGDM_DATA_DIR`. **Settings → Backup** saves your collection, locations and decks
(with their history) as one JSON file.

## License

Copyright © 2026 Wojciech Jaros. Licensed under the [GNU General Public License v3.0 or later](LICENSE):
you are free to use, study, change and share the app. Anything you distribute that is based on it
must keep this notice and be shared under the same license, with its source code.

Third-party components and data: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Legal

Card data and images come from [Scryfall](https://scryfall.com) and follow its API guidelines:
cached locally, never altered. This app is not affiliated with or endorsed by Scryfall.

MTG Deck Manager is unofficial Fan Content permitted under the
[Fan Content Policy](https://company.wizards.com/en/legal/fancontentpolicy). It is not approved or
endorsed by Wizards. Portions of the materials used are property of Wizards of the Coast.
©Wizards of the Coast LLC.
