# Talie i deckbuilder

[← Spis treści](index.md)

## Lista talii

**Talie** pokazują wszystkie talie z formatem, dowódcą, kolorami i liczbą kart. **+ Nowa talia**
tworzy pustą talię. Gotową listę albo precon wczytasz w [Imporcie](import-export.md).

**×** na kafelku usuwa talię. Karty z jej pudełka zostają w kolekcji, chyba że zaznaczysz
**Usuń też z kolekcji karty z jej pudełka**: wtedy znikają z kolekcji (razem z proxy) i samo pudełko.

![Talie](../images/pl/decks.webp)

## Deckbuilder

![Deckbuilder](../images/pl/deckbuilder.webp)

**Nagłówek:**
- nazwa talii; ▾ obok niej przełącza na inną talię, na tej samej zakładce;
- format: Commander, Brawl, Standard Brawl, Historic, Standard, Pioneer, freeform;
- platforma: papier albo Arena;
- kolory, wynik walidacji, liczba kart;
- w talii papierowej: **Prawdziwe · Proxy · Brak** (sumuje się do rozmiaru talii) i cena tego,
  czego brakuje.

**Przyciski:**
- **Mam tę talię:** przenosi karty talii do jej pudełka. Potem widać „W kolekcji ✓”, a kliknięcie
  odświeża stan. Jeśli po usuniętej talii o tej samej nazwie zostało pudełko z kartami, talia je
  przejmuje i niczego nie dodaje (karty się nie dublują);
- **Proxy:** [drukowanie proxy](proxies.md);
- **Eksport:** [eksport talii](import-export.md#eksport).

**Zakładki:** **Pula kart**, **Statystyki**, **Combo**, **Braki**, **Historia**, **Porównaj**.

### Pula kart

Pula to wyszukiwarka z tymi samymi filtrami co [Kolekcja](collection.md#wyszukiwanie):

- **Tylko karty pasujące do talii:** tożsamość kolorów dowódcy, legalność w formacie, dostępność na
  Arenie;
- **Ukryj już dodane;**
- klik dodaje kartę do talii, a prawy przycisk otwiera więcej opcji: maybeboard, sideboard,
  dowódca, [podobne karty](collection.md#podobne-karty), moje tagi, lista zakupów;
- karty można też przeciągać do talii.

Po najechaniu na kartę widać, ile kopii jest w talii, ile masz w kolekcji i gdzie leżą (np. w
pudełku innej talii). Duplikaty w formatach singleton są przygaszone.

### Lista talii, stosy i spoiler

Z prawej jest lista talii w sekcjach (dowódca, stworzenia, czary…). Wyszukasz w niej kartę przez
Cmd+F / Ctrl+F. Pod polem wyszukiwania wybierzesz grupowanie listy (typ, mana value, kolor,
rzadkość, kategoria albo bez grupowania) i sortowanie w grupach (nazwa albo mana value).

Na dole są obrazki kart talii, w jednym z dwóch widoków (przełącznik na krawędzi panelu):
- **Stosy:** karty nachodzą na siebie, jedna kolumna na grupę; domyślnie według mana value, jak na
  Arenie;
- **Spoiler:** całe karty w siatce, sekcja na grupę.

Obrazki mają własne grupowanie, sortowanie i rozmiar kart (− 100% +), niezależne od listy. Dowódca,
companion, sideboard i maybeboard są w osobnych kolumnach i sekcjach. Granicę między pulą a talią
przesuniesz, przeciągając górną krawędź talii; przy samej krawędzi zostaje sama pula albo sama
talia, a dwuklik przywraca domyślny podział. **▴ Talia** i **▾ Kolekcja** przełączają te układy
jednym kliknięciem. Klik w obrazek zdejmuje jedną kopię, a prawy przycisk otwiera menu karty.
Aplikacja pamięta te ustawienia.

Najechana karta pokazuje się powiększona obok siebie i w panelu przy talii, z wydaniem, liczbą
kopii, stanem w kolekcji i ceną. W stosach karta zostaje na miejscu (dostaje tylko obwódkę), więc
nie zasłania kart pod nią. Panel trzyma ostatnią kartę, na którą najechałeś (na początku dowódcę),
także z listy po prawej. Kartę dwustronną odwraca ⟲, a **Szczegóły i wydania** otwierają jej
szczegóły. W pasku nad talią wybierzesz **Podgląd: obok + panel**, **Podgląd: panel** (bez
powiększenia przy karcie) albo **Podgląd: obok karty** (bez panelu).

![Talia jako spoiler, z panelem podglądu](../images/pl/deck-spoiler.webp)

W talii papierowej kolor liczby przy karcie mówi, gdzie są jej egzemplarze:
- **brak:** nie masz wystarczająco kopii;
- **w innej talii:** twoje kopie leżą w pudełku innej talii (podpowiedź podaje której);
- **nie w pudełku:** masz kartę, ale nie leży w pudełku tej talii.

Prawy przycisk na karcie w talii przenosi ją między częściami talii (główna, maybeboard, sideboard,
dowódca, companion) i nadaje jej **Kategorię**: rolę w tej talii, np. „Rampa”. Kategorie liczą się
w statystykach, a grupowanie według kategorii zbiera karty o tej samej roli (karty bez kategorii
trafiają do grupy swojego typu).

### Walidacja

Reguły formatu sprawdzane są na bieżąco: rozmiar talii, liczba kopii, dowódca i jego tożsamość
kolorów, legalność kart. Wynik widać w nagłówku i nad listą talii.

## Statystyki

Zakładka **Statystyki** pokazuje:
- krzywą many, kolory (koszty i źródła many), typy i rzadkość;
- **funkcje kart** według tagów Scryfalla (ramp, draw, removal, board wipe…), które wyszukasz też
  przez `otag:`;
- **Moje tagi** i **Kategorie**;
- cenę talii i brakujących kart, a w talii z Areny potrzebne wildcardy.

![Statystyki](../images/pl/stats.webp)

![Moje tagi w statystykach](../images/pl/stats-my-tags.webp)

## Combo

Zakładka **Combo** pokazuje combo z [Commander Spellbook](https://commanderspellbook.com):

- **W talii:** combo z samych kart talii;
- **Brakuje jednej karty:** brakującą kartę dodasz jednym kliknięciem.

**Jak to działa** rozwija wymagania i kroki combo.

![Combo](../images/pl/combos.webp)

## Historia wersji

Talia zapisuje się na bieżąco. **Zapisz wersję** robi migawkę, a wszystko od ostatniej migawki jest
podświetlone: dodane karty na zielono, usunięte przekreślone na czerwono, zmienione wydania na
żółto. Wersje można porównywać i przywracać, a niezapisane zmiany odrzucić.

![Historia](../images/pl/history.webp)

## Porównanie talii

Zakładka **Porównaj** zestawia tę talię (A) z inną (B), np. papierowego Quintoriusa z arenowym.
Talię B wybierasz z listy; aplikacja sama podpowiada talię z tym samym dowódcą. Karty porównywane
są po nazwie (dowolne wydanie); liczą się dowódca, talia główna i companion.

- **Obok siebie:** A po lewej, B po prawej, każda karta w jednym wierszu, z kosztem many i ceną;
  po stronie talii, która jej nie ma, puste miejsce (albo powód, dla którego karta tam nie pasuje).
  Kolory: to, czego brakuje w drugiej talii, na czerwono po stronie A, na zielono po stronie B.
- **Tabela:** karta, koszt many, liczba kopii w A i w B, cena. Kolory: tylko w A (czerwony), tylko
  w B (zielony), różna liczba (żółty).
- **Diff:** linia pod linią, jak w porównaniu plików: `− 2 Karta` dla A, `+ 1 Karta` dla B.
- **Sortowanie:** mana value rosnąco (domyślnie) albo malejąco, z nagłówkiem dla każdej wartości;
  cena od najdroższych albo od najtańszych; nazwa. Karty o tym samym koszcie (albo cenie) idą
  alfabetycznie, **A→Z** albo **Z→A**.
- **Pokaż wspólne** dodaje karty, które obie talie mają tak samo.
- Nad listą jest podsumowanie: ile kart jest tylko w A, tylko w B, z różną liczbą, wspólnych, i
  wartość orientacyjna obu talii.

![Porównanie talii: obok siebie](../images/pl/compare-side.webp)

Najechanie na nazwę karty pokazuje jej podgląd i krótką informację dla obu talii: ile kopii jest w
talii, czy kartę można dodać, a jeśli nie, to dlaczego (nielegalna w formacie, poza kolorami
dowódcy, brak na Arenie).

**→** i **←** (w tabeli i diffie **→ B** i **← A**) dodają brakujące kopie do drugiej talii, ale
tylko gdy karta może tam trafić: jest legalna w formacie, mieści się w kolorach dowódcy, a dla
talii z Areny jest na Arenie. W formatach singleton dodawana jest najwyżej jedna kopia. Do talii z
Areny trafia wydanie z Areny, do papierowej to, którego masz najwięcej kopii (albo domyślne).

Gdy karta nie może trafić do drugiej talii (np. nielegalna w Brawl), prawy przycisk na jej nazwie
daje **Podobne karty dla A** albo **dla B**: [podobne karty](collection.md#podobne-karty) legalne w
formacie tamtej talii i, dla talii z Areny, na Arenie. Lista zaczyna od kolorów karty, które
mieszczą się w kolorach dowódcy tej talii (a gdy żaden się nie mieści, od kolorów dowódcy).
Kliknięcie dodaje kartę do tej talii (w formatach singleton jedną kopię).

![Porównanie talii: tabela według ceny](../images/pl/compare.webp)

![Porównanie talii: diff](../images/pl/compare-diff.webp)

## Braki

Zakładka **Braki** pokazuje, czego brakuje do talii papierowej, i pozwala to kupić: opis w
[Braki i zakupy](buying.md).
