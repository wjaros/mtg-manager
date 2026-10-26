"""Screenshots for the user guide (docs/images/{pl,en}/<name>.webp, 1440×900), taken from the app on a
copy of the data; the README's (docs/screenshots) are the English ones of README_SHOTS.

    cd frontend && npm run build && cd ../backend
    uv run --with playwright python ../scripts/docs_screenshots.py            # every shot
    uv run --with playwright python ../scripts/docs_screenshots.py --only stats,history --lang pl

Playwright needs a Chromium once: `uv run --with playwright playwright install chromium`.

The copy: the database through SQLite's backup API (the app may be running), the image cache linked
(new images just land in the cache); the cloud backup off and the CardTrader token dropped, so
nothing leaves the copy; the UI prefs cleared before each shot, so each shows the defaults. Decks
are found by name (DECKS); a shot whose deck is missing is skipped. Add a shot: a function taking
the page, the base URL and the decks (returning an element to crop to, or None), in SHOTS.
"""

import argparse
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from json import loads
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
IMAGES = ROOT / "docs" / "images"
README_IMAGES = ROOT / "docs" / "screenshots"
README_SHOTS = {"deckbuilder", "stats", "history", "missing"}
LOCALES = {"pl": "pl-PL", "en": "en-US"}
VIEWPORT = {"width": 1440, "height": 900}

# Decks the shots use, by a part of their name; "arena" is the Arena deck compared with "lorehold".
DECKS = {"giada": "Giada, Font of Hope", "lorehold": "Quintorius – Lorehold Spirit"}


def copy_data(source: Path, target: Path) -> None:
    target.mkdir(parents=True)
    src = sqlite3.connect(source / "db.sqlite")
    dst = sqlite3.connect(target / "db.sqlite")
    with dst:
        src.backup(dst)
        dst.execute("UPDATE meta SET value = '0' WHERE key = 'cloud_backup_enabled'")
        dst.execute("UPDATE meta SET value = '' WHERE key = 'cloud_backup_folder'")
        dst.execute("DELETE FROM meta WHERE key LIKE '%token%' OR key LIKE 'ui:%'")
    src.close()
    dst.close()
    if (source / "images").exists():
        (target / "images").symlink_to(source / "images", target_is_directory=True)


def reset_prefs(data: Path) -> None:
    """Every shot starts from the default UI (a shot may change the layout, which is remembered)."""
    conn = sqlite3.connect(data / "db.sqlite")
    with conn:
        conn.execute("DELETE FROM meta WHERE key LIKE 'ui:%'")
    conn.close()


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get_json(url: str):
    with urllib.request.urlopen(url) as resp:
        return loads(resp.read())


def find_decks(base: str) -> dict[str, int]:
    decks = get_json(f"{base}/api/decks")
    found = {key: d["id"] for key, name in DECKS.items() for d in decks if name in d["name"]}
    arena = next((d for d in decks if d["platform"] == "arena"), None)
    if arena:
        found["arena"] = arena["id"]
    return found


def settle(page: Page, ms: int = 1500) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


# ---------- shots: (page, base url, decks) -> element to crop to, or None for the whole window ----------


def deckbuilder(page, base, decks):
    page.goto(f"{base}/#/decks/{decks['giada']}")
    page.wait_for_selector(".deck-preview img")
    settle(page, 2500)


def deckbuilder_light(page, base, decks):
    page.emulate_media(color_scheme="light")
    deckbuilder(page, base, decks)


def deck_spoiler(page, base, decks):
    deckbuilder(page, base, decks)
    page.click(".columns-toggle button:has-text('▴')")
    page.click(".columns-mode button >> nth=1")
    page.wait_for_selector(".deck-spoiler-grid .stack-card")
    page.locator(".deck-spoiler-grid .stack-card").nth(4).hover()
    settle(page, 2500)


def deck_tab(tab: str, deck: str = "giada"):
    def shot(page, base, decks):
        page.goto(f"{base}/#/decks/{decks[deck]}/{tab}")
        page.wait_for_selector(".deck-preview img")
        settle(page, 3000)

    shot.deck = deck
    return shot


def compare(view: int, sort: str | None = None, hover: bool = False):
    def shot(page, base, decks):
        page.goto(f"{base}/#/decks/{decks['lorehold']}/compare")
        page.wait_for_selector(".compare-toolbar")
        page.locator(".compare-toolbar select").first.select_option(str(decks["arena"]))
        page.locator(".compare-toolbar .segmented").first.locator("button").nth(view).click()
        if sort:
            page.locator(".compare-toolbar select").nth(1).select_option(sort)
        settle(page)
        if hover:
            page.locator(".compare-name").nth(3).hover()
            settle(page, 800)

    shot.deck = "arena"
    return shot


def settings_panel(index: int, window_app: bool = False):
    def shot(page, base, decks):
        if window_app:
            # As in the window app, which zooms its web view: the interface size buttons, not the browser hint.
            def native(route):
                body = route.fetch().json()
                route.fulfill(json={**body, "native_zoom": True})

            page.route(f"{base}/api/prefs", native)
        page.goto(f"{base}/#/settings")
        settle(page)
        return page.locator(".view.settings section.panel").nth(index)

    return shot


SHOTS: dict[str, Callable] = {
    "deckbuilder": deckbuilder,
    "deckbuilder-light": deckbuilder_light,
    "deck-spoiler": deck_spoiler,
    "stats": deck_tab("stats"),
    "combos": deck_tab("combos"),
    "history": deck_tab("history"),
    "missing": deck_tab("missing", "lorehold"),
    "compare-side": compare(0, hover=True),
    "compare": compare(1, sort="price-desc"),
    "compare-diff": compare(2, sort="mv-desc"),
    "settings-appearance": settings_panel(1, window_app=True),
    "settings-card-data": settings_panel(2),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", help="comma-separated shot names: " + ", ".join(SHOTS))
    parser.add_argument("--lang", choices=sorted(LOCALES), help="one language (default: both)")
    parser.add_argument("--data", type=Path, help="data directory to copy (default: the app's)")
    args = parser.parse_args()

    from mtgdm.config import load_settings

    names = args.only.split(",") if args.only else list(SHOTS)
    unknown = [n for n in names if n not in SHOTS]
    if unknown:
        parser.error(f"unknown shots: {', '.join(unknown)}")
    langs = [args.lang] if args.lang else list(LOCALES)

    with tempfile.TemporaryDirectory(prefix="mtgdm-shots-") as tmp:
        data = Path(tmp) / "data"
        copy_data(args.data or load_settings().data_dir, data)
        port = free_port()
        base = f"http://127.0.0.1:{port}"
        server = subprocess.Popen(
            [sys.executable, "-m", "mtgdm", "serve", "--port", str(port)],
            env={**os.environ, "MTGDM_DATA_DIR": str(data)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(120):
                try:
                    get_json(f"{base}/api/prefs")
                    break
                except OSError:
                    time.sleep(0.5)
            decks = find_decks(base)
            with sync_playwright() as p:
                browser = p.chromium.launch()
                for lang in langs:
                    for name in names:
                        shot = SHOTS[name]
                        needs = [k for k in ("giada", getattr(shot, "deck", None)) if k]
                        if name.startswith("deck") or getattr(shot, "deck", None):
                            missing = [k for k in needs if k not in decks]
                            if missing:
                                print(f"skip {lang}/{name}: no deck for {', '.join(missing)}")
                                continue
                        reset_prefs(data)
                        context = browser.new_context(viewport=VIEWPORT, locale=LOCALES[lang], color_scheme="dark")
                        page = context.new_page()
                        png = Path(tmp) / f"{lang}-{name}.png"
                        element = shot(page, base, decks)
                        (element or page).screenshot(path=png)
                        context.close()
                        target = IMAGES / lang / f"{name}.webp"
                        targets = [target] + ([README_IMAGES / target.name] if lang == "en" and name in README_SHOTS else [])
                        for path in targets:
                            Image.open(png).convert("RGB").save(path, "WEBP", quality=80, method=6)
                            print(f"{path.relative_to(ROOT)}  {Image.open(path).size}")
                browser.close()
        finally:
            server.terminate()
            server.wait(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
