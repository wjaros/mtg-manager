import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.cards.search import FORMATS
from mtgdm.cards.syntax import QuerySyntaxError, parse_syntax


@pytest.fixture(scope="module")
def client(tmp_path_factory, card_db_template):
    import shutil

    from mtgdm.config import Settings

    tmp = tmp_path_factory.mktemp("syntax")
    settings = Settings(data_dir=tmp / "data", frontend_dist=tmp / "dist")
    settings.ensure_dirs()
    shutil.copy(card_db_template, settings.db_path)
    with TestClient(create_app(settings)) as c:
        yield c


def search(client, q: str, **params) -> list[dict]:
    resp = client.get("/api/cards", params={"q": q, "page_size": 200, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()["items"]


def names(client, q: str, **params) -> set[str]:
    return {c["name"] for c in search(client, q, **params)}


def test_parse_splits_name_words_and_filters():
    parsed = parse_syntax('giada t:angel -o:"lifelink" "font of"', FORMATS)
    assert parsed.name_text == "giada font of"
    assert len(parsed.clauses) == 2
    assert parsed.clauses[1][0].startswith("NOT (")
    assert not parsed.printing_level
    assert parse_syntax("s:who", FORMATS).printing_level


@pytest.mark.parametrize("q", ["foo:bar", "mv>=x", "c:xyz", "r:legendary", "f:nope", 't:""'])
def test_invalid_syntax(q):
    with pytest.raises(QuerySyntaxError):
        parse_syntax(q, FORMATS)


def test_invalid_syntax_is_422(client):
    resp = client.get("/api/cards", params={"q": "foo:bar"})
    assert resp.status_code == 422
    assert "foo" in resp.json()["detail"]


def test_type_and_oracle(client):
    angels = search(client, "t:angel")
    assert {"Serra Angel", "Giada, Font of Hope"} <= {c["name"] for c in angels}
    assert all("Angel" in c["type_line"] for c in angels)

    flying_vigilance = names(client, 'o:flying o:vigilance')
    assert {"Serra Angel", "Giada, Font of Hope"} <= flying_vigilance
    assert names(client, 'o:"each other Angel"') == {"Giada, Font of Hope"}


def test_negation(client):
    non_creature_angels = names(client, "t:angel -t:creature")
    assert "Serra Angel" not in non_creature_angels
    legendary_white = names(client, "t:legendary c:w")
    assert "Giada, Font of Hope" in legendary_white
    assert "Giada, Font of Hope" not in names(client, "t:legendary c:w -t:angel")


def test_mana_value_comparisons(client):
    assert all(c["cmc"] >= 6 for c in search(client, "mv>=6"))
    assert all(c["cmc"] < 2 for c in search(client, "mv<2 t:creature"))
    exact = search(client, "mv=5 t:angel")
    assert {c["name"] for c in exact} >= {"Serra Angel"} and all(c["cmc"] == 5 for c in exact)


def test_colors_and_identity(client):
    exact_w = search(client, "c=w t:creature")
    assert all(c["colors"] == ["W"] for c in exact_w)
    assert "Errant and Giada" not in {c["name"] for c in exact_w}

    at_least_w = names(client, "c:w t:creature")
    assert "Errant and Giada" in at_least_w

    multicolor = search(client, "c:m")
    assert multicolor and all(len(c["colors"]) >= 2 for c in multicolor)

    fits_mono_w = search(client, "id:w")
    assert all(set(c["color_identity"]) <= {"W"} for c in fits_mono_w)
    assert {"Giada, Font of Hope", "Sol Ring"} <= {c["name"] for c in fits_mono_w}

    colorless = search(client, "c:c t:artifact")
    assert colorless and all(c["colors"] == [] for c in colorless)


def test_rarity_set_and_format(client):
    mythic = search(client, "r:m")
    assert mythic and all(c["rarity"] == "mythic" for c in mythic)
    rare_plus = search(client, "r>=rare")
    assert rare_plus and all(c["rarity"] in ("rare", "mythic") for c in rare_plus)

    who = search(client, "s:who t:legendary")
    assert {"The Fourth Doctor", "Sarah Jane Smith"} <= {c["name"] for c in who}
    assert all(c["set_code"] == "who" for c in who)

    brawl = names(client, "f:brawl t:angel")
    assert "Giada, Font of Hope" in brawl


def test_syntax_combines_with_ui_filters(client):
    found = search(client, "t:angel", colors="W", color_mode="exact", game="arena")
    assert found and all(c["colors"] == ["W"] and "arena" in c["games"] for c in found)
