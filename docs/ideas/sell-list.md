# Idea: mark cards in the collection for sale, export them for Cardmarket or CardTrader

Status: idea, low priority ("maybe some day"; on 2026-10-25: nothing to sell for now).

## What I want

In the collection, mark copies I want to sell and export them as a list I can put up on
Cardmarket, the reverse of the shopping list (`mtgdm/collection/wants.py`).

## What there is today

- `collection_items` has per-copy finish, language, condition (already on the Cardmarket scale)
  and a free-text `note`; nothing marks a copy as for sale.
- Cardmarket exports exist only for buying: missing cards and the shopping list as `1 Name` lines
  for a wants list (`render_missing`, `render_wants`).
- `moxfield.py` already exports the collection as CSV with conditions mapped.

## Rough shape

- A "for sale" flag (or quantity) per collection item, new migration; set from the collection
  list and the item detail, a filter for it in the collection view.
- Export the marked copies with printing, finish, language, condition and the bulk price as a
  hint (an estimate with its date, as elsewhere).
- To check: which format Cardmarket accepts for adding stock in bulk (CSV upload or a list), and
  whether it needs the exact expansion and Cardmarket's own product ids.
- **CardTrader** is simpler: its CSV import identifies a product by `scryfall_id` alone, which our
  copies have, and its conditions map 1:1 from ours. Upload is possible through the API with the
  token the app already keeps. Sold copies could later leave the collection from its seller orders.
  See `cardtrader.md`.
- Open questions: should a card in a deck's box be blocked from sale or only warned about
  (`usage.py` knows where a copy is)? What happens to the copy once sold: delete it, or keep it
  as sold? Is the flag in the backup? (Yes, probably.)
