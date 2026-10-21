import string

import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.i18n import LANGS, MESSAGES, current_lang, parse_accept_language, set_lang, tr


def placeholders(template: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


@pytest.mark.parametrize("key", sorted(MESSAGES))
def test_catalog_is_complete(key):
    entry = MESSAGES[key]
    assert set(entry) == set(LANGS)
    assert placeholders(entry["pl"]) == placeholders(entry["en"])


@pytest.mark.parametrize(("header", "lang"), [
    (None, "pl"), ("", "pl"), ("en", "en"), ("en-US,en;q=0.9", "en"), ("pl-PL", "pl"), ("de-DE,en;q=0.5", "en"),
    ("fr", "pl"),
])
def test_accept_language(header, lang):
    assert parse_accept_language(header) == lang


def test_tr_uses_the_context_language():
    assert current_lang() == "pl"
    token = set_lang("en")
    try:
        assert tr("no_commander") == "The deck has no commander."
    finally:
        from mtgdm.i18n import _lang
        _lang.reset(token)
    assert tr("no_commander") == "Talia nie ma dowódcy."


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


def test_api_messages_follow_accept_language(client):
    deck = client.post("/api/decks", json={"name": "Empty", "format": "commander"}).json()
    issues = lambda lang: {i["code"]: i["message"] for i in client.get(  # noqa: E731
        f"/api/decks/{deck['id']}/validate", headers={"Accept-Language": lang}).json()["issues"]}
    assert issues("en")["no_commander"] == "The deck has no commander."
    assert issues("pl")["no_commander"] == "Talia nie ma dowódcy."

    bad = client.get("/api/cards", params={"q": "foo:bar"}, headers={"Accept-Language": "en"})
    assert bad.status_code == 422 and bad.json()["detail"] == "Unknown filter “foo:”"
    # The language doesn't leak into the next request.
    assert client.get("/api/cards", params={"q": "foo:bar"}).json()["detail"] == "Nieznany filtr „foo:”"
