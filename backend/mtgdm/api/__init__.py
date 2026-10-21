from fastapi import APIRouter

from mtgdm.api import backup, cards, collection, decks, health, images, importing, scans, sync

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(backup.router)
api_router.include_router(cards.router)
api_router.include_router(collection.router)
api_router.include_router(decks.router)
api_router.include_router(images.router)
api_router.include_router(importing.router)
api_router.include_router(scans.router)
api_router.include_router(sync.router)
