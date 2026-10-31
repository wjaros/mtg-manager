# Import i eksport

[← Spis treści](index.md)

**Import** ma cztery zakładki: **Talia**, **Kolekcja**, **Precony** i **Pudełka**.

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

## Pudełka

**Pudełka** to produkty z kilkoma małymi taliami: Beginner Box (np. Avatar: The Last Airbender –
dziesięć talii po 20 kart), Starter Kit (dwie talie), pakiety Jumpstart, Halfdecki. Listy też
pochodzą z MTGJSON, z dokładnymi wydaniami kart.

1. Wyszukaj pudełko po nazwie, secie albo nazwie talii (bez wpisywania widać najnowsze; drobna
   literówka nie przeszkadza). Pudełka pokazuje też wyszukiwarka w zakładce **Talia** – kliknięte
   otwiera się tutaj.
2. Każda talia ma kafelek z kolorami i liczbą kart; **Podgląd** pokazuje jej karty.
3. Zaznacz talie i **Połącz zaznaczone** – dwie połówki po 20 kart dają talię 40 kart. Jedna
   zaznaczona talia to osobna talia, a **Pozostałe osobno** dodaje wszystkie jeszcze nieużyte.
   Każdą talię z pudełka da się użyć raz.
4. Na liście **Talie do utworzenia** możesz zmienić nazwy i podejrzeć połączone talie.
5. **Mam to pudełko** od razu dodaje karty do kolekcji: każda nowa talia trafia do swojego
   pudełka (jak „Mam tę talię”), a nieużyte talie możesz dodać do wybranej lokalizacji.
6. **Utwórz talie** zapisuje wszystkie naraz (format freeform).

W dużych pulach (Jumpstart ma ponad sto pakietów) karty talii pobierają się dopiero przy podglądzie
albo zaznaczeniu, a nad kafelkami jest filtr po nazwie.

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
