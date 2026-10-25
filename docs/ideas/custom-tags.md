# Idea: my own card tags

Status: done (2026-10-25). `user_tags` per oracle id, set from the card menus (My tags…) or a
card's details. Searched with `tag:` or the filter bar's "Any of my tags". Counted in the deck
stats. In the backup.

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

- **Per card**, not per copy: a tag belongs to the card (oracle id, all printings). "For sale" is
  about a copy, so it stays a separate per-copy flag (see `sell-list.md`).
- **Deck categories** stay separate: a card's role in one deck, while tags are the same everywhere.
- **Tagger tags** are not offered as tags. Scryfall asks apps showing them to be able to hide
  individual tags; worth it only if there's a need.
