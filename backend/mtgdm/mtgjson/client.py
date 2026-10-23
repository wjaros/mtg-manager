"""Small HTTP client for MTGJSON's static JSON files: own User-Agent, a pause between requests
(the files come from a CDN, but a sync fetches a few hundred of them) and retries on 429/5xx."""

import time
from collections.abc import Callable
from typing import Any

import httpx

from mtgdm import APP_NAME, __version__

API_BASE = "https://mtgjson.com/api/v5"
MIN_INTERVAL = 0.1
MAX_RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}


class MtgjsonError(Exception):
    pass


class MtgjsonClient:
    def __init__(self, http: httpx.Client | None = None, *, min_interval: float = MIN_INTERVAL,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self._http = http or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True)
        self._http.headers.update({"User-Agent": f"{APP_NAME}/{__version__}", "Accept": "application/json"})
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def close(self) -> None:
        self._http.close()

    def get_json(self, path: str) -> dict[str, Any]:
        """GET <API_BASE>/<path>; MTGJSON wraps every file as {"meta": ..., "data": ...}."""
        url = f"{API_BASE}/{path.lstrip('/')}"
        for attempt in range(MAX_RETRIES + 1):
            if self._last is not None:
                wait = self._min_interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            try:
                resp = self._http.get(url)
            except httpx.HTTPError as exc:
                if attempt < MAX_RETRIES:
                    self._sleep(2 ** attempt)
                    continue
                raise MtgjsonError(f"MTGJSON: {exc}") from exc
            if resp.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                self._sleep(2 ** attempt)
                continue
            if resp.is_error:
                raise MtgjsonError(f"MTGJSON {resp.status_code}: {url}")
            return resp.json()
        raise AssertionError("unreachable")
