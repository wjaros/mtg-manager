"""Does the mana base carry the spells? Frank Karsten's approach: the coloured sources a deck needs to
cast a spell on its turn, given that it hit its land drops, from the hypergeometric distribution.

Pure math on counts; `stats.py` gathers the deck's cards.
"""

from dataclasses import dataclass
from functools import cache
from math import comb

from pydantic import BaseModel

TARGET = 0.9  # how sure the deck should be to have the colours for a spell on its turn
LAND_DROP_TURNS = (3, 4, 5)
CHEAP_SOURCE_MV = 2  # nonland mana producers up to this mana value count as sources (rocks, dorks)


class ColorRequirement(BaseModel):
    color: str
    sources: int                # lands and cheap nonland sources that make this colour
    needed: int | None          # sources the hardest spell asks for; None: not reachable with this mana
    card_id: str                # the hardest spell
    name: str
    pips: int                   # its symbols of this colour
    turn: int                   # the turn it is cast on (its mana value, at least 1)


class LandDrop(BaseModel):
    turn: int
    chance: float  # of having this many lands on this turn


class ManaBase(BaseModel):
    colors: list[ColorRequirement]
    land_drops: list[LandDrop]
    target: float


@dataclass
class Spell:
    card_id: str
    name: str
    mv: int
    pips: dict[str, int]  # single-colour symbols only: hybrid and Phyrexian ones can be paid otherwise


def seen_by(turn: int) -> int:
    """Cards seen by a turn on the draw (in multiplayer most players are): seven plus a draw a turn."""
    return 7 + turn


@cache
def _chance(deck: int, producers: int, sources: int, seen: int, pips: int, lands: int) -> float:
    """P(at least `pips` sources among `seen` cards | at least `lands` producers among them)."""
    seen = min(seen, deck)
    other = producers - sources
    both = enough = 0
    for s in range(min(sources, seen) + 1):
        for o in range(min(other, seen - s) + 1):
            if s + o < lands:
                continue
            ways = comb(sources, s) * comb(other, o) * comb(deck - producers, seen - s - o)
            enough += ways
            if s >= pips:
                both += ways
    return both / enough if enough else 0.0


def chance_at_least(deck: int, hits: int, seen: int, wanted: int) -> float:
    """P(at least `wanted` of `hits` cards among `seen` cards drawn from `deck`)."""
    seen = min(seen, deck)
    return sum(comb(hits, i) * comb(deck - hits, seen - i) for i in range(wanted, min(hits, seen) + 1)) / comb(deck, seen)


@cache
def sources_needed(deck: int, producers: int, pips: int, turn: int) -> int | None:
    """Fewest of the deck's mana producers that must make a colour to cast `pips` of it on `turn` with
    TARGET certainty, given `turn` producers by then. None: even all of them would not do."""
    turn = max(turn, 1)
    if producers < turn:
        return None
    for sources in range(pips, producers + 1):
        if _chance(deck, producers, sources, seen_by(turn), pips, turn) >= TARGET:
            return sources
    return None


def mana_base(deck: int, lands: int, producers: int, sources: dict[str, int], spells: list[Spell],
              colors: list[str]) -> ManaBase:
    """`producers`: lands plus cheap nonland sources; `sources`: those per colour."""
    hardest: dict[str, tuple[int | None, Spell]] = {}
    for spell in spells:
        for color, pips in spell.pips.items():
            need = sources_needed(deck, producers, pips, spell.mv)
            current = hardest.get(color)
            # None (out of reach) is the hardest of all.
            if current is None or (current[0] is not None and (need is None or need > current[0])):
                hardest[color] = (need, spell)
    requirements = []
    for color in colors:
        if color not in hardest:
            continue
        need, spell = hardest[color]
        requirements.append(ColorRequirement(
            color=color, sources=sources.get(color, 0), needed=need, card_id=spell.card_id, name=spell.name,
            pips=spell.pips[color], turn=max(spell.mv, 1),
        ))
    drops = [LandDrop(turn=t, chance=round(chance_at_least(deck, lands, seen_by(t), t), 3))
             for t in LAND_DROP_TURNS] if deck else []
    return ManaBase(colors=requirements, land_drops=drops, target=TARGET)
