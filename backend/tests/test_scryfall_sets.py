import httpx

from mtgdm.scryfall import ScryfallClient
from mtgdm.scryfall.sets import icon_filename, sync_sets

SETS = [
    {"object": "set", "code": "dom", "arena_code": "dar", "mtgo_code": "dom", "name": "Dominaria",
     "set_type": "expansion", "released_at": "2018-04-27", "digital": False,
     "icon_svg_uri": "https://svgs.scryfall.io/sets/dom.svg?1700000000"},
    {"object": "set", "code": "tdom", "name": "Dominaria Tokens", "set_type": "token",
     "released_at": "2018-04-27", "digital": False,
     "icon_svg_uri": "https://svgs.scryfall.io/sets/dom.svg?1700000000"},
    {"object": "set", "code": "y22", "name": "Alchemy: Innistrad", "set_type": "alchemy",
     "released_at": "2021-12-09", "digital": True,
     "icon_svg_uri": "https://svgs.scryfall.io/sets/y22.svg?1700000000"},
]


class FakeScryfall:
    def __init__(self, sets=SETS, broken_icons=()):
        self.sets = sets
        self.broken_icons = set(broken_icons)
        self.icon_requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.scryfall.com" and request.url.path == "/sets":
            return httpx.Response(200, json={"object": "list", "has_more": False, "data": self.sets})
        if request.url.host == "svgs.scryfall.io":
            name = request.url.path.rsplit("/", 1)[-1]
            self.icon_requests.append(name)
            if name in self.broken_icons:
                return httpx.Response(500, text="boom")
            return httpx.Response(200, content=f"<svg id='{name}'/>".encode())
        return httpx.Response(404, json={"object": "error", "details": "unexpected"})


def make_client(fake) -> ScryfallClient:
    return ScryfallClient(httpx.Client(transport=httpx.MockTransport(fake)), min_interval=0)


def test_icon_filename():
    assert icon_filename("https://svgs.scryfall.io/sets/mdd.svg?1792382400") == "mdd.svg"


def test_sync_sets_stores_rows_and_icons(db, tmp_path):
    fake = FakeScryfall()
    progress = []
    count = sync_sets(db, make_client(fake), tmp_path, on_progress=lambda *a: progress.append(a))

    assert count == 3
    rows = {r["code"]: dict(r) for r in db.execute("SELECT * FROM sets")}
    assert rows["dom"]["arena_code"] == "dar"
    assert rows["dom"]["icon_path"] == "sets/dom.svg"
    assert rows["tdom"]["icon_path"] == "sets/dom.svg"
    assert rows["y22"]["digital"] == 1
    assert rows["tdom"]["arena_code"] is None
    assert (tmp_path / "sets" / "dom.svg").read_text(encoding="utf-8") == "<svg id='dom.svg'/>"
    # Shared icon downloaded once.
    assert sorted(fake.icon_requests) == ["dom.svg", "y22.svg"]
    assert progress[-1] == ("set_icons", 2, 2)
    assert db.execute("SELECT value FROM meta WHERE key = 'sets_synced_at'").fetchone()


def test_resync_updates_and_skips_existing_icons(db, tmp_path):
    sync_sets(db, make_client(FakeScryfall()), tmp_path)
    renamed = [dict(SETS[0], name="Dominaria (renamed)"), *SETS[1:]]
    fake = FakeScryfall(sets=renamed)
    sync_sets(db, make_client(fake), tmp_path)

    assert fake.icon_requests == []
    assert db.execute("SELECT name FROM sets WHERE code = 'dom'").fetchone()[0] == "Dominaria (renamed)"
    assert db.execute("SELECT COUNT(*) FROM sets").fetchone()[0] == 3


def test_broken_icon_does_not_fail_sync(db, tmp_path):
    sync_sets(db, make_client(FakeScryfall(broken_icons={"y22.svg"})), tmp_path)

    assert db.execute("SELECT icon_path FROM sets WHERE code = 'y22'").fetchone()[0] is None
    assert not list((tmp_path / "sets").glob("*.part"))
    # Next sync retries the missing icon.
    fake = FakeScryfall()
    sync_sets(db, make_client(fake), tmp_path)
    assert fake.icon_requests == ["y22.svg"]
    assert db.execute("SELECT icon_path FROM sets WHERE code = 'y22'").fetchone()[0] == "sets/y22.svg"
