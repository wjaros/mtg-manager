import httpx
import pytest
from fastapi.testclient import TestClient

from mtgdm import updates
from mtgdm.app import create_app

NOTES = """Download the file for your system:
- **macOS**: `…-arm64.dmg`

## What's changed

### Precons from MTGJSON (#4)

Find a precon by name."""


def release(tag: str, body: str = NOTES, **extra) -> dict:
    version = tag.lstrip("v")
    return {
        "tag_name": tag, "html_url": f"https://github.com/x/releases/tag/{tag}", "published_at": "2026-10-23T10:00:00Z",
        "body": body, "draft": False, "prerelease": False,
        "assets": [{"name": f"MTG-Deck-Manager-{version}{s}", "browser_download_url": f"https://dl/{version}{s}", "size": 1}
                   for s in ("-arm64.dmg", "-x86_64.dmg", "-windows-x64.zip")],
        **extra,
    }


class FakeGitHub:
    def __init__(self, releases: list[dict], status: int = 200):
        self.releases, self.status, self.calls = releases, status, 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        assert request.url.path == "/repos/wjaros/mtg-manager/releases"
        return httpx.Response(self.status, json=self.releases if self.status == 200 else {"message": "rate limited"})


@pytest.fixture
def make_client(settings, monkeypatch):
    monkeypatch.setattr(updates, "__version__", "0.1.8")
    monkeypatch.setattr(updates, "asset_suffix", lambda: "-arm64.dmg")
    clients = []

    def make(fake: FakeGitHub) -> TestClient:
        client = TestClient(create_app(settings, github=httpx.Client(transport=httpx.MockTransport(fake))))
        client.__enter__()
        clients.append(client)
        return client

    yield make
    for c in clients:
        c.__exit__(None, None, None)


def test_newer_release_with_changes_and_download(make_client):
    fake = FakeGitHub([release("v0.1.10"), release("v0.1.9", body="## What's Changed\n* Old style by @me"),
                       release("v0.1.8"), release("v0.2.0-beta", prerelease=True)])
    info = make_client(fake).get("/api/updates").json()
    assert (info["current"], info["latest"], info["newer"]) == ("0.1.8", "0.1.10", True)  # 10 > 9 as numbers
    assert info["download"] == {"name": "MTG-Deck-Manager-0.1.10-arm64.dmg", "url": "https://dl/0.1.10-arm64.dmg", "size": 1}
    assert [r["version"] for r in info["releases"]] == ["0.1.10", "0.1.9"]  # every newer one, not the beta
    assert info["releases"][0]["notes"].startswith("### Precons from MTGJSON (#4)")  # no download instructions
    assert info["releases"][1]["notes"] == "* Old style by @me"


def test_checked_at_most_every_few_hours(make_client):
    fake = FakeGitHub([release("v0.1.8")])
    client = make_client(fake)
    assert client.get("/api/updates").json()["newer"] is False
    client.get("/api/updates")
    assert fake.calls == 1  # cached
    client.get("/api/updates", params={"force": True})
    assert fake.calls == 2


def test_disabled_and_offline(make_client):
    fake = FakeGitHub([], status=403)
    client = make_client(fake)
    info = client.get("/api/updates").json()
    assert info["error"] and info["newer"] is False
    off = client.put("/api/updates/settings", json={"enabled": False}).json()
    assert off["enabled"] is False
    calls = fake.calls
    client.get("/api/updates")
    assert fake.calls == calls  # no requests while disabled


def test_versions_and_assets():
    assert updates.version_tuple("v0.1.10") > updates.version_tuple("0.1.9")
    assert updates.asset_suffix("darwin", "arm64") == "-arm64.dmg"
    assert updates.asset_suffix("darwin", "x86_64") == "-x86_64.dmg"
    assert updates.asset_suffix("win32", "AMD64") == "-windows-x64.zip"
    assert updates.asset_suffix("linux", "x86_64") is None


def test_skip_a_version(make_client):
    fake = FakeGitHub([release("v0.1.9"), release("v0.1.8")])
    client = make_client(fake)
    assert client.get("/api/updates").json()["skipped"] is False
    info = client.post("/api/updates/skip", json={"version": "0.1.9"}).json()
    assert info["newer"] is True and info["skipped"] is True  # still listed in Settings
    # A newer release is shown again.
    fake.releases = [release("v0.1.10"), *fake.releases]
    again = client.get("/api/updates", params={"force": True}).json()
    assert (again["latest"], again["skipped"]) == ("0.1.10", False)
