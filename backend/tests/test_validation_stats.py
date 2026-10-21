import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from tests.helpers import SEEDS_DIR, fixture_cards

CARDS = fixture_cards()


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


def card(name: str, set_code: str | None = None, arena: bool = False) -> str:
    return next(
        c["id"] for c in CARDS
        if c["name"] == name and (set_code is None or c["set"] == set_code) and (not arena or "arena" in c["games"])
        and c["layout"] not in ("token", "art_series")
    )


def make_deck(client, fmt: str, platform: str, entries: list[tuple[str, int, str]]) -> int:
    deck = client.post("/api/decks", json={"name": "t", "format": fmt, "platform": platform}).json()
    body = [{"card_id": cid, "quantity": qty, "board": board} for cid, qty, board in entries]
    assert client.put(f"/api/decks/{deck['id']}/cards", json=body).status_code == 200
    return deck["id"]


def import_seed(client, file: str) -> int:
    report = client.post("/api/import/parse", json={"text": (SEEDS_DIR / file).read_text(encoding="utf-8")}).json()
    meta = report["meta"]
    return client.post("/api/import/commit", json={
        "name": meta["name"], "format": meta["format"], "platform": meta["platform"],
        "entries": [{"card_id": l["card"]["id"], "quantity": l["quantity"], "board": l["board"]} for l in report["lines"]],
    }).json()["id"]


def validate(client, deck_id: int) -> dict:
    resp = client.get(f"/api/decks/{deck_id}/validate")
    assert resp.status_code == 200, resp.text
    return resp.json()


def codes(result: dict, severity: str = "error") -> set[str]:
    return {i["code"] for i in result["issues"] if i["severity"] == severity}


@pytest.mark.parametrize("seed", ["doctor-who-blast-from-the-past.txt", "quintorius-lorehold-spirit.txt", "giada-font-of-hope.txt"])
def test_seed_decks_are_valid(client, seed):
    result = validate(client, import_seed(client, seed))
    assert result["valid"], result["issues"]
    # Physical decks not yet in the collection get a reminder, not an error.
    assert "not_in_collection" in codes(result, "warning")


def test_doctor_and_companion_pair_is_valid_but_two_random_legends_are_not(client):
    doctor_pair = make_deck(client, "commander", "paper", [
        (card("The Fourth Doctor", "who"), 1, "commander"),
        (card("Sarah Jane Smith", "who"), 1, "commander"),
    ])
    assert "invalid_partner" not in codes(validate(client, doctor_pair))

    random_pair = make_deck(client, "commander", "paper", [
        (card("Giada, Font of Hope", "fdn"), 1, "commander"),
        (card("The Fourth Doctor", "who"), 1, "commander"),
    ])
    result = validate(client, random_pair)
    assert "invalid_partner" in codes(result)


def test_broken_brawl_deck_lists_specific_errors(client):
    deck_id = make_deck(client, "brawl", "arena", [
        (card("Serra Angel", arena=True), 1, "commander"),       # not legendary
        (card("Seal Away", "dom"), 2, "main"),                    # singleton
        (card("Lightning Bolt", arena=True), 1, "main"),          # red: outside a white identity
        (card("Sol Ring"), 1, "main"),                            # not on Arena / not legal in Brawl
        (card("Plains", arena=True), 20, "main"),
        (card("Giada, Font of Hope", "fdn"), 1, "sideboard"),     # Brawl has no sideboard
    ])
    result = validate(client, deck_id)
    assert not result["valid"]
    assert {"deck_size", "invalid_commander", "singleton", "color_identity", "not_legal", "not_on_arena"} <= codes(result)
    assert "sideboard" in codes(result, "warning")

    by_code = {i["code"]: i for i in result["issues"]}
    assert "Seal Away ×2" in by_code["singleton"]["message"]
    assert "Lightning Bolt" in by_code["color_identity"]["message"]
    assert by_code["deck_size"]["message"].startswith("Talia ma 25 kart")
    assert card("Sol Ring") in by_code["not_on_arena"]["card_ids"]


def test_valid_small_brawl_has_only_size_and_land_issues(client):
    deck_id = make_deck(client, "standardbrawl", "arena", [
        (card("Giada, Font of Hope", "fdn"), 1, "commander"),
        (card("Plains", arena=True), 59, "main"),
    ])
    result = validate(client, deck_id)
    errors = codes(result)
    assert errors <= {"not_legal"}, result["issues"]  # legality depends on the current Standard rotation
    assert "land_count" in codes(result, "warning")


def test_constructed_rules(client):
    deck_id = make_deck(client, "historic", "arena", [
        (card("Seal Away", "dom"), 5, "main"),
        (card("Plains", arena=True), 20, "main"),
        (card("Serra Angel", arena=True), 16, "sideboard"),
    ])
    result = validate(client, deck_id)
    assert {"deck_size", "sideboard_size", "max4"} <= codes(result)
    by_code = {i["code"]: i for i in result["issues"]}
    assert "Seal Away ×5" in by_code["max4"]["message"]


def test_freeform_has_no_errors(client):
    deck_id = make_deck(client, "freeform", "paper", [(card("Serra Angel"), 9, "main")])
    result = validate(client, deck_id)
    assert result["valid"] and codes(result) == set()


def test_collection_clears_missing_warning(client):
    deck_id = import_seed(client, "doctor-who-blast-from-the-past.txt")
    assert client.post(f"/api/decks/{deck_id}/collection").status_code == 200
    assert "not_in_collection" not in codes(validate(client, deck_id), "warning")


def test_stats(client):
    deck_id = import_seed(client, "doctor-who-blast-from-the-past.txt")
    stats = client.get(f"/api/decks/{deck_id}/stats").json()
    assert stats["total"] == 100
    assert stats["lands"] + stats["nonlands"] == 100
    assert sum(b["total"] for b in stats["curve"]) == stats["nonlands"]
    assert all(b["total"] == sum(b["by_color"].values()) for b in stats["curve"])
    assert stats["types"]["Land"] >= stats["lands"]
    assert sum(stats["primary_types"].values()) == 100
    assert 2 < stats["average_mv"] < 5
    pips = {c["color"]: c for c in stats["colors"]}
    assert pips["W"]["pips"] > 0 and pips["U"]["pips"] > 0 and pips["G"]["pips"] > 0
    assert pips["R"]["pips"] == 0 and pips["B"]["pips"] == 0
    assert pips["W"]["land_sources"] > 0
    assert stats["price"]["eur"] > 0 and stats["price"]["as_of"]
    assert stats["price"]["missing_eur"] == stats["price"]["eur"]  # nothing owned yet
    assert sum(stats["wildcards"].values()) <= 100

    client.post(f"/api/decks/{deck_id}/collection")
    assert client.get(f"/api/decks/{deck_id}/stats").json()["price"]["missing_eur"] == 0


def test_validate_and_stats_unknown_deck(client):
    assert client.get("/api/decks/999/validate").status_code == 404
    assert client.get("/api/decks/999/stats").status_code == 404


def test_pioneer_rules(client):
    deck = make_deck(client, "pioneer", "paper", [
        (card("Serra Angel", "j25"), 5, "main"), (card("Plains", "fra"), 40, "main"),
        (card("Lightning Bolt"), 2, "sideboard"),
    ])
    result = validate(client, deck)
    assert result["format"] == "pioneer"
    # 45 cards, 5 Serra Angels, Lightning Bolt is not Pioneer-legal (basics are exempt from the limit).
    assert codes(result) == {"deck_size", "max4", "not_legal"}
    assert "Pioneer" in next(i["message"] for i in result["issues"] if i["code"] == "not_legal")
