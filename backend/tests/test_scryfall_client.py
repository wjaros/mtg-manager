import httpx
import pytest

from mtgdm import __version__
from mtgdm.scryfall import ScryfallClient, ScryfallError


class FakeTime:
    """Deterministic clock: sleep() advances the clock instead of waiting."""

    def __init__(self):
        self.now = 1000.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def make_client(handler, fake_time=None, **kwargs) -> tuple[ScryfallClient, FakeTime]:
    fake_time = fake_time or FakeTime()
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = ScryfallClient(http, sleep=fake_time.sleep, clock=fake_time.clock, **kwargs)
    return client, fake_time


def test_sends_required_headers():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"object": "list", "data": []})

    client, _ = make_client(handler)
    client.get_json("/sets")
    assert seen[0].url == "https://api.scryfall.com/sets"
    assert seen[0].headers["User-Agent"] == f"MTGDeckManager/{__version__}"
    assert seen[0].headers["Accept"] == "application/json;q=0.9,*/*;q=0.8"


def test_rate_limit_spaces_api_requests():
    client, t = make_client(lambda r: httpx.Response(200, json={}), min_interval=0.1)
    client.get_json("/a")
    client.get_json("/b")
    t.now += 0.5  # enough time passed, no wait needed
    client.get_json("/c")
    assert t.sleeps == [pytest.approx(0.1)]


def test_stricter_endpoints_wait_longer():
    client, t = make_client(lambda r: httpx.Response(200, json={}), min_interval=0.1)
    client.get_text("/cards/search", {"q": "otag:ramp"})
    client.get_text("/cards/search", {"q": "otag:ramp", "page": 2})  # 2 per second at most
    client.get_json("/sets")
    assert t.sleeps == [pytest.approx(0.5), pytest.approx(0.1)]


def test_429_without_retry_after_waits_out_the_lockout():
    responses = iter([
        httpx.Response(429, json={"object": "error", "details": "slow down"}),
        httpx.Response(200, json={"ok": True}),
    ])
    client, t = make_client(lambda r: next(responses), min_interval=0)
    assert client.get_json("/sets") == {"ok": True}
    assert t.sleeps == [30.0]


def test_retries_429_using_retry_after():
    responses = iter([
        httpx.Response(429, headers={"Retry-After": "2"}, json={"object": "error", "details": "slow down"}),
        httpx.Response(200, json={"ok": True}),
    ])
    client, t = make_client(lambda r: next(responses), min_interval=0)
    assert client.get_json("/cards/named") == {"ok": True}
    assert t.sleeps == [2.0]


def test_retries_5xx_with_exponential_backoff_then_gives_up():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503, json={"object": "error", "code": "unavailable", "details": "down"})

    client, t = make_client(handler, min_interval=0, max_retries=2)
    with pytest.raises(ScryfallError) as exc:
        client.get_json("/sets")
    assert len(calls) == 3
    assert t.sleeps == [1.0, 2.0]
    assert exc.value.status == 503
    assert exc.value.code == "unavailable"


def test_404_raises_without_retry():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404, json={"object": "error", "code": "not_found", "details": "No card found"})

    client, _ = make_client(handler)
    with pytest.raises(ScryfallError, match="No card found"):
        client.get_json("/cards/xyz/1")
    assert len(calls) == 1


def test_iter_list_follows_pagination():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json={"object": "list", "has_more": False, "data": [{"n": 3}]})
        return httpx.Response(200, json={
            "object": "list", "has_more": True, "data": [{"n": 1}, {"n": 2}],
            "next_page": "https://api.scryfall.com/cards/search?q=giada&page=2",
        })

    client, _ = make_client(handler)
    assert [c["n"] for c in client.iter_list("/cards/search", {"q": "giada"})] == [1, 2, 3]


def test_bulk_data_picks_type():
    body = {"object": "list", "has_more": False, "data": [
        {"type": "oracle_cards", "download_uri": "https://data.scryfall.io/oracle.json"},
        {"type": "default_cards", "download_uri": "https://data.scryfall.io/default.json"},
    ]}
    client, _ = make_client(lambda r: httpx.Response(200, json=body))
    assert client.bulk_data("default_cards")["download_uri"].endswith("default.json")
    with pytest.raises(ScryfallError):
        client.bulk_data("nope")


def test_stream_is_not_rate_limited():
    client, t = make_client(lambda r: httpx.Response(200, content=b"x" * 10), min_interval=1.0)
    for _ in range(3):
        with client.stream("https://data.scryfall.io/file.json") as resp:
            assert resp.read() == b"x" * 10
    assert t.sleeps == []


def test_stream_raises_on_error():
    client, _ = make_client(lambda r: httpx.Response(404, text="gone"))
    with pytest.raises(ScryfallError) as exc:
        with client.stream("https://cards.scryfall.io/x.jpg"):
            pass
    assert exc.value.status == 404
