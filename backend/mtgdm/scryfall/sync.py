"""Full sync: Scryfall sets (with icons) first, then cards (cards.set_code references sets), then
MTGJSON's preconstructed decks and Scryfall's function tags (failures there don't fail the card sync)."""

import logging
from dataclasses import dataclass

import httpx

from mtgdm.config import Settings
from mtgdm.db import connect, migrate
from mtgdm.mtgjson.client import MtgjsonClient, MtgjsonError
from mtgdm.mtgjson.precons import sync_precons
from mtgdm.scryfall.bulk import CardSyncResult, sync_cards
from mtgdm.scryfall.client import ScryfallClient, ScryfallError
from mtgdm.scryfall.sets import Progress, sync_sets
from mtgdm.scryfall.tags import sync_tags

log = logging.getLogger(__name__)


@dataclass
class SyncResult:
    sets: int
    cards: CardSyncResult
    precons: int | None = None  # decks fetched from MTGJSON; None when that step failed or was skipped
    tags: int | None = None     # cards with Scryfall function tags; None when fresh, failed or skipped


def run_sync(
    settings: Settings,
    *,
    force: bool = False,
    client: ScryfallClient | None = None,
    on_progress: Progress | None = None,
    mtgjson: MtgjsonClient | None = None,
    precons: bool = True,
) -> SyncResult:
    settings.ensure_dirs()
    conn = connect(settings.db_path)
    own_client = client is None
    client = client or ScryfallClient()
    try:
        migrate(conn)
        if on_progress:
            on_progress("sets", 0, 0)
        sets = sync_sets(conn, client, settings.images_dir, on_progress)
        cards = sync_cards(conn, client, settings.bulk_dir, force=force, on_progress=on_progress)
        fetched = None
        if precons:
            own_mtgjson = mtgjson is None
            mtgjson = mtgjson or MtgjsonClient()
            try:
                fetched = sync_precons(conn, mtgjson, on_progress)
            except (MtgjsonError, KeyError, ValueError):
                log.warning("precon sync failed", exc_info=True)
            finally:
                if own_mtgjson:
                    mtgjson.close()
        tagged = None
        try:
            tagged = sync_tags(conn, client, settings.bulk_dir, on_progress, force=force)
        except (ScryfallError, httpx.HTTPError, ValueError, KeyError):
            log.warning("card tag sync failed", exc_info=True)
        return SyncResult(sets=sets, cards=cards, precons=fetched, tags=tagged)
    finally:
        conn.close()
        if own_client:
            client.close()
