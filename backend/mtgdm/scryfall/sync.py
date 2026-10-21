"""Full Scryfall sync: sets (with icons) first, then cards (cards.set_code references sets)."""

from dataclasses import dataclass

from mtgdm.config import Settings
from mtgdm.db import connect, migrate
from mtgdm.scryfall.bulk import CardSyncResult, sync_cards
from mtgdm.scryfall.client import ScryfallClient
from mtgdm.scryfall.sets import Progress, sync_sets


@dataclass
class SyncResult:
    sets: int
    cards: CardSyncResult


def run_sync(
    settings: Settings,
    *,
    force: bool = False,
    client: ScryfallClient | None = None,
    on_progress: Progress | None = None,
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
        return SyncResult(sets=sets, cards=cards)
    finally:
        conn.close()
        if own_client:
            client.close()
