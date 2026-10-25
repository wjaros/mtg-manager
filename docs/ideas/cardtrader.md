# Idea: CardTrader integration

Status: step 1 done (2026-10-25): the shopping list as one CardTrader wishlist, a deck's missing
cards put on the list first (`mtgdm/cardtrader/`, Settings › CardTrader). There is no endpoint to
edit a wishlist, so a sync creates a new one and then deletes the last. The facts below come from CardTrader's API reference (pasted from
https://www.cardtrader.com/en/docs/api/full/reference on 2026-10-25; the page itself is behind a
Cloudflare check, the API host is not).

## API basics

- Base URL `https://api.cardtrader.com/api/v2`, header `Authorization: Bearer <token>`. The token
  comes from the settings page of the user's CardTrader profile. `GET /info` tests it.
- Rate limits: 200 requests per 10 s overall; marketplace products 10/s; jobs 1/s.
- Magic is game id 1. Expansion codes look like Scryfall's (`m21`, `grn`, `pgrn`).
- Blueprint = one sellable printing. Each carries `scryfall_id` (and Cardmarket ids), so our
  printings map to blueprints exactly.

## Wishlists (cards to buy)

- `POST /wishlists` with `{"deck": {"game_id": 1, "name": ..., "public": false, ...}}` and one of:
  - `deck_items_from_text_deck`: a list in MTGA format. **Lines matching no blueprint are
    silently ignored.**
  - `deck_items_attributes`: a list of DeckItems. Fields: `quantity`, and either `meta_name`
    (the card name: any edition) or `blueprint_id` / `expansion_code` + `collector_number`
    (one printing). Optionally `language`, `condition`, `foil`.
- `GET /wishlists/:id` returns the items as stored, so we can check what was recognized. Their
  `meta_name` is a slug (`teferi-who-slows-the-sunset`), seen on a real wishlist on 2026-10-25.
  `GET /wishlists?game_id=1` lists them; `DELETE /wishlists/:id` removes one.
- The docs don't say whether the website's wishlist form takes a pasted list (to check by hand).

## Selling (see `sell-list.md`)

- **CSV import** (`POST /product_imports`, multipart):
  - `game_id=1`;
  - `replace_stock_or_add_to_stock` = `add_to_stock` or `replace_stock`;
  - `column_names` names the CSV's columns, e.g. `scryfall_id|quantity|condition|language|foil|price`.
  - `scryfall_id` alone identifies the product.
  - Asynchronous: `GET /product_imports/:id` gives counts of imported, skipped and created items.
- **Also possible:**
  - single products: `POST /products` (`blueprint_id`, `price`, `quantity`, `properties`);
  - batch jobs: `/products/bulk_create`, checked through `/jobs/:uuid`.
- **Conditions:** Mint, Near Mint, Slightly Played, Moderately Played, Played, Heavily Played,
  Poor. From our Cardmarket scale: M→Mint, NM→Near Mint, EX→Slightly Played, GD→Moderately
  Played, LP→Played, PL→Heavily Played, PO→Poor.
- **Foil** is the property `mtg_foil`.

## Orders (bought and sold cards)

- **Listing:** `GET /orders?order_as=buyer|seller`, with `state`, `from` / `to` (dates),
  `from_id` / `to_id`, `page` and `limit` (1–100). `GET /orders/:id` gets one order.
- **Order items** carry `scryfall_id`, `quantity` and `properties` (`condition`,
  `mtg_language`, `mtg_foil`, `collector_number`), so a purchase maps to our exact printing.
- **States:** paid → sent → arrived → done; also hub_pending (CardTrader Zero),
  request_for_cancel, canceled, lost.
  - As a seller with CardTrader Zero, count a sale once only: hub_pending orders, not the
    weekly merged paid one.
- **CardTrader Zero:** `GET /ct0_box_items` lists bought cards not yet shipped to the buyer.
  Quantities come per state: `ok` (in the box), `pending` (on its way), `missing` (refunded).
  Each item has `scryfall_id`, `properties` and `estimated_arrived_at`.

## Errors and webhooks

- Errors are JSON `{"error_code", "errors", "extra": {"message"}, "request_id"}`: 401
  unauthorized, 404 not_found, 422 missing_parameter.
- Rate limit errors are `{"error": "Too many requests: ..."}`.
- **Webhooks** fire when a product or an order is created, modified or deleted. They are signed
  with HMAC-SHA256 of the body using the app's `shared_secret`. Changes made through the API itself
  don't trigger them. They need a public HTTPS endpoint; a desktop app has none, so it would poll
  instead (e.g. `GET /orders` from the last order id seen).

## Prices

`GET /marketplace/products?blueprint_id=` gives the cheapest 25 offers per printing. It needs
blueprint ids: `GET /blueprints/export?expansion_id=` per expansion, which carries `scryfall_id`.

## Possible steps

1. **"Send to CardTrader"** for a deck's missing cards, and later the shopping list:
   - create a private wishlist from DeckItems by card name (any printing), or with set and
     number when the printing matters;
   - read it back and report the cards CardTrader didn't take.
2. **Import purchases:**
   - add the cards of buyer orders (arrived or done) to the collection: exact printing by
     `scryfall_id`, with condition, language and foil;
   - remember the imported order ids, so nothing is added twice;
   - the shopping list then counts them as bought. CT0 box items could show what's on its way.
3. **Sell list:**
   - export the copies marked for sale as a CSV keyed by `scryfall_id`, for CardTrader's
     import; later, upload it through the API;
   - seller orders could then take sold copies out of the collection.
4. **Token:** stored locally only. Never in the JSON backup or the cloud backup folder.
