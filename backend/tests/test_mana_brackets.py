import json

import pytest
from fastapi.testclient import TestClient

from mtgdm.app import create_app
from mtgdm.db import connect
from mtgdm.decks.brackets import is_mass_land_denial, takes_extra_turns
from mtgdm.decks.mana import Spell, chance_at_least, mana_base, seen_by, sources_needed
from tests.test_validation_stats import card, import_seed, make_deck


@pytest.fixture
def client(card_settings):
    with TestClient(create_app(card_settings)) as c:
        yield c


def test_more_pips_and_earlier_turns_need_more_sources():
    assert sources_needed(99, 40, 2, 2) > sources_needed(99, 40, 1, 2)
    assert sources_needed(99, 40, 1, 1) > sources_needed(99, 40, 1, 3) > sources_needed(99, 40, 1, 6)
    assert sources_needed(99, 40, 3, 3) <= 40
    # More pips than producers, or fewer producers than the turn: no answer.
    assert sources_needed(99, 8, 9, 8) is None
    assert sources_needed(99, 2, 1, 3) is None


def test_land_drops():
    assert chance_at_least(99, 0, seen_by(3), 3) == 0
    assert chance_at_least(99, 99, seen_by(3), 3) == 1
    assert 0.7 < chance_at_least(99, 37, seen_by(3), 3) < 0.9
    assert chance_at_least(99, 37, seen_by(5), 5) < chance_at_least(99, 37, seen_by(3), 3)


def test_hardest_spell_per_color():
    spells = [
        Spell(card_id="a", name="Easy", mv=5, pips={"W": 1}),
        Spell(card_id="b", name="Hard", mv=2, pips={"W": 2}),
        Spell(card_id="c", name="Blue", mv=3, pips={"U": 1}),
    ]
    base = mana_base(99, 38, 40, {"W": 25, "U": 10}, spells, ["W", "U", "B"])
    colors = {c.color: c for c in base.colors}
    assert set(colors) == {"W", "U"}  # no black spells, no black row
    assert colors["W"].name == "Hard" and colors["W"].pips == 2 and colors["W"].turn == 2
    assert colors["W"].needed > colors["W"].sources
    assert colors["U"].needed <= 20
    assert [d.turn for d in base.land_drops] == [3, 4, 5]


@pytest.mark.parametrize(("text", "expected"), [
    ("Destroy all lands.", True),  # Armageddon
    ("Destroy all nonbasic lands.", True),  # Ruination
    ("Destroy all artifacts, creatures, and lands. They can't be regenerated.", True),  # Jokulhaups
    ("Return all lands to their owners' hands.", True),  # Sunder
    ("Players can't untap more than one land during their untap steps.", True),  # Winter Orb
    ("Lands don't untap during their controllers' untap steps.", True),  # Hokori
    ("Each player sacrifices X lands of their choice.", True),
    ("Each player chooses from the lands they control a land of each basic land type, then sacrifices the rest.", True),
    ("When this land enters, sacrifice two lands.", False),  # Lotus Field
    ("Destroy target land.", False),
    ("Return all land cards from your graveyard to the battlefield.", False),
])
def test_mass_land_denial(text, expected):
    assert is_mass_land_denial(text) is expected


@pytest.mark.parametrize(("text", "expected"), [
    ("Take an extra turn after this one.", True),
    ("Target player takes an extra turn after this one.", True),
    ("Your opponents can't take extra turns.", False),  # Stranglehold
])
def test_extra_turns(text, expected):
    assert takes_extra_turns(text) is expected


def test_stats_mana_base_and_bracket(client, card_settings):
    deck_id = import_seed(client, "doctor-who-blast-from-the-past.txt")
    stats = client.get(f"/api/decks/{deck_id}/stats").json()
    colors = {c["color"]: c for c in stats["mana_base"]["colors"]}
    assert set(colors) == {"W", "U", "G"}
    assert all(c["sources"] > 0 and c["name"] and c["needed"] for c in colors.values())
    assert [d["turn"] for d in stats["mana_base"]["land_drops"]] == [3, 4, 5]
    assert stats["bracket"]["minimum"] == 2
    assert stats["bracket"]["game_changers"] == []

    # Scryfall marks Game Changers on the card; the fixture has none, so mark a few.
    names = [c["card"]["name"] for c in client.get(f"/api/decks/{deck_id}").json()["cards"]
             if "Land" not in c["card"]["type_line"]][:4]
    conn = connect(card_settings.db_path)
    with conn:
        for name in names[:1]:
            conn.execute("UPDATE card_details SET raw = json_set(raw, '$.game_changer', json('true')) "
                         "WHERE id IN (SELECT id FROM cards WHERE name = ?)", (name,))
    bracket = client.get(f"/api/decks/{deck_id}/stats").json()["bracket"]
    assert bracket["minimum"] == 3 and [c["name"] for c in bracket["game_changers"]] == names[:1]
    with conn:
        for name in names[1:]:
            conn.execute("UPDATE card_details SET raw = json_set(raw, '$.game_changer', json('true')) "
                         "WHERE id IN (SELECT id FROM cards WHERE name = ?)", (name,))
    conn.close()
    assert client.get(f"/api/decks/{deck_id}/stats").json()["bracket"]["minimum"] == 4


def test_bracket_only_for_commander(client):
    deck_id = make_deck(client, "standard", "paper", [(card("Lotus Field"), 4, "main")])
    stats = client.get(f"/api/decks/{deck_id}/stats").json()
    assert stats["bracket"] is None
    assert stats["mana_base"]["colors"] == []
    assert json.dumps(stats["mana_base"]["land_drops"])
