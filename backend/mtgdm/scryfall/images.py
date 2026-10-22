"""Local cache of card images (Scryfall's rules: cached, never hotlinked or altered).

Files: <images>/cards/<size>/<id[:2]>/<id>-<face>.jpg (.png for "png": 745 x 1040, transparent corners,
used for printing), downloaded on first request.
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Literal

from mtgdm.scryfall.client import ScryfallClient

ImageSize = Literal["small", "normal", "large", "art_crop", "png"]


class ImageNotAvailable(LookupError):
    """The card does not exist or has no image for that face."""


class ImageCache:
    def __init__(self, images_dir: Path, client: ScryfallClient):
        self._root = images_dir / "cards"
        self._client = client
        self._locks: dict[Path, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def path_for(self, card_id: str, size: ImageSize, face: int) -> Path:
        return self._root / size / card_id[:2] / f"{card_id}-{face}.{'png' if size == 'png' else 'jpg'}"

    def get(self, conn: sqlite3.Connection, card_id: str, size: ImageSize, face: int = 0) -> Path:
        """Return the cached file, downloading it first if needed."""
        target = self.path_for(card_id, size, face)
        if target.is_file():
            return target

        url = image_url(conn, card_id, size, face)
        # One download per file even when the grid requests it several times at once.
        with self._lock_for(target):
            if target.is_file():
                return target
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".part")
            try:
                with self._client.stream(url) as resp, tmp.open("wb") as f:
                    for chunk in resp.iter_bytes():
                        f.write(chunk)
                tmp.replace(target)
            finally:
                tmp.unlink(missing_ok=True)
        return target

    def _lock_for(self, path: Path) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(path, threading.Lock())


def image_url(conn: sqlite3.Connection, card_id: str, size: ImageSize, face: int) -> str:
    row = conn.execute("SELECT image_uris, card_faces FROM card_details WHERE id = ?", (card_id,)).fetchone()
    if row is None:
        raise ImageNotAvailable(card_id)
    uris = json.loads(row["image_uris"]) if row["image_uris"] else None
    if uris is None:
        # Transform / MDFC cards have one image per face.
        faces = json.loads(row["card_faces"]) if row["card_faces"] else []
        uris = faces[face].get("image_uris") if face < len(faces) else None
    elif face != 0:
        uris = None
    if not uris or not uris.get(size):
        raise ImageNotAvailable(f"{card_id} face {face}")
    return uris[size]
