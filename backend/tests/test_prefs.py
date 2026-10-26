from mtgdm import prefs


def test_prefs_round_trip(client):
    assert client.get("/api/prefs").json() == {"values": {}, "scale": 1.0, "native_zoom": False, "open_urls": False}

    assert client.put("/api/prefs", json={"key": "mtgdm.deckView.mode", "value": "spoiler"}).status_code == 204
    assert client.put("/api/prefs", json={"key": "mtgdm.lang", "value": "en"}).status_code == 204
    assert client.get("/api/prefs").json()["values"] == {"mtgdm.deckView.mode": "spoiler", "mtgdm.lang": "en"}

    # No value removes the preference.
    assert client.put("/api/prefs", json={"key": "mtgdm.lang"}).status_code == 204
    assert client.get("/api/prefs").json()["values"] == {"mtgdm.deckView.mode": "spoiler"}


def test_prefs_are_apart_from_other_meta(client, settings):
    from mtgdm.db import connect

    conn = connect(settings.db_path)
    with conn:
        conn.execute("INSERT INTO meta(key, value) VALUES ('cardtrader_token', 'secret')")
    conn.close()
    client.put("/api/prefs", json={"key": "a", "value": "1"})
    assert client.get("/api/prefs").json()["values"] == {"a": "1"}


def test_scale(client):
    body = client.put("/api/prefs/scale", json={"scale": 1.25}).json()
    assert body["scale"] == 1.25
    assert body["values"] == {}  # the scale is not one of the plain values
    assert client.get("/api/prefs").json()["scale"] == 1.25

    assert client.put("/api/prefs/scale", json={"scale": 5}).status_code == 422
    assert client.put("/api/prefs/scale", json={"scale": 0.1}).status_code == 422


def test_scale_zooms_the_window(client):
    zoomed: list[float] = []
    prefs.set_window_zoom(zoomed.append)
    try:
        body = client.put("/api/prefs/scale", json={"scale": 1.5}).json()
        assert body["native_zoom"] is True
        assert zoomed == [1.5]
    finally:
        prefs.set_window_zoom(None)
    assert client.get("/api/prefs").json()["native_zoom"] is False


def test_bad_stored_scale_falls_back(db):
    prefs.set_pref(db, prefs.SCALE_KEY, "big")
    assert prefs.get_scale(db) == 1.0
    prefs.set_pref(db, prefs.SCALE_KEY, "9")
    assert prefs.get_scale(db) == prefs.MAX_SCALE
