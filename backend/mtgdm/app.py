"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import cv2
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from mtgdm import __version__
from mtgdm.api import api_router
from mtgdm.cloud_backup import CloudBackupWriter
from mtgdm.config import Settings, load_settings
from mtgdm.db import connect, migrate
from mtgdm.i18n import LanguageMiddleware
from mtgdm.mtgjson.client import MtgjsonClient
from mtgdm.printing.jobs import PrintJobs, clear_print_dir
from mtgdm.scan.service import Recognizer
from mtgdm.scryfall.client import ScryfallClient
from mtgdm.scryfall.images import ImageCache
from mtgdm.scryfall.manager import SyncManager


def create_app(
    settings: Settings | None = None,
    scryfall: ScryfallClient | None = None,
    mtgjson: MtgjsonClient | None = None,
    github: httpx.Client | None = None,
) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.ensure_dirs()
        clear_print_dir(settings.print_dir)
        conn = connect(settings.db_path)
        try:
            migrate(conn)
        finally:
            conn.close()
        # Backups into a synced folder, when enabled (Settings › Backup).
        writer = CloudBackupWriter(lambda: connect(settings.db_path))
        writer.start()
        try:
            yield
        finally:
            writer.stop()
            app.state.recognizer.close()
            app.state.scryfall.close()
            app.state.mtgjson.close()
            app.state.github.close()

    app = FastAPI(title="MTG Deck Manager", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    # One shared client: it enforces the Scryfall rate limit across all requests.
    app.state.scryfall = scryfall or ScryfallClient()
    app.state.image_cache = ImageCache(settings.images_dir, app.state.scryfall)
    # Precon card lists fetched on demand (Commander decks come with the card data sync).
    app.state.mtgjson = mtgjson or MtgjsonClient()
    # GitHub's releases API: is there a newer version?
    app.state.github = github or httpx.Client(timeout=10.0, follow_redirects=True)
    app.state.sync_manager = SyncManager(settings, app.state.scryfall)
    app.state.print_jobs = PrintJobs(settings.db_path, settings.print_dir, app.state.image_cache)
    app.state.recognizer = Recognizer(settings.db_path, lambda conn: _image_loader(app.state.image_cache, conn))
    app.include_router(api_router)
    app.add_middleware(LanguageMiddleware)
    _mount_frontend(app, settings)
    return app


def _image_loader(cache: ImageCache, conn):
    """Card images for comparing scans with candidate printings; None when unavailable (offline)."""

    def load(card_id: str):
        try:
            return cv2.imread(str(cache.get(conn, card_id, "normal")))
        except Exception:
            return None

    return load


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    dist = settings.frontend_dist
    index = dist / "index.html"
    if not index.is_file():
        # Dev mode without a build: the Vite dev server serves the UI and proxies /api.
        return

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
            return FileResponse(candidate)
        # Client-side routes fall back to the SPA entry point.
        return FileResponse(index)
