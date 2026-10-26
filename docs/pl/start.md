# Pierwsze kroki

[← Spis treści](index.md)

## Instalacja

Pobierz najnowszą wersję ze strony [Releases](https://github.com/wjaros/mtg-manager/releases):

- **macOS:** plik `…-arm64.dmg` dla procesorów Apple Silicon (M1–M4) albo `…-x86_64.dmg` dla
  Intela. Otwórz DMG i przeciągnij aplikację do folderu Programy. Aplikacja nie jest notaryzowana
  przez Apple: za pierwszym razem otwórz ją prawym przyciskiem → **Otwórz**.
- **Windows:** plik `…-windows-x64.zip`. Rozpakuj go i uruchom `MTG Deck Manager.exe`. Okno
  aplikacji korzysta z Microsoft Edge WebView2, wbudowanego w Windows 11 i aktualny Windows 10.

## Pierwsze uruchomienie: dane kart

Aplikacja potrzebuje danych kart ze Scryfalla (ok. 80 MB do pobrania, import trwa 2–3 minuty):

1. Otwórz **Ustawienia** (menu po lewej).
2. W sekcji **Dane kart (Scryfall)** kliknij **Pobierz dane kart**.
3. Poczekaj na koniec paska postępu. Razem z kartami pobierają się funkcje kart (tagi Scryfalla:
   ramp, removal, draw…) i listy preconów.

![Ustawienia: dane kart](../images/pl/settings-card-data.webp)

Dane warto co jakiś czas odświeżyć (**Odśwież dane**). Aplikacja podpowiada to sama, gdy Scryfall
ma nowsze dane: raz w tygodniu albo po premierze dodatku w zupełności wystarczy. Ceny w danych
Scryfalla mają do doby opóźnienia, dlatego aplikacja pokazuje je jako orientacyjne, z datą.

## Układ aplikacji

Menu po lewej prowadzi do pięciu części:

- **[Kolekcja](collection.md):** wszystkie karty, twoje egzemplarze, lokalizacje, proxy i lista
  zakupów.
- **[Talie](decks.md):** lista talii i deckbuilder.
- **[Import](import-export.md):** listy talii, precony i kolekcje.
- **[Skanowanie](scanning.md):** dodawanie kart do kolekcji ze zdjęć i skanów.
- **[Ustawienia](settings.md):** dane kart, język, kopie zapasowe, drukowanie, CardTrader.

**Zwiń menu** na dole menu zostawia same ikony (nazwa w podpowiedzi), żeby zrobić więcej miejsca;
strzałka rozwija je z powrotem. Aplikacja pamięta wybór.

## Język

Interfejs jest po polsku i po angielsku: **Ustawienia → Język / Language**. Zmiana języka
przeładowuje aplikację.

## Aktualizacje aplikacji

Przy starcie aplikacja sprawdza na GitHubie (najwyżej co kilka godzin), czy jest nowa wersja.
Jeśli jest, pokazuje, co się zmieniło, i przycisk pobrania wersji dla twojego systemu. **Pomiń tę
wersję** wyłącza przypomnienia do następnego wydania. Sprawdzanie można wyłączyć w
**Ustawienia → Aplikacja**. Instalacja nie jest automatyczna: pobierz nową wersję i zastąp starą.
Twoje dane zostają, bo leżą w osobnym folderze.

## Gdzie są twoje dane

- macOS: `~/Library/Application Support/MTGDeckManager/`
- Windows: `%APPDATA%\MTGDeckManager\`

W tym folderze są baza danych, obrazy kart, skany i log. O kopiach zapasowych przeczytasz w
[Ustawieniach](settings.md#kopia-zapasowa).
