"""HTTP client following Scryfall's API rules (https://scryfall.com/docs/api).

- Custom User-Agent and Accept headers on every request.
- api.scryfall.com: at least MIN_INTERVAL between requests (more before the endpoints with stricter
  limits, https://scryfall.com/docs/api/rate-limits), retry on 429/5xx with backoff.
- *.scryfall.io (bulk files, images): no rate limit, fetched via stream().
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx

from mtgdm import APP_NAME, __version__

API_BASE = "https://api.scryfall.com"
USER_AGENT = f"{APP_NAME}/{__version__}"
ACCEPT = "application/json;q=0.9,*/*;q=0.8"

MIN_INTERVAL = 0.1  # seconds between api.scryfall.com requests (10 req/s)
# Scryfall's hard limits of single endpoints, as seconds between requests.
ENDPOINT_INTERVALS = {
    "/cards/search": 0.5, "/cards/named": 0.5, "/cards/random": 0.5, "/cards/collection": 0.5,
    "/cards/manifest": 6.0,
}
MAX_RETRIES = 4
BACKOFF_BASE = 1.0  # seconds, doubled per retry unless Retry-After says otherwise
RATE_LIMITED_PAUSE = 30.0  # a 429 locks the client out for 30 s (unless Retry-After says otherwise)
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ScryfallError(Exception):
    """Non-retryable error response, carrying Scryfall's error object when present."""

    def __init__(self, status: int, details: str, code: str | None = None):
        super().__init__(f"Scryfall {status}: {details}")
        self.status = status
        self.details = details
        self.code = code


class ScryfallClient:
    def __init__(
        self,
        http: httpx.Client | None = None,
        *,
        min_interval: float = MIN_INTERVAL,
        max_retries: int = MAX_RETRIES,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._http = http or httpx.Client(timeout=httpx.Timeout(30.0, read=120.0), follow_redirects=True)
        self._http.headers.update({"User-Agent": USER_AGENT, "Accept": ACCEPT})
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._last_request: float | None = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "ScryfallClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- api.scryfall.com -------------------------------------------------

    def get_json(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET a JSON object from the API, honouring the rate limit and retrying 429/5xx."""
        url = path_or_url if path_or_url.startswith("http") else API_BASE + path_or_url
        for attempt in range(self._max_retries + 1):
            self._wait_for_slot(url)
            resp = self._http.get(url, params=params)
            if resp.status_code in RETRY_STATUSES and attempt < self._max_retries:
                self._sleep(_retry_delay(resp, attempt))
                continue
            if resp.is_error:
                raise _error_from(resp)
            return resp.json()
        raise AssertionError("unreachable")

    def get_text(self, path_or_url: str, params: dict[str, Any] | None = None) -> str:
        """GET a non-JSON response (e.g. search results as CSV), with the same rate limit and retries."""
        url = path_or_url if path_or_url.startswith("http") else API_BASE + path_or_url
        for attempt in range(self._max_retries + 1):
            self._wait_for_slot(url)
            resp = self._http.get(url, params=params)
            if resp.status_code in RETRY_STATUSES and attempt < self._max_retries:
                self._sleep(_retry_delay(resp, attempt))
                continue
            if resp.is_error:
                raise _error_from(resp)
            return resp.text
        raise AssertionError("unreachable")

    def iter_list(self, path_or_url: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """Iterate items of a paginated list object, following next_page."""
        page = self.get_json(path_or_url, params)
        while True:
            yield from page.get("data", [])
            if not page.get("has_more"):
                return
            # next_page already carries the query string.
            page = self.get_json(page["next_page"])

    def bulk_data(self, bulk_type: str) -> dict[str, Any]:
        """Metadata (download_uri, updated_at, size) of one bulk data file, e.g. 'default_cards'."""
        for item in self.iter_list("/bulk-data"):
            if item.get("type") == bulk_type:
                return item
        raise ScryfallError(404, f"bulk data type {bulk_type!r} not found")

    # --- *.scryfall.io (bulk files, images, set icons) ---------------------

    @contextmanager
    def stream(self, url: str) -> Iterator[httpx.Response]:
        """Stream a file download; not rate limited (Scryfall CDN)."""
        with self._http.stream("GET", url) as resp:
            if resp.is_error:
                resp.read()
                raise _error_from(resp)
            yield resp

    def _wait_for_slot(self, url: str) -> None:
        interval = max(self._min_interval, ENDPOINT_INTERVALS.get(httpx.URL(url).path, 0.0))
        with self._lock:
            now = self._clock()
            if self._last_request is not None:
                remaining = interval - (now - self._last_request)
                if remaining > 0:
                    self._sleep(remaining)
                    now += remaining
            self._last_request = now


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass  # HTTP-date form; fall back to the defaults below
    if resp.status_code == 429:
        return RATE_LIMITED_PAUSE
    return BACKOFF_BASE * 2**attempt


def _error_from(resp: httpx.Response) -> ScryfallError:
    try:
        body = resp.json()
    except ValueError:
        return ScryfallError(resp.status_code, resp.text[:200] or resp.reason_phrase)
    if isinstance(body, dict) and body.get("object") == "error":
        return ScryfallError(resp.status_code, body.get("details", ""), body.get("code"))
    return ScryfallError(resp.status_code, resp.reason_phrase)
