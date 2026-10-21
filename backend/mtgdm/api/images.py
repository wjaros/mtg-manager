from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse

from mtgdm.api.deps import Db
from mtgdm.scryfall.client import ScryfallError
from mtgdm.scryfall.images import ImageCache, ImageNotAvailable, ImageSize

router = APIRouter(tags=["images"])


@router.get("/images/{card_id}/{size}", response_class=FileResponse)
def card_image(
    request: Request,
    db: Db,
    card_id: str,
    size: ImageSize,
    face: Annotated[int, Query(ge=0, le=1)] = 0,
) -> FileResponse:
    """Card image from the local cache; downloaded from Scryfall on first request."""
    cache: ImageCache = request.app.state.image_cache
    try:
        path = cache.get(db, card_id, size, face)
    except ImageNotAvailable as exc:
        raise HTTPException(status_code=404, detail="Image not available") from exc
    except (ScryfallError, httpx.HTTPError) as exc:
        raise HTTPException(status_code=502, detail=f"Image download failed: {exc}") from exc
    # A printing's image practically never changes; let the browser keep it.
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=2592000"})
