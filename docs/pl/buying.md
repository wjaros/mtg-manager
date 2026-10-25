# Braki i zakupy

[← Spis treści](index.md)

## Braki talii

Zakładka **Braki** w deckbuilderze (talia papierowa) pokazuje karty, których brakuje, z ceną
orientacyjną:

- **Nie licz kart z pudełek innych talii:** karty wbudowane w inne talie liczą się jako
  niedostępne, więc lista pokazuje, co kupić, żeby mieć obie talie naraz;
- karty, za które w pudełku stoi proxy, są osobno („pokryte przez proxy – do kupienia”);
- na dole są precony, które zawierają kilka brakujących kart.

![Braki talii](../images/pl/missing.webp)

Przyciski:
- **Kopiuj dla CardMarket:** lista „1 Nazwa” do wklejenia na Cardmarket;
- **Kopiuj z wydaniami:** lista z setem i numerem karty;
- **Pobierz CSV;**
- **Dodaj do listy zakupów** (opis niżej);
- **Wyślij do CardTrader** ([CardTrader](#cardtrader)).

### Cardmarket

1. Kliknij **Kopiuj dla CardMarket**.
2. Na Cardmarket: **Wants** → nowa lista → wklej w **Add decklist**.
3. **Shopping Wizard** Cardmarketu dobierze sprzedawców, np. z najmniejszą liczbą przesyłek.

Lista nie podaje wydań, więc Cardmarket pokaże każde.

## Lista zakupów

**Kolekcja → Do kupienia** zbiera karty do kupienia ze wszystkich talii. Trafiają na nią:
- braki talii (**Dodaj do listy zakupów** w zakładce **Braki**). Ponowne dodanie zastępuje to, co
  ta talia dodała wcześniej;
- dowolna karta z menu prawego przycisku (**Dodaj do listy zakupów**).

Liczy się karta, a nie wydanie. Lista pokazuje, dla których talii jest karta, ile kopii już masz i
cenę orientacyjną. Prawdziwe egzemplarze dodane do kolekcji później liczą się jako kupione i
znikają z listy (proxy się nie liczą). Pozycje zmniejszysz albo usuniesz ręcznie. Listę skopiujesz
dla Cardmarketu, pobierzesz jako CSV albo wyślesz do CardTradera.

![Lista zakupów](../images/pl/shopping-list.webp)

## CardTrader

Lista zakupów może być jedną prywatną wishlistą w [CardTrader](https://www.cardtrader.com),
aktualizowaną jednym kliknięciem.

### Połączenie (raz)

1. Na stronie CardTrader otwórz ustawienia swojego profilu i skopiuj **token API**.
2. W aplikacji: **Ustawienia → CardTrader**, wklej token i kliknij **Połącz**. Aplikacja sprawdzi
   token w CardTraderze.
3. Opcjonalnie wybierz **Język kart na wishliście** (domyślnie dowolny).

![Ustawienia CardTrader](../images/pl/settings-cardtrader.webp)

Token zostaje tylko na tym komputerze: nie trafia do kopii zapasowej ani do folderu kopii w
chmurze. **Odłącz** go usuwa. Jeśli token wycieknie, wygeneruj w CardTraderze nowy.

### Wysyłanie

- Na liście zakupów kliknij **Wyślij do CardTrader**: wishlista „MTG Deck Manager – do kupienia”
  dostaje całą listę zakupów (dowolne wydanie).
- W zakładce **Braki** ten sam przycisk najpierw dopisuje braki talii do listy zakupów, a potem
  aktualizuje wishlistę.

API CardTradera nie pozwala edytować wishlisty, więc każda wysyłka tworzy nową i usuwa poprzednią.
**Zmiany zrobione na CardTraderze zostaną nadpisane**: kart, których nie chcesz kupować (np. za
drogich), usuwaj z listy zakupów w aplikacji. Pusta lista zakupów usuwa wishlistę.

CardTrader po cichu pomija karty, których nie rozpozna. Aplikacja sprawdza wishlistę po wysłaniu i
wypisuje takie karty, żebyś mógł je dodać ręcznie. Jeśli wybrany język nie zostanie zapisany,
aplikacja też to zgłosi.
