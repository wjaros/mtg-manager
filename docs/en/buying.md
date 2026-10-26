# Missing cards and buying

[← Contents](index.md)

## A deck's missing cards

The deckbuilder's **Missing** tab (paper decks) lists the cards a deck still needs, with estimated
prices:

- **Don't count cards in other decks' boxes:** copies built into your other decks count as
  unavailable, so the list covers having both decks at once;
- cards a proxy stands in for in the deck's box are listed apart ("covered by proxy – to buy");
- at the bottom are the precons that contain several of the missing cards.

![Missing cards](../images/en/missing.webp)

Buttons:
- **Copy for CardMarket:** a "1 Name" list to paste into Cardmarket;
- **Copy with printings:** a list with set and collector number;
- **Download CSV;**
- **Add to shopping list** (see below);
- **Send to CardTrader** ([CardTrader](#cardtrader)).

### Cardmarket

1. Click **Copy for CardMarket**.
2. On Cardmarket: **Wants** → new list → paste into **Add decklist**.
3. Cardmarket's **Shopping Wizard** picks the sellers, e.g. the fewest shipments.

The list names no printings, so Cardmarket offers any.

## Shopping list

**Collection → To buy** gathers what to buy across decks:
- a deck's missing cards (**Add to shopping list** in its **Missing** tab). Adding them again
  replaces what that deck added before;
- any card from its right-click menu (**Add to shopping list**).

It goes by card, not printing. The list shows the decks a card is for, the copies you own and an
estimated price. Real copies you add to the collection afterwards count as bought and leave the
list (proxies don't). Reduce or remove entries by hand. Copy the list for Cardmarket, download it as
CSV or send it to CardTrader.

![Shopping list](../images/en/shopping-list.webp)

## Where to buy

Card search links per shop and a basket planner. Allegro gives no API access to other sellers'
offers or to the cart, so the app **only opens searches in your browser**: it fetches nothing from
Allegro or the sellers' shops.

### Shops (Settings → Where to buy)

Each shop is a search address with `{query}` where the search phrase goes. **Allegro** is there to
start with (`https://allegro.pl/listing?string={query}`, " mtg" added); you can edit or disable it.

To add a favourite seller:
1. Search for something in their Allegro shop or their own web shop.
2. Copy the address of the results page.
3. **Add a shop**, paste the address and replace the search phrase with `{query}`.
4. **Test** opens a search for "Sol Ring".

A shop's options:
- **Search for:** the card name, or the card name with the set name;
- **Added to the phrase:** e.g. " mtg" (with a leading space);
- **Free delivery from** and **Shipping below it:** when the seller has their own rules (empty =
  the general settings). A shop named like an offer's seller sets that seller's threshold.

A double-faced card is searched by its front face ("Delver of Secrets").

### Where the links are

- **Buy ▾** next to a card in the **Missing** tab, **Collection → To buy**, **Collection →
  Proxies** (proxies of cards you don't own yet) and the card detail panel: one link per enabled
  shop.
- The deckbuilder's **Shopping** tab (or **Shopping list** in the **Missing** tab).

### The Shopping tab

The deck's cards to buy: missing ones and those a proxy stands in for (reason: missing / proxy),
with the copies needed and a column of links per shop.

- **Done:** tick a card off when bought or ordered. Kept per deck, so you can work through the list
  over several sessions. **Untick all** starts over.
- **Open selected:** opens the selected cards' searches at the chosen shop. The window app opens
  them in your system browser, one tab each. In a browser the first one opens and the others are
  listed as links (browsers block several pop-ups from one click). Above 10 tabs the app asks first.
- **Copy for CardMarket:** compare prices for the whole list on CardMarket (filter sellers by
  country: Poland).

### Basket planner

Allegro Smart! gives free delivery from a minimum order **per single seller** (49.90 PLN since 2
March 2026; it changes over time, set it in **Settings → Where to buy**). With cards at 1–5 PLN it
pays to buy from 1–2 sellers, even if single cards are a bit dearer there.

1. **+ offer** next to a card: the seller (suggested from earlier ones), the price per copy,
   optionally the copies available and the offer link. **Enter** saves and moves to the next card
   with the same seller.
2. A card's first offer is chosen right away; pick another with its radio button. **Cheapest** /
   **Cheapest for all** choose the cheapest offers.
3. **Basket by seller:** each seller with the chosen cards, the subtotal and a progress bar to free
   delivery. Below the threshold the app suggests cards this seller also has (with the price
   difference); **add** moves the choice there.
4. The summary: cards + estimated shipping (0 above the threshold) and the number of parcels.
   **Open offers** opens the seller's offer links, **Copy list** copies "1 Card – price".
5. **Suggest basket** picks one offer per card so that cards + shipping cost the least. Accept or
   discard the proposal; nothing changes until you accept.

Cards ticked as done stay out of the basket. Offers and choices are kept per deck (in the backup
too).

### Compare with CardTrader Zero

With a CardTrader token ([CardTrader](#cardtrader)), **Fetch CardTrader offers** looks up the
cheapest offers of sellers shipping through CardTrader Zero for every card (one parcel, one fee;
18 USD by default). Prices are converted with the exchange rates typed in the settings.

The comparison shows three options: the sellers' chosen offers, everything from CardTrader Zero,
and **mixed** (cheaper cards to CardTrader, as long as no seller drops below their free-delivery
threshold). Cards CardTrader Zero doesn't have are listed apart. **Send to CardTrader cart** adds
the mixed option's CardTrader offers to your cart on CardTrader; you make the purchase on the site.

## CardTrader

The shopping list can be kept as one private wishlist on [CardTrader](https://www.cardtrader.com),
updated with one click.

### Connecting (once)

1. On CardTrader, open your profile settings and copy your **API token**.
2. In the app: **Settings → CardTrader**, paste the token and click **Connect**. The app checks it
   with CardTrader.
3. Optionally pick the **Language of the cards on the wishlist** (any by default).

![CardTrader settings](../images/en/settings-cardtrader.webp)

The token stays on this computer: it's never part of a backup or the cloud backup folder.
**Disconnect** removes it. If the token ever leaks, generate a new one on CardTrader.

### Sending

- On the shopping list, click **Send to CardTrader**: the wishlist "MTG Deck Manager – to buy" gets
  the whole shopping list (any printing).
- In a deck's **Missing** tab, the same button first puts the deck's missing cards on the shopping
  list, then updates the wishlist.

CardTrader's API can't edit a wishlist, so each send creates a new one and deletes the previous
one. **Changes made on CardTrader are overwritten**: take cards you don't want to buy (too
expensive, say) off the shopping list in the app. An empty shopping list removes the wishlist.

CardTrader silently drops cards it doesn't recognize. The app reads the wishlist back after sending
and lists those cards, so you can add them there by hand. If the chosen language isn't kept, the
app says so too.
