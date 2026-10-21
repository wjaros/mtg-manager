from fastapi.testclient import TestClient

from mtgdm import __version__
from mtgdm.app import create_app
from mtgdm.db.migrations import available_migrations


def test_health(client, settings):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__, "schema_version": available_migrations()[-1][0]}
    assert settings.db_path.is_file()
    for path in (settings.images_dir, settings.scans_dir, settings.bulk_dir):
        assert path.is_dir()


def test_openapi_lists_health(client):
    assert "/api/health" in client.get("/openapi.json").json()["paths"]


def test_without_frontend_build_root_is_404(client):
    assert client.get("/").status_code == 404


def test_serves_frontend_build_with_spa_fallback(settings):
    dist = settings.frontend_dist
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>index</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")

    with TestClient(create_app(settings)) as c:
        assert c.get("/").text == "<html>index</html>"
        assert c.get("/decks/42").text == "<html>index</html>"
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/favicon.svg").text == "<svg/>"
        assert c.get("/api/nope").status_code == 404
        assert c.get("/api/health").status_code == 200
