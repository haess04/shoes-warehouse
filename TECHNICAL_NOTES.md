# Magazynier — notatka techniczna

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
