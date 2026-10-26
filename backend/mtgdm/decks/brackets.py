"""Commander brackets (Wizards of the Coast's power levels 1–5): the lowest bracket a deck's cards allow.

Brackets 1–2 allow no Game Changers, 3 up to three; mass land denial needs bracket 4; chaining extra
turns is not for brackets 1–3. Game Changers come from Scryfall (`game_changer` on the card), the rest
from the rules text. Two-card combos (also not for brackets 1–2) are on the deckbuilder's Combo tab.
"""

import re

from pydantic import BaseModel

MAX_GAME_CHANGERS = {2: 0, 3: 3}

# Lands of all players: destroyed, exiled, sacrificed, bounced, or kept from untapping.
_LAND_DENIAL_RE = re.compile(
    r"(destroy|exile|return) all (nonbasic )?lands(?! you control)"
    r"|(destroy|exile|return) all [^.]*\band lands\b"
    r"|each (player|opponent) sacrifices [^.]*\blands\b"
    r"|from the lands they control[^.]*sacrifices the rest"
    r"|lands (don't|do not) untap during their controllers' untap steps"
    r"|can't untap more than (one|two) lands?",
    re.I,
)
_EXTRA_TURN_RE = re.compile(r"\btakes? (an|one|two|three|x|that many) extra turns?", re.I)


class CardRef(BaseModel):
    card_id: str
    name: str


class Bracket(BaseModel):
    minimum: int  # 2 stands for "1 or 2": their card rules are the same
    game_changers: list[CardRef]
    mass_land_denial: list[CardRef]
    extra_turns: list[CardRef]
    tutors: int  # copies tagged as tutors: brackets 1–2 expect few


def is_mass_land_denial(oracle_text: str) -> bool:
    return bool(_LAND_DENIAL_RE.search(oracle_text))


def takes_extra_turns(oracle_text: str) -> bool:
    return bool(_EXTRA_TURN_RE.search(oracle_text))


def bracket(game_changers: list[CardRef], land_denial: list[CardRef], extra_turns: list[CardRef],
            tutors: int) -> Bracket:
    if land_denial or len(game_changers) > MAX_GAME_CHANGERS[3]:
        minimum = 4
    elif game_changers:
        minimum = 3
    else:
        minimum = 2
    return Bracket(minimum=minimum, game_changers=game_changers, mass_land_denial=land_denial,
                   extra_turns=extra_turns, tutors=tutors)
