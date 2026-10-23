"""Client for Commander Spellbook's find-my-combos endpoint: own User-Agent, a pause between requests,
retries on 429/5xx, and answers cached in memory per card list (a deck's combos are asked for again
whenever the tab opens; the service asks for sparse requests)."""

import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import httpx

from mtgdm import APP_NAME, __version__

API_BASE = "https://backend.commanderspellbook.com"
MIN_INTERVAL = 1.0
MAX_RETRIES = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
CACHE_TTL = 24 * 3600
CACHE_SIZE = 64


class SpellbookError(Exception):
    pass


class SpellbookClient:
    def __init__(self, http: httpx.Client | None = None, *, min_interval: float = MIN_INTERVAL,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic):
        self._http = http or httpx.Client(timeout=httpx.Timeout(30.0, read=60.0), follow_redirects=True)
        self._http.headers.update({"User-Agent": f"{APP_NAME}/{__version__}", "Accept": "application/json"})
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self._cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

    def close(self) -> None:
        self._http.close()

    def find_my_combos(self, commanders: list[tuple[str, int]], main: list[tuple[str, int]]) -> dict[str, Any]:
        """The `results` of POST /find-my-combos for (name, quantity) lists."""
        body = {
            "commanders": [{"card": name, "quantity": qty} for name, qty in commanders],
            "main": [{"card": name, "quantity": qty} for name, qty in main],
        }
        key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        cached = self._cache.get(key)
        if cached and self._clock() - cached[0] < CACHE_TTL:
            self._cache.move_to_end(key)
            return cached[1]
        results = self._post(f"{API_BASE}/find-my-combos", body)["results"]
        self._cache[key] = (self._clock(), results)
        while len(self._cache) > CACHE_SIZE:
            self._cache.popitem(last=False)
        return results

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(MAX_RETRIES + 1):
            if self._last is not None:
                wait = self._min_interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
            try:
                resp = self._http.post(url, json=body)
            except httpx.HTTPError as exc:
                if attempt < MAX_RETRIES:
                    self._sleep(2 ** attempt)
                    continue
                raise SpellbookError(f"Commander Spellbook: {exc}") from exc
            if resp.status_code in RETRY_STATUSES and attempt < MAX_RETRIES:
                retry_after = resp.headers.get("Retry-After", "")
                self._sleep(float(retry_after) if retry_after.isdigit() else 2 ** (attempt + 1))
                continue
            if resp.is_error:
                raise SpellbookError(f"Commander Spellbook {resp.status_code}")
            return resp.json()
        raise AssertionError("unreachable")
