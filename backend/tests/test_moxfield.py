import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from tests.helpers import fixture_cards

CARDS = fixture_cards()
# Moxfield's CSV format with short and long forms mixed, blank fields, alter and playtest flags.
EXAMPLE = (Path(__file__).parent / "fixtures" / "moxfield" / "collection-example.csv").read_text(encoding="utf-8")


def printing(name: str, set_code: str, number: str) -> dict:
    return next(c for c in CARDS if c["name"] == name and c["set"] == set_code and c["collector_number"] == number)


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


def parse(client, text: str) -> dict:
    resp = client.post("/api/collection/import/moxfield/parse", json={"text": text})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_example_parses(client):
    report = parse(client, EXAMPLE)
    assert report["errors"] == []
    assert [(l["quantity"], l["card"]["set_code"], l["card"]["collector_number"], l["finish"], l["condition"],
             l["language"], l["note"], l["status"]) for l in report["lines"]] == [
        (2, "c21", "9", "foil", "NM", "de", None, "matched"),
        (1, "oc21", "9", "etched", "EX", "en", "playtest", "matched"),  # Moxfield LP = our EX
        (3, "2x2", "36", "nonfoil", "NM", "en", None, "matched"),      # no language = English
        (1, "tmp", "1", "nonfoil", "PO", "ja", "alter", "matched"),    # D(amaged) = PO
    ]
    assert report["counts"] == {"matched": 4, "warning": 0, "not_found": 0, "copies": 7}


def test_long_and_short_forms_and_problems(client):
    text = """Name,Edition,Collector Number,Count,Condition,Language,Foil
"Serra Angel",j25,251,2,Played,jp,
"Serra Angel",j25,251,1,Mint,Simplified Chinese,foil
"Serra Angel",zzz,1,1,Excellent,Klingon,
"No Such Card",,,1,NM,en,
"Serra Angel",j25,251,x,NM,en,
"""
    report = parse(client, text)
    assert [e["row"] for e in report["errors"]] == [6]
    first, second, third, missing = report["lines"]
    assert (first["condition"], first["language"], first["status"]) == ("GD", "ja", "matched")
    assert (second["condition"], second["language"], second["finish"]) == ("M", "zhs", "foil")
    assert second["status"] == "warning"  # j25 Serra Angel has no foil version
    assert third["status"] == "warning" and third["card"]["name"] == "Serra Angel"
    assert (third["condition"], third["language"]) == ("NM", "en")
    assert len(third["warnings"]) == 3  # unknown condition, unknown language, set without the card
    assert missing["status"] == "not_found" and missing["card"] is None
    assert parse(client, "just,some\n1,2\n")["errors"][0]["row"] == 1


def test_commit_adds_to_location(client):
    report = parse(client, EXAMPLE)
    binder = client.post("/api/locations", json={"name": "Binder"}).json()
    entries = [{k: l[k] for k in ("quantity", "finish", "condition", "language", "note")} | {"card_id": l["card"]["id"]}
               for l in report["lines"]]
    result = client.post("/api/collection/import/commit", json={"entries": entries, "location_id": binder["id"]})
    assert result.json() == {"added": 7, "entries": 4}
    items = client.get("/api/collection", params={"location_id": binder["id"]}).json()
    assert sorted((i["card"]["set_code"], i["quantity"], i["finish"], i["condition"], i["note"], i["source"])
                  for i in items) == [
        ("2x2", 3, "nonfoil", "NM", None, "import"),
        ("c21", 2, "foil", "NM", None, "import"),
        ("oc21", 1, "etched", "EX", "playtest", "import"),
        ("tmp", 1, "nonfoil", "PO", "alter", "import"),
    ]
    # Like Moxfield: importing again adds, never replaces.
    client.post("/api/collection/import/commit", json={"entries": entries, "location_id": binder["id"]})
    assert client.get("/api/collection/stats").json()["copies"] == 14
    bad = client.post("/api/collection/import/commit", json={"entries": entries, "location_id": 999})
    assert bad.status_code == 404


def test_export_round_trip(client):
    serra = printing("Serra Angel", "j25", "251")
    adrix = printing("Adrix and Nev, Twincasters", "oc21", "9")
    client.post("/api/collection", json={"card_id": serra["id"], "quantity": 2, "condition": "GD", "language": "pl"})
    client.post("/api/collection", json={"card_id": adrix["id"], "finish": "etched", "condition": "EX", "language": "de"})

    resp = client.get("/api/collection/export", params={"format": "moxfield"})
    assert resp.headers["content-type"].startswith("text/csv")
    assert 'filename="collection-moxfield.csv"' in resp.headers["content-disposition"]
    assert resp.text.splitlines()[0] == ('"Count","Name","Edition","Condition","Language","Foil","Collector Number",'
                                         '"Alter","Playtest Card","Purchase Price"')
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert [(r["Count"], r["Name"], r["Edition"], r["Condition"], r["Language"], r["Foil"], r["Collector Number"])
            for r in rows] == [
        ("1", "Adrix and Nev, Twincasters", "oc21", "LP", "de", "etched", "9"),
        ("2", "Serra Angel", "j25", "MP", "en", "", "251"),  # Polish is not a Moxfield language
    ]
    # Our own export imports back (conditions come back on the Cardmarket scale: LP -> EX, MP -> GD).
    back = parse(client, resp.text)
    assert [(l["card"]["id"], l["condition"], l["finish"]) for l in back["lines"]] == [
        (adrix["id"], "EX", "etched"), (serra["id"], "GD", "nonfoil")]
