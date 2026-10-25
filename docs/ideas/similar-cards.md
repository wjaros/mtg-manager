# Idea: suggest similar cards

Status: done (context menu → Similar cards, `mtgdm/cards/similar.py`). Below: the design and
what the prototype showed (2026-10-25).

## What I want

For a card, show cards that do the same job, preferably ones I already own, so a missing or
expensive card can be swapped instead of bought or proxied.

## Where

An item in the card's context menu ("Similar cards"); `ContextMenu` is already used in the
deckbuilder pool, the collection grid, the deck list and the mana columns. It opens a list:
owned first, with price and an "add to deck" button. In a deck: within the deck's format,
without cards already in the deck.

Colors: by default, cards within the card's own color identity (colorless cards always fit).
Toggles for W U B R G in the list widen it to other colors. The list refreshes, and the choice
stays while the list is open. In a deck, a shortcut could select the deck's colors.

## How: computed on the fly, nothing stored

1. Candidates: one FTS5 query over `cards_fts.oracle_text` built from the card's own text
   (reminder text and its name removed), joined to the default printings (`oracle_cards`), with
   color identity and main card type filtered in SQL (filtering after `LIMIT` loses good matches).
   Adjacent word pairs as phrases (`"exile target" OR "target creature" OR …`) beat single words.
2. Score: text rank (bm25, relative to the best match) + shared Tagger functions (`card_tags`) +
   mana value closeness. The prototype used 0.5 / 0.3 / 0.2.

Prototype results:

- **Speed:** 30–120 ms per card (about 300–500 ms on a cold cache): fine for a menu action.
- **Strong where the wording is shared:**
  - Counterspell → Negate, Essence Scatter, Remove Soul…
  - Llanowar Elves → Elvish Mystic, Fyndhorn Elves…
  - Cultivate → Kodama's Reach…
  - Wrath of God → Day of Judgment…
  - Sol Ring → Mana Vault, Grim Monolith…
- **Weaker where only the job is shared:**
  - Swords to Plowshares: Path to Exile only 7th, life gain cards around it.
  - Beast Within: no Generous Gift or Chaos Warp.
- That is where Tagger tags should help. Since the switch to the `oracle_tags` bulk file, all
  ~4,600 tags are local, with their hierarchy (`oracle_taggings`, `oracle_tag_parents`). Fine
  ones, such as `spot-removal` and below it, are what Swords and Path share. Their effect on
  the score is still untested. If the list shows Tagger labels, Scryfall asks for a way to hide
  individual tags.

## Open questions

- The weights. Tagger tags: shared fine tags count more than shared broad ones (depth in the
  hierarchy); "cycle-…" tags say little about function.
