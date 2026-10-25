"""Messages the API returns to the UI (validation, import warnings, errors), in the UI language.

The language comes from the request's Accept-Language header (the frontend sends its own) and is
kept in a context variable, so code deep in a request calls tr() without passing it around.
Polish is the default (the CLI, requests without the header)."""

from contextvars import ContextVar
from typing import Literal

Lang = Literal["pl", "en"]
LANGS: tuple[Lang, ...] = ("pl", "en")

_lang: ContextVar[Lang] = ContextVar("lang", default="pl")

MESSAGES: dict[str, dict[Lang, str]] = {
    # deck validation
    "deck_size_exact": {
        "pl": "Talia ma {size} kart, a powinna mieć dokładnie {target} (z dowódcą).",
        "en": "The deck has {size} cards; it must have exactly {target} (including the commander).",
    },
    "no_commander": {"pl": "Talia nie ma dowódcy.", "en": "The deck has no commander."},
    "too_many_commanders": {
        "pl": "Talia może mieć najwyżej dwóch dowódców.",
        "en": "A deck can have at most two commanders.",
    },
    "invalid_commander": {
        "pl": "{name} nie może być dowódcą (wymagana legendarna istota).",
        "en": "{name} can't be a commander (a legendary creature is required).",
    },
    "invalid_commander_pw": {
        "pl": "{name} nie może być dowódcą (wymagana legendarna istota lub planeswalker).",
        "en": "{name} can't be a commander (a legendary creature or planeswalker is required).",
    },
    "invalid_partner": {
        "pl": "{first} i {second} nie mogą być razem dowódcami "
              "(potrzebny Partner, Friends forever, Doctor's companion lub Background).",
        "en": "{first} and {second} can't be commanders together "
              "(Partner, Friends forever, Doctor's companion or Background is needed).",
    },
    "color_identity": {
        "pl": "Karty spoza tożsamości kolorów dowódcy ({identity}): {names}",
        "en": "Cards outside the commander's color identity ({identity}): {names}",
    },
    "colorless": {"pl": "bezbarwna", "en": "colorless"},
    "colorless_basics": {
        "pl": "Przy bezbarwnym dowódcy dozwolone są podstawowe lądy tylko jednego typu: {names}",
        "en": "With a colorless commander, basic lands of only one type are allowed: {names}",
    },
    "no_sideboard": {
        "pl": "{format} nie ma sideboardu – {n} kart w sideboardzie nie zostanie uwzględnionych.",
        "en": "{format} has no sideboard – the {n} sideboard cards won't be used.",
    },
    "companions": {"pl": "Można mieć tylko jednego companiona.", "en": "Only one companion is allowed."},
    "deck_size_min": {
        "pl": "Talia ma {size} kart, minimum to {min}.",
        "en": "The deck has {size} cards; the minimum is {min}.",
    },
    "sideboard_size": {
        "pl": "Sideboard ma {size} kart, maksimum to {max}.",
        "en": "The sideboard has {size} cards; the maximum is {max}.",
    },
    "singleton": {
        "pl": "Singleton: każda karta (poza podstawowymi lądami) może wystąpić tylko raz – {detail}",
        "en": "Singleton: each card (except basic lands) may appear only once – {detail}",
    },
    "max_copies": {
        "pl": "Najwyżej {n} kopie karty (poza podstawowymi lądami) – {detail}",
        "en": "At most {n} copies of a card (except basic lands) – {detail}",
    },
    "banned": {"pl": "Zbanowane w {format}: {names}", "en": "Banned in {format}: {names}"},
    "not_legal": {"pl": "Nielegalne w {format}: {names}", "en": "Not legal in {format}: {names}"},
    "not_on_arena": {"pl": "Karty niedostępne na Arenie: {names}", "en": "Cards not available on Arena: {names}"},
    "arena_printing": {
        "pl": "Wybrane wydania nie są na Arenie (eksport użyje innych): {names}",
        "en": "The chosen printings aren't on Arena (the export uses others): {names}",
    },
    "digital_only": {
        "pl": "Karty tylko cyfrowe w talii papierowej: {names}",
        "en": "Digital-only cards in a paper deck: {names}",
    },
    "land_count": {
        "pl": "{lands} lądów – typowo {low}–{high} dla talii {target}-kartowej.",
        "en": "{lands} lands – typically {low}–{high} for a {target}-card deck.",
    },
    "not_in_collection": {
        "pl": "Brakuje w kolekcji {n} kart: {names}",
        "en": "{n} cards missing from the collection: {names}",
    },
    "and_more": {"pl": " i {n} innych", "en": " and {n} more"},
    # decklist import
    "alchemy": {
        "pl": "„{name}” to karta Alchemy (przebalansowana) – Scryfall jej nie ma, użyto oryginału „{original}”",
        "en": "“{name}” is an Alchemy (rebalanced) card – Scryfall doesn't have it, used the original “{original}”",
    },
    "printed_name": {
        "pl": "Dopasowano po nazwie drukowanej (inny język): „{name}”",
        "en": "Matched by printed name (another language): “{name}”",
    },
    "no_number_in_set": {
        "pl": "Brak numeru {number} w secie {set} – użyto #{used}",
        "en": "No number {number} in set {set} – used #{used}",
    },
    "not_in_set": {
        "pl": "Karta nie występuje w secie {set} – użyto innego wydania",
        "en": "The card isn't in set {set} – used another printing",
    },
    "card_not_on_arena": {"pl": "Karta niedostępna na Arenie", "en": "The card isn't available on Arena"},
    "printing_not_on_arena": {
        "pl": "Wybrane wydanie nie jest dostępne na Arenie",
        "en": "The chosen printing isn't available on Arena",
    },
    "digital_card": {
        "pl": "Karta tylko cyfrowa (nie istnieje w wersji papierowej)",
        "en": "Digital-only card (doesn't exist in paper)",
    },
    "bad_line": {
        "pl": "Nie rozpoznano linii (oczekiwano np. „1 Nazwa (SET) 123”)",
        "en": "Unrecognized line (expected e.g. “1 Name (SET) 123”)",
    },
    "bad_quantity": {"pl": "Ilość musi być większa od zera", "en": "The quantity must be greater than zero"},
    "export_swapped": {
        "pl": "{name}: wydanie {printing} nie jest na Arenie – użyto {set} #{number}",
        "en": "{name}: printing {printing} isn't on Arena – used {set} #{number}",
    },
    # search syntax
    "unknown_filter": {"pl": "Nieznany filtr „{key}:”", "en": "Unknown filter “{key}:”"},
    "empty_filter": {"pl": "Pusty filtr „{text}”", "en": "Empty filter “{text}”"},
    "unknown_format": {"pl": "Nieznany format „{value}”", "en": "Unknown format “{value}”"},
    "mv_number": {
        "pl": "mv wymaga liczby, np. mv>=3 (jest „{value}”)",
        "en": "mv needs a number, e.g. mv>=3 (got “{value}”)",
    },
    "unknown_rarity": {"pl": "Nieznana rzadkość „{value}”", "en": "Unknown rarity “{value}”"},
    "rarity_compare": {
        "pl": "Porównania rzadkości działają dla common/uncommon/rare/mythic",
        "en": "Rarity comparisons work for common/uncommon/rare/mythic",
    },
    "unsupported_filter": {"pl": "Nieobsługiwany filtr „{key}”", "en": "Unsupported filter “{key}”"},
    "unknown_colors": {
        "pl": "Nieznane kolory „{colors}” (użyj W U B R G C)",
        "en": "Unknown colors “{colors}” (use W U B R G C)",
    },
    "unsupported_operator": {"pl": "Nieobsługiwany operator „{op}”", "en": "Unsupported operator “{op}”"},
    # scans
    "scan_bad_type": {
        "pl": "Nieobsługiwany format pliku (JPG, PNG, HEIC, WEBP, TIFF, PDF).",
        "en": "Unsupported file type (JPG, PNG, HEIC, WEBP, TIFF, PDF).",
    },
    "scan_heic_macos_only": {
        "pl": "Zdjęcia HEIC obsługuje tylko wersja na macOS. Zapisz zdjęcie jako JPG "
              "(iPhone: Ustawienia → Aparat → Formaty → Najbardziej zgodne).",
        "en": "HEIC photos are supported on macOS only. Save the photo as JPG "
              "(iPhone: Settings → Camera → Formats → Most Compatible).",
    },
    "scan_bad_image": {"pl": "Nie udało się odczytać obrazu: {error}", "en": "Could not read the image: {error}"},
    "scan_bad_pdf": {"pl": "Nie udało się odczytać PDF: {error}", "en": "Could not read the PDF: {error}"},
    "scan_pdf_pages": {
        "pl": "PDF ma {n} stron (maks. {max}).",
        "en": "The PDF has {n} pages (max. {max}).",
    },
    "scan_too_large": {"pl": "Plik jest za duży (maks. 40 MB).", "en": "The file is too large (max. 40 MB)."},
    "scan_failed": {"pl": "Rozpoznawanie nie powiodło się: {error}", "en": "Recognition failed: {error}"},
    "scan_committed": {"pl": "Ten skan jest już w kolekcji.", "en": "This scan is already in the collection."},
    "scan_no_file": {"pl": "Brak pliku skanu.", "en": "The scan file is missing."},
    "unknown_card": {"pl": "Nieznana karta", "en": "Unknown card"},
    "reason_name": {"pl": "nazwa", "en": "name"},
    "reason_name_mismatch": {"pl": "nazwa się nie zgadza", "en": "name doesn't match"},
    "reason_name_score": {"pl": "nazwa {score}%", "en": "name {score}%"},
    "reason_number": {"pl": "numer", "en": "number"},
    "reason_artist": {"pl": "artysta", "en": "artist"},
    "reason_year": {"pl": "rok", "en": "year"},
    "reason_image": {"pl": "obraz {distance}", "en": "image {distance}"},
    "reason_frame": {"pl": "ramka", "en": "frame"},
    "reason_same_art": {"pl": "ta sama ilustracja", "en": "same illustration"},
    # Moxfield collection CSV
    "moxfield_no_header": {
        "pl": "To nie jest CSV kolekcji Moxfielda (brak kolumny „Name”).",
        "en": "This is not a Moxfield collection CSV (no “Name” column).",
    },
    "moxfield_unknown_condition": {
        "pl": "Nieznany stan „{value}” – przyjęto NM",
        "en": "Unknown condition “{value}” – using NM",
    },
    "moxfield_unknown_language": {
        "pl": "Nieznany język „{value}” – przyjęto angielski",
        "en": "Unknown language “{value}” – using English",
    },
    "moxfield_finish": {
        "pl": "To wydanie nie ma wersji „{finish}”",
        "en": "This printing has no “{finish}” version",
    },
    # backup, versions
    "backup_not_ours": {
        "pl": "To nie jest plik kopii zapasowej MTG Deck Manager.",
        "en": "This is not an MTG Deck Manager backup file.",
    },
    "backup_newer": {
        "pl": "Kopia pochodzi z nowszej wersji aplikacji.",
        "en": "The backup comes from a newer version of the app.",
    },
    "backup_broken": {"pl": "Uszkodzony plik kopii: {error}", "en": "Damaged backup file: {error}"},
    "no_changes": {"pl": "Brak zmian od ostatniej wersji", "en": "No changes since the last version"},
    # proxy printing (PDF texts)
    "print_footer_page": {"pl": "{title} · strona {page}/{pages}", "en": "{title} · page {page}/{pages}"},
    "print_uncalibrated": {"pl": "Drukarka nieskalibrowana (skala 1,0)", "en": "Uncalibrated printer (scale 1.0)"},
    "print_profile": {"pl": "{name} · skala x {x:.4f}, y {y:.4f}", "en": "{name} · scale x {x:.4f}, y {y:.4f}"},
    "print_actual_size": {
        "pl": "Drukuj w 100% / rozmiar rzeczywisty, bez „Dopasuj do strony”",
        "en": "Print at 100% / Actual size – do not “Fit to page”",
    },
    "print_calibration_title": {"pl": "Kalibracja drukarki", "en": "Printer calibration"},
    "print_verification": {"pl": "Strona weryfikacyjna", "en": "Verification page"},
    "print_card_size": {"pl": "{w:.1f} × {h:.1f} mm", "en": "{w:.1f} × {h:.1f} mm"},
    "print_measure_a": {"pl": "A = {mm:.1f} mm (szerokość siatki)", "en": "A = {mm:.1f} mm (grid width)"},
    "print_measure_b": {"pl": "B = {mm:.1f} mm (wysokość)", "en": "B = {mm:.1f} mm (grid height)"},
    "print_measure_left": {
        "pl": "Od lewej krawędzi papieru do siatki: {mm:.1f} mm",
        "en": "Left paper edge to grid: {mm:.1f} mm",
    },
    "print_measure_top": {
        "pl": "Od górnej krawędzi papieru do siatki: {mm:.1f} mm",
        "en": "Top paper edge to grid: {mm:.1f} mm",
    },
    "print_calibration_steps": {
        "pl": "1. Drukuj w 100% / rozmiar rzeczywisty.\n"
              "2. Wyłącz „Dopasuj do strony” i „Zmniejsz za duże strony”.\n"
              "3. Ten sam papier i podajnik co do proxy.\n"
              "4. Zmierz A i B linijką lub suwmiarką (do 0,5 mm),\n"
              "    po zewnętrznych krawędziach ramek.\n"
              "5. Opcjonalnie: odległości od krawędzi papieru.\n"
              "6. Wpisz wyniki w Ustawienia › Drukowanie.",
        "en": "1. Print at 100% / Actual size.\n"
              "2. Turn off “Fit to page” and “Shrink oversized pages”.\n"
              "3. Use the paper and tray you'll print proxies on.\n"
              "4. Measure A and B with a ruler or calipers (to 0.5 mm),\n"
              "    along the outer edges of the frames.\n"
              "5. Optional: the distances from the paper edges.\n"
              "6. Enter them in Settings › Printing.",
    },
    "print_duplex_title": {"pl": "Test druku dwustronnego", "en": "Two-sided print test"},
    "print_duplex_long": {"pl": "obracanie wzdłuż dłuższej krawędzi", "en": "flip on long edge"},
    "print_duplex_short": {"pl": "obracanie wzdłuż krótszej krawędzi", "en": "flip on short edge"},
    "print_duplex_x": {"pl": "X: + w prawo, − w lewo", "en": "X: + right, − left"},
    "print_duplex_y": {"pl": "Y: + w dół, − w górę", "en": "Y: + down, − up"},
    "print_duplex_steps": {
        "pl": "1. Drukuj dwustronnie w 100%, {mode}, na papierze do proxy.\n"
              "2. Obejrzyj kartkę od przodu pod światło (okno, lampa).\n"
              "3. Odczytaj, gdzie linie z tyłu przecinają podziałki (co 0,5 mm): X i Y.\n"
              "4. Wpisz obie liczby w Ustawienia › Drukowanie; 0 i 0 = tył idealnie pod przodem.",
        "en": "1. Print two-sided at 100%, {mode}, on your proxy paper.\n"
              "2. Look at the front of the sheet against the light (window, lamp).\n"
              "3. Read where the back's lines cross the scales (0.5 mm ticks): X and Y.\n"
              "4. Enter both in Settings › Printing; 0 and 0 = the back is right behind the front.",
    },
    "print_proxy_mark": {"pl": "Proxy – nie do sprzedaży", "en": "Proxy – not for sale"},
    "not_a_proxy": {
        "pl": "To nie jest proxy (albo ten egzemplarz nie leży luzem, więc nie można go przenieść).",
        "en": "That's not a proxy (or that copy isn't loose, so it can't be moved).",
    },
    "deck_proxies": {
        "pl": "{n} kart(y) w tej talii to proxy.",
        "en": "{n} cards in this deck are proxies.",
    },
    "print_history_not_found": {"pl": "Nie ma takiego wydruku.", "en": "No such print."},
    "print_choose_location": {
        "pl": "Ten wydruk nie jest z talii: wybierz, gdzie oznaczyć proxy.",
        "en": "This print isn't from a deck: choose where to put the proxies.",
    },
    "cloud_folder_error": {
        "pl": "Nie da się zapisać w tym folderze: {error}",
        "en": "Can't write to that folder: {error}",
    },
    "precon_not_found": {"pl": "Nie ma takiej talii.", "en": "No such deck."},
    "cardtrader_bad_token": {
        "pl": "CardTrader nie przyjął tokenu – sprawdź go w ustawieniach profilu CardTrader.",
        "en": "CardTrader didn't accept the token – check it in your CardTrader profile settings.",
    },
    "cardtrader_no_token": {
        "pl": "Najpierw dodaj token CardTrader w Ustawieniach.",
        "en": "Add your CardTrader token in Settings first.",
    },
    "cardtrader_failed": {"pl": "CardTrader zwrócił błąd: {error}", "en": "CardTrader returned an error: {error}"},
    "cardtrader_offline": {
        "pl": "Nie udało się połączyć z CardTrader (brak internetu?): {error}",
        "en": "Couldn't reach CardTrader (offline?): {error}",
    },
    "cardtrader_nothing": {"pl": "Nie ma nic do kupienia.", "en": "There's nothing to buy."},
    "cardtrader_wishlist": {"pl": "MTG Deck Manager – do kupienia", "en": "MTG Deck Manager – to buy"},
    "combos_failed": {
        "pl": "Nie udało się pobrać combo z Commander Spellbook (brak internetu?): {error}",
        "en": "Couldn't get combos from Commander Spellbook (offline?): {error}",
    },
    "precon_download_failed": {
        "pl": "Nie udało się pobrać talii z MTGJSON (brak internetu?): {error}",
        "en": "Couldn't download the deck from MTGJSON (offline?): {error}",
    },
    "print_profile_not_found": {"pl": "Nie ma takiego profilu drukarki.", "en": "No such printer profile."},
    "print_job_not_found": {"pl": "Nie ma takiego wydruku.", "en": "No such print job."},
    "print_nothing": {"pl": "Nie wybrano żadnej karty do druku.", "en": "No cards selected for printing."},
    # app window (native dialogs, shown before the UI is up)
    "window_failed": {
        "pl": "Nie można otworzyć okna aplikacji.\n\n{error}\n\nSzczegóły w logu:\n{log}",
        "en": "Could not open the app window.\n\n{error}\n\nDetails are in the log:\n{log}",
    },
    "webview2_missing": {
        "pl": "Nie można otworzyć okna aplikacji: brakuje Microsoft Edge WebView2 Runtime.\n\n"
              "Zainstaluj go ze strony:\nhttps://developer.microsoft.com/microsoft-edge/webview2/",
        "en": "Could not open the app window: Microsoft Edge WebView2 Runtime is missing.\n\n"
              "Install it from:\nhttps://developer.microsoft.com/microsoft-edge/webview2/",
    },
}


def tr(key: str, /, **params: object) -> str:
    entry = MESSAGES[key]
    return (entry.get(_lang.get()) or entry["pl"]).format(**params)


def current_lang() -> Lang:
    return _lang.get()


def set_lang(lang: Lang):
    """Returns a token for ContextVar.reset (tests, CLI)."""
    return _lang.set(lang)


def parse_accept_language(header: str | None) -> Lang:
    for part in (header or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code  # type: ignore[return-value]
    return "pl"


class LanguageMiddleware:
    """Pure ASGI middleware: sets the message language for the duration of each request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        token = _lang.set(parse_accept_language(headers.get(b"accept-language", b"").decode("latin-1")))
        try:
            await self.app(scope, receive, send)
        finally:
            _lang.reset(token)
