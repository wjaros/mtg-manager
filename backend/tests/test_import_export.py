import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.decks.textformat import parse_decklist
from tests.helpers import SEEDS_DIR, fixture_cards

CARDS = fixture_cards()


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


def parse(client, text: str, **body) -> dict:
    resp = client.post("/api/import/parse", json={"text": text, **body})
    assert resp.status_code == 200, resp.text
    return resp.json()


def only_line(report: dict) -> dict:
    assert len(report["lines"]) == 1, report
    return report["lines"][0]


def card_id(name: str, set_code: str, number: str) -> str:
    return next(c["id"] for c in CARDS if c["name"] == name and c["set"] == set_code and c["collector_number"] == number)


# --- parser ------------------------------------------------------------------


def test_parser_sections_quantities_and_metadata():
    parsed = parse_decklist(
        """# name: Test deck
# format: brawl
# just a comment
About
Name Ignored because meta wins

commander
1 Calix, Guided by Fate (MAT) 26

Deck
11 Forest (SOS) 281
2x Seal Away *F*
1 Fire // Ice
Sideboard:
1 Serra Angel (FDN) 147 *F*
MAYBEBOARD
1 Kirol’s Thing
"""
    )
    assert parsed.meta == {"name": "Test deck", "format": "brawl"}
    assert parsed.errors == []
    got = [(l.board, l.quantity, l.name, l.set_code, l.collector_number, l.foil) for l in parsed.lines]
    assert got == [
        ("commander", 1, "Calix, Guided by Fate", "mat", "26", False),
        ("main", 11, "Forest", "sos", "281", False),
        ("main", 2, "Seal Away", None, None, True),
        ("main", 1, "Fire // Ice", None, None, False),
        ("sideboard", 1, "Serra Angel", "fdn", "147", True),
        ("maybe", 1, "Kirol's Thing", None, None, False),
    ]


def test_parser_arena_about_block_and_errors():
    parsed = parse_decklist("About\nName My Arena Deck\n\nDeck\n1 Sol Ring\nnot a card line\n0 Plains\n")
    assert parsed.meta["name"] == "My Arena Deck"
    assert [l.name for l in parsed.lines] == ["Sol Ring"]
    assert [(e.line_no, e.text) for e in parsed.errors] == [(6, "not a card line"), (7, "0 Plains")]


def test_parser_lines_without_section_go_to_main():
    parsed = parse_decklist("4 Lightning Bolt\n20 Plains (FDN)\n")
    assert [(l.board, l.set_code, l.collector_number) for l in parsed.lines] == [
        ("main", None, None), ("main", "fdn", None)
    ]


# --- matching ----------------------------------------------------------------


@pytest.mark.parametrize("seed", ["quintorius-lorehold-spirit.txt", "doctor-who-blast-from-the-past.txt", "giada-font-of-hope.txt"])
def test_seeds_import_without_missing_cards(client, seed):
    report = parse(client, (SEEDS_DIR / seed).read_text(encoding="utf-8"))
    assert report["errors"] == []
    assert report["counts"]["not_found"] == 0, [l["name"] for l in report["lines"] if l["status"] == "not_found"]
    assert report["counts"]["cards"] == 100
    assert report["meta"]["format"] == "commander" and report["meta"]["platform"] == "paper"
    # Tokens share names with real cards (the token "Ajani's Pridemate"); never pick them.
    assert not [l["name"] for l in report["lines"] if l["card"]["layout"] in ("token", "emblem", "art_series")]


def test_doctor_who_seed_keeps_exact_printings(client):
    report = parse(client, (SEEDS_DIR / "doctor-who-blast-from-the-past.txt").read_text(encoding="utf-8"))
    for line in report["lines"]:
        assert line["status"] == "matched", line
        assert (line["card"]["set_code"], line["card"]["collector_number"]) == (line["set_code"], line["collector_number"])


def test_preferred_sets_choose_printing(client):
    report = parse(client, "# preferred-sets: soc\n1 Quintorius, History Chaser\n1 Sol Ring\n")
    assert report["meta"]["preferred_sets"] == ["soc"]
    assert {l["card"]["set_code"] for l in report["lines"]} == {"soc"}


def test_arena_set_code_is_mapped(client):
    line = only_line(parse(client, "1 Seal Away (DAR) 31"))
    assert line["status"] == "matched"
    assert line["card"]["id"] == card_id("Seal Away", "dom", "31")


def test_scryfall_code_wins_but_only_if_set_has_the_card(client):
    # 'med' is a Scryfall set code and also the Arena code of me1; Bolt is only in me1.
    line = only_line(parse(client, "1 Lightning Bolt (MED) 102"))
    assert line["card"]["id"] == card_id("Lightning Bolt", "me1", "102")
    # me1 (Masters Edition) is an MTGO-only set: the only warning is about the paper deck.
    assert line["warnings"] == ["Karta tylko cyfrowa (nie istnieje w wersji papierowej)"]


def test_number_with_face_letter_and_front_face_name(client):
    expected = card_id("Twice Upon a Time // Unlikely Meeting", "who", "61")
    for text in ("1 Twice Upon a Time // Unlikely Meeting (WHO) 61a", "1 Twice Upon a Time (WHO) 61"):
        line = only_line(parse(client, text))
        assert line["status"] == "matched", line
        assert line["card"]["id"] == expected


def test_alchemy_prefix_falls_back_with_warning(client):
    line = only_line(parse(client, "1 A-Haywire Mite"))
    assert line["status"] == "warning"
    assert line["card"]["name"] == "Haywire Mite"
    assert "Alchemy" in line["warnings"][0]


def test_unknown_set_and_number_warn(client):
    line = only_line(parse(client, "1 Serra Angel (XYZ) 1"))
    assert line["status"] == "warning" and line["card"]["name"] == "Serra Angel"
    assert "XYZ" in line["warnings"][0]

    line = only_line(parse(client, "1 Serra Angel (FDN) 9999"))
    assert line["status"] == "warning" and line["card"]["set_code"] == "fdn"
    assert "9999" in line["warnings"][0]


def test_not_found_with_suggestions(client):
    report = parse(client, "1 Giada Font\n1 Completely Made Up Card")
    giada, fake = report["lines"]
    assert giada["status"] == "not_found" and giada["card"] is None
    assert "Giada, Font of Hope" in giada["suggestions"]
    assert fake["status"] == "not_found" and fake["suggestions"] == []
    assert report["counts"]["not_found"] == 2


def test_arena_platform_prefers_arena_printings(client):
    report = parse(client, "1 Calix, Guided by Fate\n1 Sol Ring", platform="arena")
    calix, sol_ring = report["lines"]
    assert calix["status"] == "matched" and "arena" in calix["card"]["games"]
    assert sol_ring["status"] == "warning" and "Arenie" in sol_ring["warnings"][0]


# --- commit & export ---------------------------------------------------------


def commit(client, report: dict, **overrides) -> dict:
    meta = report["meta"]
    body = {
        "name": meta["name"] or "Imported",
        "format": meta["format"] or "freeform",
        "platform": meta["platform"] or "paper",
        "description": meta["description"],
        "preferred_sets": meta["preferred_sets"],
        "entries": [
            {"card_id": l["card"]["id"], "quantity": l["quantity"], "board": l["board"]}
            for l in report["lines"] if l["card"]
        ],
        **overrides,
    }
    resp = client.post("/api/import/commit", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_commit_seed_creates_deck(client):
    report = parse(client, (SEEDS_DIR / "doctor-who-blast-from-the-past.txt").read_text(encoding="utf-8"))
    deck = commit(client, report)
    assert deck["name"] == "Doctor Who – Blast from the Past (precon)"
    assert deck["counts"]["total"] == 100
    assert deck["commander_name"] == "The Fourth Doctor & Sarah Jane Smith"
    assert "source: precon Doctor Who Commander" in deck["description"]


def test_commit_with_unknown_card_creates_nothing(client):
    resp = client.post("/api/import/commit", json={"name": "x", "entries": [{"card_id": "nope"}]})
    assert resp.status_code == 404
    assert client.get("/api/decks").json() == []


def test_arena_export(client):
    report = parse(client, """Commander
1 Calix, Guided by Fate (MAT) 26
Deck
1 Seal Away (DOM) 31
1 Delver of Secrets // Insectile Aberration (MID) 47
1 Serra Angel (SLZ) 10
1 Sol Ring
10 Plains
Sideboard
1 Lightning Bolt
""")
    deck = commit(client, report, format="brawl", platform="arena")
    result = client.get(f"/api/decks/{deck['id']}/export", params={"target": "arena"}).json()
    lines = result["text"].splitlines()

    assert lines[:2] == ["Commander", "1 Calix, Guided by Fate (MAT) 26"]
    assert "Deck" in lines
    assert "1 Seal Away (DAR) 31" in lines                      # Arena set code
    assert "1 Delver of Secrets (MID) 47" in lines              # front face only
    assert not any("Sol Ring" in l for l in lines)
    assert result["unavailable"] == ["Sol Ring"]
    # Paper-only Secret Lair printing swapped for an Arena one, with a warning.
    serra = next(l for l in lines if "Serra Angel" in l)
    assert "(SLZ)" not in serra
    assert any("Serra Angel" in w for w in result["warnings"])
    # Brawl has no sideboard on Arena.
    assert "Sideboard" not in lines and not any("Lightning Bolt" in l for l in lines)


def test_text_export_round_trips(client):
    report = parse(client, (SEEDS_DIR / "quintorius-lorehold-spirit.txt").read_text(encoding="utf-8"))
    deck = commit(client, report)
    exported = client.get(f"/api/decks/{deck['id']}/export", params={"target": "text"}).json()["text"]
    assert exported.startswith("# name: Quintorius")
    assert "# preferred-sets: soc" in exported

    again = parse(client, exported)
    assert again["counts"]["not_found"] == again["counts"]["warning"] == 0
    original = sorted((c["card"]["id"], c["quantity"], c["board"]) for c in deck["cards"])
    reparsed = sorted((l["card"]["id"], l["quantity"], l["board"]) for l in again["lines"])
    assert reparsed == original


def test_seeds_endpoint(client):
    seeds = client.get("/api/import/seeds").json()
    # Deck seeds only: lists in seeds/collection are products, not decks.
    assert {s["file"] for s in seeds} == {
        "quintorius-lorehold-spirit.txt", "doctor-who-blast-from-the-past.txt", "giada-font-of-hope.txt",
        "orzhov-auras-q06.txt", "code-of-the-orzhov-gpt.txt",
    }
    assert all(s["text"] and s["name"] for s in seeds)


# --- Moxfield ----------------------------------------------------------------

# "Copy for MTG Arena" from Moxfield: Arena sections, Scryfall set codes, foil/etched markers.
MOXFIELD_ARENA = """Commander
1 Giada, Font of Hope (FDN) 141 *F*

Deck
1 Sol Ring (SLD) 2783 *F*
1 Fire // Ice (MH2) 290 *E*
1 Serra Angel (J25) 251
12 Plains (FRA) 281
"""

# Plain text export: no section headers except the sideboard one.
MOXFIELD_TEXT = """1 Sol Ring (SLD) 2783
1 Fire // Ice (MH2) 290 *E*

SIDEBOARD:
1 Seal Away (DOM) 31
"""


def test_moxfield_arena_export_imports_exactly(client):
    report = parse(client, MOXFIELD_ARENA)
    assert report["counts"] == {"matched": 5, "warning": 0, "not_found": 0, "cards": 16}
    got = {(l["card"]["name"], l["card"]["set_code"], l["card"]["collector_number"], l["board"], l["foil"])
           for l in report["lines"]}
    assert got == {
        ("Giada, Font of Hope", "fdn", "141", "commander", True),
        ("Sol Ring", "sld", "2783", "main", True),
        ("Fire // Ice", "mh2", "290", "main", True),
        ("Serra Angel", "j25", "251", "main", False),
        ("Plains", "fra", "281", "main", False),
    }


def test_moxfield_text_export_with_sideboard(client):
    report = parse(client, MOXFIELD_TEXT)
    assert report["errors"] == []
    assert [(l["card"]["name"], l["board"]) for l in report["lines"]] == [
        ("Sol Ring", "main"), ("Fire // Ice", "main"), ("Seal Away", "sideboard")]


# --- product lists (several half-decks or printings in one list) ------------------------

PRODUCT_LIST = """# name: Product
Deck
# --- Half deck A (W) ---
2 Plains (FRA) 281
1 Serra Angel (J25) 251
# --- Half deck B (W) ---
1 Serra Angel (J25) 251
3 Plains (FRA) 282
1 Plains (FRA) 281
"""


def test_group_comments_are_ignored():
    parsed = parse_decklist(PRODUCT_LIST)
    assert parsed.errors == [] and parsed.meta == {"name": "Product"}
    assert [(l.quantity, l.name, l.collector_number) for l in parsed.lines] == [
        (2, "Plains", "281"), (1, "Serra Angel", "251"), (1, "Serra Angel", "251"), (3, "Plains", "282"),
        (1, "Plains", "281")]


def test_duplicate_lines_are_summed_and_printings_kept_apart(client):
    deck = commit(client, parse(client, PRODUCT_LIST))
    got = sorted((c["card"]["name"], c["card"]["collector_number"], c["quantity"]) for c in deck["cards"])
    assert got == [("Plains", "281", 3), ("Plains", "282", 3), ("Serra Angel", "251", 2)]
    assert deck["counts"]["total"] == 8


def test_trailing_comment_is_a_note():
    parsed = parse_decklist("7 Plains (TLA) 282 # printing unverified\n1 Sol Ring #   \n2 Fire // Ice *F* # promo\n")
    assert parsed.errors == []
    assert [(l.name, l.set_code, l.collector_number, l.foil, l.note) for l in parsed.lines] == [
        ("Plains", "tla", "282", False, "printing unverified"),
        ("Sol Ring", None, None, False, None),
        ("Fire // Ice", None, None, True, "promo"),
    ]


# --- product lists (decks and a collection list in seeds/) -------------------------------


@pytest.mark.parametrize(("seed", "main", "sideboard", "fmt"), [
    ("orzhov-auras-q06.txt", 60, 15, "pioneer"),
    ("code-of-the-orzhov-gpt.txt", 60, 0, "freeform"),
])
def test_product_deck_seeds_match_exactly(client, seed, main, sideboard, fmt):
    report = parse(client, (SEEDS_DIR / seed).read_text(encoding="utf-8"))
    assert report["errors"] == [] and report["meta"]["format"] == fmt
    assert report["counts"]["not_found"] == 0 and report["counts"]["warning"] == 0
    boards = {}
    for line in report["lines"]:
        assert (line["card"]["set_code"], line["card"]["collector_number"]) == (line["set_code"], line["collector_number"])
        boards[line["board"]] = boards.get(line["board"], 0) + line["quantity"]
    assert boards == {"main": main, **({"sideboard": sideboard} if sideboard else {})}


def test_code_of_the_orzhov_keeps_eight_basic_printings(client):
    deck = commit(client, parse(client, (SEEDS_DIR / "code-of-the-orzhov-gpt.txt").read_text(encoding="utf-8")))
    basics = [c for c in deck["cards"] if c["card"]["name"] in ("Plains", "Swamp")]
    assert len(basics) == 8 and sum(c["quantity"] for c in basics) == 21
    assert deck["counts"]["total"] == 60


def test_orzhov_auras_only_lurrus_is_illegal_in_pioneer(client):
    deck = commit(client, parse(client, (SEEDS_DIR / "orzhov-auras-q06.txt").read_text(encoding="utf-8")))
    issues = client.get(f"/api/decks/{deck['id']}/validate").json()["issues"]
    errors = [(i["code"], i["message"]) for i in issues if i["severity"] == "error"]
    assert errors == [("banned", "Zbanowane w Pioneer: Lurrus of the Dream-Den")]


def test_avatar_beginner_box_into_collection(client):
    text = (SEEDS_DIR / "collection" / "avatar-tla-beginner-box.txt").read_text(encoding="utf-8")
    report = parse(client, text)
    assert report["errors"] == [] and report["counts"]["not_found"] == 0 and report["counts"]["warning"] == 0
    assert report["counts"]["cards"] == 200
    basics = sum(l["quantity"] for l in report["lines"] if l["name"] in ("Plains", "Island", "Swamp", "Mountain", "Forest"))
    assert basics == 72
    unverified = [l for l in report["lines"] if l["note"]]
    assert len(unverified) == 9 and all("printing unverified" in l["note"] for l in unverified)

    box = client.post("/api/locations", json={"name": "Avatar Beginner Box", "kind": "box"}).json()
    entries = [{"card_id": l["card"]["id"], "quantity": l["quantity"], "note": l["note"]} for l in report["lines"]]
    assert client.post("/api/collection/import/commit", json={"entries": entries, "location_id": box["id"]}).json()["added"] == 200
    location = next(loc for loc in client.get("/api/locations").json() if loc["id"] == box["id"])
    assert location["card_count"] == 200
    items = client.get("/api/collection", params={"location_id": box["id"]}).json()
    assert sum(i["quantity"] for i in items if i["note"] and "printing unverified" in i["note"]) == 57
