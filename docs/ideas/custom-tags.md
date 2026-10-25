# Idea: my own card tags

Status: first version done (2026-10-25): `user_tags` per oracle id, set from the card menus
(My tags…) or a card's details, searched with `tag:`, in the backup. Not yet: deck stats, a
filter in the filter bar, and the open questions below.

## What I want

My own tags on cards ("wincon", "pet card", "for the cube", "swap out"…), next to Scryfall's
Tagger tags: several per card, the same in the collection and every deck.

## What there is today

- **Deck categories:** `deck_cards.category`, one free-text category per card per deck (deck
  menu → Category), counted in the deck stats. Deck-only, one per card.
- **Tagger functions:** read-only and community-made. The app counts 9 of them; all ~4,600 are
  stored (`oracle_tags`, `oracle_taggings`).
- **Collection notes:** a free-text `note` per collection item (per copy, not per card).

## Rough shape

- A table of my tags per oracle id (all printings of a card), many per card. A migration, and
  the tags go in the backup.
- **Setting them:** context menu → Tags…, chips with autocomplete from tags already used.
- **Using them:**
  - search (`tag:wincon`, beside `otag:`) and the Function filter;
  - counted in the deck stats like the functions;
  - perhaps a signal for similar cards (cards I tagged alike).

## Decided

- **Per card**, not per copy (2026-10-25): a tag belongs to the card (oracle id, all printings).
  "For sale" is about a copy, so it stays a separate per-copy flag (see `sell-list.md`).

## Open questions

- **Deck categories:** keep them as a deck's own roles, or let them default from my tags?
- **Tagger tags:** should they be visible and pickable too, e.g. to copy one as my own tag?
