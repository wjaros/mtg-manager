# Import i eksport

[← Spis treści](index.md)

**Import** ma trzy zakładki: **Talia**, **Kolekcja** i **Precony**.

![Import](../images/pl/import.webp)

## Import talii

1. Wklej listę z MTG Arena albo Moxfielda (np. `4 Lightning Bolt (M10) 146`). Przykładowe listy są
   nad polem.
2. **Analizuj listę** pokazuje raport dopasowania: dokładne wydania, ostrzeżenia, podpowiedzi przy
   nieznalezionych kartach.
3. Po sprawdzeniu zapisz talię. Nic nie zapisuje się przed tym krokiem.

## Precony

**Precony** to lista oficjalnych talii Commander (z [MTGJSON](https://mtgjson.com), pobierana razem
z danymi kart). Przy każdej widać kolory, ile kart z niej masz i wartość kart. Precon wczytasz też
w zakładce **Talia**, wyszukując go po nazwie, dowódcy albo kodzie setu.

W zakładce **Braki** talii aplikacja podpowiada precony, które zawierają kilka brakujących kart.

## Import kolekcji

Zakładka **Kolekcja**:
- **Lista kart:** lista w formacie Areny (np. zawartość produktu, który nie jest talią):
  `4 Nazwa (SET) 123`. Sekcje i komentarze `#` są dozwolone, a `# preferred-sets: tle, tla`
  wybiera wydania;
- **CSV z Moxfielda:** plik z eksportu kolekcji Moxfielda.

Najpierw dostajesz raport; nic nie zapisuje się, dopóki nie dodasz kart.

## Eksport

**Talia** (przycisk **Eksport** w deckbuilderze):
- **MTG Arena:** wydań, których nie ma na Arenie, aplikacja używa zamienników i to wypisuje;
- **lista tekstowa** z wydaniami;
- **PDF** z jedną kartą na stronę, do przeglądania talii na telefonie.

**Kolekcja** (zakładka **Egzemplarze**):
- **Kopiuj listę (format Areny):** `4 Nazwa (SET) 123`;
- **CSV;**
- **CSV dla Moxfielda:** w Moxfieldzie Collection → Import → Moxfield format. Stany są przeliczane
  na skalę Moxfielda.

**Braki i lista zakupów:** dla Cardmarketu, CSV i CardTradera ([Braki i zakupy](buying.md)).

**Całość:** kopia zapasowa JSON ([Ustawienia](settings.md#kopia-zapasowa)).
