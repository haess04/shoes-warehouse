# Magazynier — notatka techniczna

## Aktualizacja: Material 3 — trzecia partia wizualna

- Galeria i potwierdzenia wykorzystują natywne elementy `dialog` i `showModal()`:
  przeglądarka zapewnia warstwę modalną oraz nieaktywne tło. Escape anuluje operację.
- Potwierdzenie zapamiętuje formularz i przycisk wysyłający. Dopiero akceptacja
  wywołuje `requestSubmit()`; jednorazowa zgoda zapobiega ponownemu otwarciu dialogu,
  a blokada ponownego wysłania jest resetowana po powrocie przez bfcache.
- Komunikaty z nazwami są wstawiane przez `textContent`, nie `innerHTML`.
- Lightbox ma stan wczytywania i błędu, ponowienie, licznik, nawigację cykliczną
  oraz wykrywanie poziomego gestu dotykowego. Zamknięcie przywraca fokus.
- Inspektor pozostaje widokiem odczytowym. Filtrowanie ukrywa tylko wiersze DOM;
  nie jest audytem integralności bazy ani sprawdzaniem obecności zdjęć na dysku.
- Testy Playwright sprawdzają akceptację i anulowanie z kontrolą liczby POST,
  modalność, rozmiary dialogów, pojedyncze i wielokrotne zdjęcia, błąd obrazu,
  ponowienie, symulowany gest oraz filtrowanie inspektora.
- Redesign nie wprowadza logowania, autoryzacji ani CSRF — to nadal następny etap.

## Aktualizacja: Material 3 — druga partia wizualna

- Przebudowano szablony palety i produktu bez zmian tras POST ani modeli bazy.
  Natywne sekcje `details` ograniczają liczbę stale otwartych formularzy.
- Przy HTTP 422 serwer otwiera tylko sekcję odpowiadającą ścieżce błędnego POST:
  notatki, koszt, dodawanie produktu, edycja danych, edycja sprzedaży lub zdjęcia.
- Lista butów usuwa techniczne ID z głównego widoku. Natywny lazy loading zdjęć
  zastępuje dodatkowy kod IntersectionObserver. Ścieżki mediów buduje `url_for()`.
- Galeria i sprzedaż mają osobne kolumny na komputerze; na małym ekranie panel
  sprzedaży poprzedza galerię. Usuwanie produktu pozostaje dostępne w zwijanej
  sekcji na obu typach urządzeń, z dotychczasowym potwierdzeniem.
- `app/static/app-ui.js` współdzieli obsługę formularzy, klikalnych wierszy
  i lightboxa. Zdarzenia klawiatury z linków i przycisków wewnątrz wiersza nie
  uruchamiają dodatkowego przejścia. Zamknięcie lightboxa przywraca fokus miniaturze.
- Testy rozszerzono o właściwy stan sekcji po błędach, mobilną sprzedaż,
  filtrowanie, potwierdzenia usuwania i przywracania dostępności oraz fokus galerii.

## Aktualizacja: Material 3 — pierwsza partia wizualna

- Arkusz `app/static/styles.css` zastąpiono spójnym zestawem tokenów kolorów,
  powierzchni, kształtów i stanów interakcji. Nie jest to warstwa nadpisująca
  stary styl ani integracja z zewnętrznym frameworkiem.
- `app/templates/components.html` udostępnia makro lokalnych ikon SVG. Bazowy
  layout zawiera link pominięcia nawigacji oraz czytelny fokus klawiatury.
- Strona główna ma natywny zwijany formularz, automatycznie otwierany przez
  serwer przy błędzie walidacji. JavaScript jedynie usprawnia otwieranie i fokus.
- Na małych ekranach lista palet przechodzi z tabeli w karty. Role i tekst
  dostępności paska zwrotu uwzględniają wyniki powyżej 100%.
- `tests/test_material_ui.py` dodaje kontrolę otwierania formularza, lokalnych
  zasobów i wybranych par kontrastu WCAG AA. `tests/browser_smoke.py` to osobny,
  opcjonalny zestaw Playwright/Edge do testowania rzeczywistego układu i JavaScriptu.
- Zmiana nie modyfikuje bazy ani logiki sprzedaży. Układ palety, karty buta
  i rozbudowane interakcje będą porządkowane w kolejnych partiach wizualnych.

## Aktualizacja: partia 2 — formularze i dostęp do plików

- `app/validation.py` zawiera parsery tekstów, dat, kwot i identyfikatorów oraz
  dekorator `form_handler()`. Błędy walidacji zwracają ponownie właściwy widok
  z HTTP 422 i danymi z bieżącego żądania. Formularz nie jest zapisywany w sesji.
- Dekorator sprawdza istnienie rodzica, obsługuje konflikty integralności bazy,
  błędy plików i nieudane zapisy do bazy. Kontekst sesji wycofuje transakcje.
- `form_value()` uzupełnia tylko pola formularza, który nie przeszedł walidacji.
  Potwierdzenia poprawnych operacji korzystają z mechanizmu Flask flash.
- `configure_session()` w `app/config.py` generuje trwały losowy klucz podpisu
  w ignorowanym pliku `.session-key`. To fundament komunikatów, nie logowanie.
- `app/media.py` sprawdza ścieżkę po rozwiązaniu dowiązań, rozszerzenie obrazu,
  dozwolony katalog i (dla starego układu katalogów) powiązanie z rekordem buta.
  Sam prefiks tekstowy ścieżki nie jest już kryterium bezpieczeństwa.
- Potwierdzenia usunięcia używają atrybutu danych zamiast wklejania nazw do kodu
  JavaScript. Dane z nazw zawierających cudzysłowy nie są wykonywane jako skrypt.
- Synchronizacja zdjęć raportuje wynik i pozostaje niedestrukcyjna dla plików.
- Testy regresji i bezpieczeństwa dodano w `tests/test_validation_media.py`.

## Aktualizacja: partia 1 — konfiguracja i izolacja danych

- Fabryka `create_app(config=None)` w `app/__init__.py` tworzy niezależne instancje
  Flask. Nie istnieje już globalna instancja Flask dostępna jako `app.main.app`
  przy imporcie; narzędzia integracyjne powinny korzystać z `app:create_app`.
- `app/main.py` rejestruje widoki w Blueprint `inventory`; adresy HTTP nie zmieniły
  się, natomiast nazwy endpointów mają prefiks `inventory.`.
- `app/config.py` ustala katalog danych względem projektu, niezależnie od katalogu
  terminala. `DATA_ROOT` określa wspólny katalog bazy i zdjęć.
- `init_database(app)` tworzy silnik i fabrykę sesji dla konkretnej aplikacji.
  Tabele i brakujące kolumny sprzedaży są inicjalizowane przy tworzeniu aplikacji,
  nie podczas importowania modułów. Dotychczasowe dane nie są przenoszone.
- `get_session()` korzysta z kontekstu aktywnej aplikacji i wycofuje transakcję
  po wyjątku. Silniki dwóch instancji nie współdzielą konfiguracji.
- Testy w `tests/test_foundation.py` używają tylko tymczasowych danych. Tryb
  `TESTING` nie pozwala wybrać domyślnego katalogu rzeczywistego magazynu.
- Logowanie, CSRF i backup pozostają do kolejnych partii. Poniższy opis ogólny
  miejscami pokazuje wcześniejszą organizację kodu; aktualizacje opisano powyżej.

## 1. Architektura

Magazynier jest lokalną aplikacją webową renderowaną po stronie serwera. Przeglądarka wysyła żądanie HTTP do Flask, backend odczytuje lub zapisuje dane przez SQLAlchemy, a Jinja2 generuje gotowy HTML.

Projekt nie ma osobnego frontendu React/Vue ani publicznego API. Interfejs wykorzystuje HTML, CSS i niewielkie skrypty JavaScript.

Główne technologie:

- Python i Flask — backend oraz routing,
- SQLAlchemy — ORM i zapytania do bazy,
- SQLite — lokalna baza danych,
- Jinja2 — szablony HTML,
- HTML/CSS/vanilla JavaScript — interfejs i interakcje.

## 2. Struktura projektu

```text
app/
  __init__.py
  database.py
  main.py
  models.py
  static/
    favicon.svg
    styles.css
  templates/
    base.html
    db_inspector.html
    home.html
    pallet_detail.html
    shoe_detail.html
README.md
requirements.txt
.gitignore
```

- `app/main.py` — aplikacja Flask, trasy, formularze, statystyki i synchronizacja zdjęć.
- `app/database.py` — silnik SQLite, baza modeli i fabryka sesji.
- `app/models.py` — modele ORM.
- `app/templates/` — strony renderowane przez Jinja2.
- `app/static/styles.css` — wspólny wygląd i responsywność.
- `requirements.txt` — zależności Pythona.

## 3. Uruchomienie aplikacji

Aplikacja jest tworzona w `app/main.py`:

```python
app = Flask(__name__, static_folder="static", template_folder="templates")
```

Uruchomienie:

```powershell
python -m app.main
```

Domyślnie serwer developerski działa pod `http://localhost:5000`.

## 4. Warstwa bazy danych

SQLite przechowuje dane w lokalnym pliku `inventory.db`. SQLAlchemy tworzy silnik i sesje:

```python
engine = create_engine(
    "sqlite:///./inventory.db",
    connect_args={"check_same_thread": False},
)
```

Helper `get_session()` jest context managerem. Zapewnia zamknięcie sesji po obsłużeniu operacji:

```python
with get_session() as session:
    pallets = session.query(Pallet).all()
```

## 5. Modele i relacje

### Pallet

Reprezentuje paletę albo box. Przechowuje kod, datę dostawy, koszt zakupu, notatki i datę utworzenia.

Jedna paleta ma wiele butów:

```python
shoes = relationship(
    "Shoe",
    back_populates="pallet",
    cascade="all, delete-orphan",
)
```

Usunięcie palety usuwa przez ORM należące do niej buty.

### Shoe

Reprezentuje jedną parę butów. Najważniejsze pola to:

- `pallet_id` — identyfikator palety,
- `internal_id` — unikalne oznaczenie magazynowe,
- `name` i `description`,
- `status` — `available` lub `sold`,
- `sale_price` i `sale_date`,
- `created_at`.

But należy do jednej palety i może mieć wiele zdjęć.

### ShoePhoto

Przechowuje ścieżkę do pliku, a nie zawartość obrazu. Dzięki temu baza pozostaje mała. Pole `sort_order` kontroluje kolejność galerii.

Relacje tworzą układ:

```text
Pallet 1 ---- wiele Shoe 1 ---- wiele ShoePhoto
```

## 6. Kompatybilność schematu

Przy starcie `Base.metadata.create_all(bind=engine)` tworzy brakujące tabele. Funkcja `ensure_schema_compatibility()` sprawdza przez `PRAGMA table_info(shoes)`, czy starsza baza ma pola sprzedaży, i w razie potrzeby dodaje je przez `ALTER TABLE`.

Wycofane funkcje nie są usuwane z istniejącej bazy destrukcyjnie. Stare, nieużywane kolumny lub tabele mogą pozostać w prywatnym pliku SQLite, ale ORM ich nie mapuje. Pozwala to zachować dane i uniknąć ryzyka uszkodzenia bazy.

W większym systemie ręczne poprawki schematu warto zastąpić migracjami Alembic.

## 7. Routing i formularze

Dekoratory Flask łączą adres i metodę HTTP z funkcją:

```python
@app.get("/")
def home():
    ...

@app.post("/pallets")
def create_pallet():
    ...
```

Przyjęta konwencja:

- `GET` pobiera i prezentuje dane,
- `POST` zmienia dane,
- po poprawnym `POST` aplikacja zwraca przekierowanie, co zapobiega ponownemu wysłaniu formularza po odświeżeniu.

## 8. Główne widoki

### Strona główna

Wyświetla palety, globalną wyszukiwarkę i dashboard. Wyszukiwanie obejmuje identyfikator buta, nazwę i kod palety. Dashboard agreguje sprzedaż, koszty, stan magazynu, statystyki cen, porównanie miesięcy oraz rekordy wymagające uwagi.

Agregacje powstają w SQLAlchemy przy użyciu m.in. `func.count`, `func.sum` i `case`. Mediana cen jest obliczana w Pythonie.

### Widok palety

Pozwala:

- edytować koszt i notatki,
- dodawać i filtrować buty,
- synchronizować zdjęcia,
- przejść do szczegółów buta,
- obserwować sprzedaż i stan zwrócenia kosztu.

### Widok buta

Pozwala edytować ID, nazwę, opis, status i dane sprzedaży. Domyślna data sprzedaży pochodzi z lokalnej daty systemu:

```python
datetime.now().astimezone().date()
```

Nie wymaga to zewnętrznej bazy stref czasowych na Windows.

## 9. Zdjęcia

Pliki są przechowywane poza bazą:

```text
PALETY/<KOD_PALETY>/<ID_BUTA>/zdjecie.jpg
```

Synchronizacja przegląda katalog buta i tworzy rekordy `ShoePhoto`. Trasa `/media/<path:rel_path>` udostępnia obraz, a `safe_abs_from_rel()` sprawdza, czy wynikowa ścieżka nadal znajduje się wewnątrz katalogu `PALETY`. To zabezpiecza przed path traversal.

Galeria szczegółów używa lightboxa w vanilla JavaScript. Kliknięcie miniatury otwiera obraz nad stroną. Podgląd można zamknąć przyciskiem, kliknięciem tła lub klawiszem Escape. CSS ogranicza obraz do rozmiaru okna i blokuje przewijanie strony w tle.

## 10. Szablony i JavaScript

`base.html` zawiera wspólny dokument, nagłówek i podpięcie arkusza stylów. Pozostałe strony dziedziczą po nim:

```jinja2
{% extends "base.html" %}
{% block content %}
  ...
{% endblock %}
```

Jinja2 obsługuje pętle, warunki i bezpieczne wstawianie wartości. JavaScript odpowiada między innymi za klikalne wiersze, lazy loading miniaturek i lightbox.

## 11. Bezpieczeństwo danych

`.gitignore` wyklucza:

- `inventory.db`,
- `PALETY/`,
- `.thumb_cache/`,
- `.env`,
- środowiska wirtualne i cache Pythona.

Kod nie zawiera kluczy API, tokenów ani haseł. Aplikacja jest jednak narzędziem lokalnym: nie ma logowania, autoryzacji ani ochrony CSRF. Nie powinna być wystawiana bezpośrednio do Internetu bez dodania tych zabezpieczeń i produkcyjnego serwera WSGI.

## 12. Wzorce, których można się nauczyć

- CRUD: tworzenie, odczyt, aktualizacja i usuwanie rekordów.
- ORM: praca na obiektach Python zamiast ręcznego SQL.
- Relacje one-to-many i kaskadowe usuwanie.
- Server-side rendering i wzorzec POST/Redirect/GET.
- Agregacje danych do dashboardu.
- Oddzielenie plików multimedialnych od rekordów bazy.
- Walidacja ścieżek plików.
- Responsywny interfejs bez frameworka JavaScript.

## 13. Możliwe dalsze ulepszenia

- logowanie i role użytkowników,
- ochrona CSRF,
- testy automatyczne pytest,
- migracje Alembic,
- konfiguracja przez zmienne środowiskowe,
- upload i obróbka zdjęć z poziomu formularza,
- historia zmian statusów i cen,
- backup bazy z poziomu aplikacji.
