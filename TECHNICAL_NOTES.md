# Magazynier — notatka techniczna projektu

Ta notatka opisuje, jak technicznie jest zbudowany projekt **Magazynier**: jakie ma warstwy, jak działa backend, baza danych, szablony, zdjęcia, raporty oraz ostatnio dodane konta Vinted.

## 1. Ogólny obraz aplikacji

Projekt jest klasyczną lokalną aplikacją webową typu **server-rendered app**.

Oznacza to, że:

- użytkownik wchodzi w przeglądarce na adres aplikacji,
- backend Flask odbiera żądanie HTTP,
- backend pobiera albo zapisuje dane w bazie SQLite,
- backend renderuje gotowy HTML przez Jinja2,
- przeglądarka dostaje już gotową stronę.

Nie ma tutaj osobnego frontendu typu React/Vue. Frontend to zwykłe szablony HTML, CSS i trochę JavaScriptu w samych szablonach.

Główne technologie:

- Python,
- Flask,
- SQLAlchemy,
- SQLite,
- Jinja2,
- openpyxl,
- HTML/CSS/JavaScript.

## 2. Struktura plików

Najważniejsze pliki:

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
    vinted_accounts.html
requirements.txt
README.md
.gitignore
```

Rola plików:

- `app/main.py` — serce aplikacji: trasy HTTP, logika formularzy, raport Excel, synchronizacja zdjęć.
- `app/database.py` — konfiguracja bazy SQLite i sesji SQLAlchemy.
- `app/models.py` — definicje tabel bazy danych jako klasy Python.
- `app/templates/*.html` — szablony stron HTML.
- `app/static/styles.css` — wygląd aplikacji.
- `requirements.txt` — zależności Pythona.
- `.gitignore` — zabezpiecza lokalne dane przed wrzuceniem na GitHub.

## 3. Jak uruchamia się aplikacja

Aplikacja Flask tworzona jest w `app/main.py`:

```python
app = Flask(__name__, static_folder="static", template_folder="templates")
```

To mówi Flaskowi:

- gdzie są pliki statyczne, czyli `app/static`,
- gdzie są szablony, czyli `app/templates`.

Na końcu pliku jest klasyczny start aplikacji developerskiej:

```python
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
```

Dzięki temu można uruchomić projekt komendą:

```powershell
python -m app.main
```

Po uruchomieniu aplikacja działa lokalnie na porcie `5000`.

## 4. Baza danych

Baza danych to SQLite, czyli pojedynczy lokalny plik `inventory.db`.

Konfiguracja jest w `app/database.py`:

```python
DATABASE_URL = "sqlite:///./inventory.db"
```

SQLite jest dobre dla takiego projektu, bo:

- nie trzeba instalować osobnego serwera bazy,
- baza jest jednym plikiem,
- łatwo ją skopiować lub zbackupować,
- wystarcza do lokalnego panelu magazynowego.

SQLAlchemy tworzy silnik bazy:

```python
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
```

`check_same_thread=False` jest typowe przy SQLite + Flask, bo requesty mogą być obsługiwane w różnych wątkach.

Sesje do bazy tworzy `SessionLocal`, a wygodny helper `get_session()` otwiera i zamyka sesję:

```python
@contextmanager
def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

Dzięki temu w trasach można pisać:

```python
with get_session() as session:
    pallets = session.query(Pallet).all()
```

## 5. Modele danych

Modele są w `app/models.py`. Model to klasa Python, która odpowiada tabeli w bazie.

### 5.1. Pallet

`Pallet` reprezentuje paletę albo box.

Najważniejsze pola:

- `id` — techniczne ID rekordu,
- `code` — kod palety/boxa, np. `PALETA_A`, `BOX_AA`,
- `delivery_date` — data dostawy,
- `purchase_gross` — cena brutto zakupu,
- `notes` — notatki,
- `created_at` — data utworzenia rekordu.

Relacja:

```python
shoes = relationship("Shoe", back_populates="pallet", cascade="all, delete-orphan")
```

To znaczy: jedna paleta ma wiele butów. Jeśli usuniesz paletę, SQLAlchemy usuwa też powiązane buty z bazy.

### 5.2. Shoe

`Shoe` reprezentuje jedną parę butów / jeden przedmiot.

Najważniejsze pola:

- `id` — techniczne ID rekordu,
- `pallet_id` — do której palety należy but,
- `internal_id` — Twoje ID buta, np. `A001`, `B052`,
- `name` — tytuł/nazwa,
- `description` — opis,
- `status` — `available` albo `sold`,
- `vinted_account_id` — opcjonalne konto Vinted,
- `sale_price` — cena sprzedaży,
- `sale_date` — data sprzedaży,
- `created_at` — data utworzenia.

Ważne: `vinted_account_id` jest opcjonalne. Dzięki temu wszystkie stare buty po aktualizacji zostają bez przypisanego konta Vinted.

Relacje:

```python
pallet = relationship("Pallet", back_populates="shoes")
vinted_account = relationship("VintedAccount", back_populates="shoes")
photos = relationship("ShoePhoto", back_populates="shoe", cascade="all, delete-orphan")
```

Czyli but:

- należy do jednej palety,
- może mieć jedno konto Vinted albo żadne,
- może mieć wiele zdjęć.

### 5.3. ShoePhoto

`ShoePhoto` przechowuje ścieżkę do zdjęcia buta.

Zdjęcia nie są zapisywane w bazie jako pliki/binary. W bazie jest tylko ścieżka tekstowa.

Pola:

- `id`,
- `shoe_id`,
- `file_path`,
- `sort_order`.

To jest dobre rozwiązanie, bo baza nie puchnie od zdjęć.

### 5.4. VintedAccount

`VintedAccount` reprezentuje konto Vinted.

Pola:

- `id`,
- `name` — nazwa konta,
- `is_banned` — czy konto jest zbanowane,
- `created_at`.

Relacja:

```python
shoes = relationship("Shoe", back_populates="vinted_account")
```

Czyli jedno konto Vinted może być przypisane do wielu butów.

## 6. Automatyczne tworzenie i aktualizacja schematu

Przy starcie aplikacji wykonywane jest:

```python
Base.metadata.create_all(bind=engine)
```

To tworzy tabele, jeśli ich jeszcze nie ma.

Jest też funkcja `ensure_schema_compatibility()`, która ręcznie sprawdza kolumny w tabeli `shoes` i dodaje brakujące:

```python
columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(shoes)").fetchall()]
```

Potem np.:

```python
if "vinted_account_id" not in columns:
    conn.exec_driver_sql("ALTER TABLE shoes ADD COLUMN vinted_account_id INTEGER")
```

To jest prosta forma migracji bazy. Nie używasz tutaj Alembic, tylko ręczną kompatybilność.

Plus: łatwe i szybkie.

Minus: przy większym projekcie lepsze byłyby prawdziwe migracje.

## 7. Trasy HTTP i zasada działania

Flask działa przez dekoratory typu:

```python
@app.get("/")
def home():
    ...
```

albo:

```python
@app.post("/pallets")
def create_pallet():
    ...
```

Różnica:

- `GET` — pobieranie strony/danych,
- `POST` — wysyłanie formularza i zmiana danych.

## 8. Strona główna

Strona główna to trasa `home()`.

Robi kilka rzeczy:

- pobiera listę palet,
- obsługuje raport sprzedaży za zakres dat,
- obsługuje globalne wyszukiwanie butów po wszystkich paletach/boxach,
- renderuje `home.html`.

Globalne wyszukiwanie używa zapytania SQLAlchemy z `join(Pallet)`, żeby można było szukać też po kodzie palety:

```python
session.query(Shoe)
    .options(joinedload(Shoe.pallet))
    .join(Pallet)
    .filter(
        or_(
            Shoe.internal_id.ilike(f"%{shoe_q}%"),
            Shoe.name.ilike(f"%{shoe_q}%"),
            Pallet.code.ilike(f"%{shoe_q}%"),
        )
    )
```

`joinedload(Shoe.pallet)` powoduje, że SQLAlchemy od razu ładuje powiązaną paletę. Dzięki temu w szablonie można bezpiecznie używać `s.pallet.code`.

## 9. Palety i boxy

Dodawanie palety obsługuje trasa `create_pallet()`.

Formularz wysyła:

- `code`,
- `delivery_date`,
- `purchase_gross`,
- `notes`.

Backend robi z tego obiekt `Pallet` i zapisuje go:

```python
pallet = Pallet(
    code=code,
    delivery_date=delivery_date,
    purchase_gross=purchase_gross,
    notes=notes,
)
session.add(pallet)
session.commit()
```

Widok konkretnej palety to `pallet_detail()`.

Pokazuje:

- dane palety,
- notatki,
- formularz edycji notatek,
- zmianę ceny zakupu,
- statystyki butów,
- formularz dodania buta,
- listę butów w palecie,
- filtr statusu i wyszukiwarkę w obrębie palety.

Edycja notatek jest osobną trasą `update_pallet_notes()`.

## 10. Dodawanie buta

But jest dodawany przez `create_shoe()`.

Formularz przyjmuje:

- `internal_id`,
- `name`,
- `description`,
- `vinted_account_id`.

Backend sprawdza, czy `internal_id` nie jest już zajęte:

```python
exists = session.query(Shoe).filter(Shoe.internal_id == internal_id).first()
```

Jeśli ID jest wolne, tworzy buta:

```python
shoe = Shoe(
    pallet_id=pallet_id,
    internal_id=internal_id,
    name=name,
    description=description,
    vinted_account_id=vinted_account_id,
    status="available",
)
```

Status nowego buta zawsze startuje jako `available`.

## 11. Edycja buta

Edycja danych buta jest w `update_shoe_details()`.

Można zmienić:

- ID buta,
- tytuł/nazwę,
- opis,
- konto Vinted.

Przed zapisem backend sprawdza, czy nowe ID buta nie koliduje z innym butem:

```python
duplicate = session.query(Shoe).filter(Shoe.internal_id == internal_id, Shoe.id != shoe_id).first()
```

Jeśli jest duplikat, aplikacja nie zapisuje zmian i wraca do szczegółów buta.

## 12. Sprzedaż buta

Sprzedaż obsługuje `toggle_shoe_status()`.

Jeśli but jest dostępny:

- formularz wymaga ceny sprzedaży,
- data sprzedaży jest domyślnie dzisiejsza,
- status zmienia się na `sold`,
- zapisywane są `sale_price` i `sale_date`.

Jeśli but jest sprzedany i klikniesz przycisk cofnięcia:

- status wraca na `available`,
- cena sprzedaży jest czyszczona,
- data sprzedaży jest czyszczona.

Dzisiejsza data jest liczona przez:

```python
def local_today() -> date:
    return datetime.now().astimezone().date()
```

To korzysta z lokalnej strefy systemu Windows, więc nie wymaga dodatkowej paczki `tzdata`.

## 13. Konta Vinted

Konta Vinted mają osobną stronę `vinted_accounts.html` i trasy:

- `vinted_accounts()` — lista kont,
- `create_vinted_account()` — dodanie konta,
- `update_vinted_account()` — edycja konta.

Konto ma:

- nazwę,
- checkbox `is_banned`.

W formularzu dodawania i edycji buta jest select z listą kont Vinted. Jest też opcja `Brak przypisanego konta`.

To znaczy, że but może:

- mieć konto Vinted,
- albo nie mieć żadnego konta.

Zbanowane konta nie są blokowane technicznie. Są tylko oznaczane w UI jako zbanowane. Dzięki temu możesz nadal widzieć historię przypisań.

## 14. Zdjęcia

Zdjęcia są trzymane na dysku, a nie w bazie.

Główny katalog zdjęć:

```python
PHOTOS_ROOT = Path.cwd() / "PALETY"
```

Oczekiwany folder zdjęć buta buduje `expected_shoe_dir()`:

```python
return PHOTOS_ROOT / pallet_code / shoe_internal_id
```

Przykład:

```text
PALETY/PALETA_A/A001/zdjecie1.jpg
```

Synchronizacja zdjęć działa przez `sync_shoe_photos()`:

1. Sprawdza folder buta.
2. Pobiera pliki o obsługiwanych rozszerzeniach.
3. Sortuje je po nazwie.
4. Zapisuje ścieżki do tabeli `shoe_photos`.
5. Usuwa z bazy stare ścieżki, jeśli pliku nie ma już na dysku.

Obsługiwane rozszerzenia:

```python
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
```

Zdjęcia są podawane przez trasę:

```python
@app.get("/media/<path:rel_path>")
```

Przed wysłaniem pliku aplikacja używa `safe_abs_from_rel()`, żeby nie dało się wyjść poza katalog projektu przez dziwną ścieżkę typu `../../coś`.

## 15. Raport Excel

Raport sprzedanych butów jest generowany w `export_sold_shoes_report()`.

Używa biblioteki `openpyxl`.

Raport zawiera:

- ID rekordu,
- datę sprzedaży,
- ID buta,
- nazwę,
- cenę sprzedaży,
- stawkę ryczałtu,
- podatek.

Plik nie jest zapisywany na dysku. Jest tworzony w pamięci:

```python
output = BytesIO()
workbook.save(output)
output.seek(0)
```

Potem Flask wysyła go do pobrania przez `send_file()`.

## 16. Szablony HTML

Wszystkie strony dziedziczą po `base.html`:

```jinja2
{% extends "base.html" %}
```

`base.html` zawiera:

- podstawowy HTML,
- link do CSS,
- favicon,
- górne menu,
- blok `content`.

Inne szablony wypełniają blok:

```jinja2
{% block content %}
...
{% endblock %}
```

Najważniejsze szablony:

- `home.html` — główna strona z listą palet i globalnym wyszukiwaniem,
- `pallet_detail.html` — widok palety/boxa,
- `shoe_detail.html` — widok buta,
- `vinted_accounts.html` — zarządzanie kontami Vinted,
- `db_inspector.html` — podgląd bazy.

## 17. CSS i responsywność

Style są w `app/static/styles.css`.

Aplikacja ma ciemny wygląd, karty, tabele, badge statusów i responsywne widoki.

Przykładowo status buta używa klas:

- `badge available`,
- `badge sold`.

Lista butów na mniejszych ekranach zmienia układ tabeli na bardziej mobilny przez media query:

```css
@media (max-width: 860px) {
    ...
}
```

## 18. JavaScript

JavaScript jest minimalny i wpisany bezpośrednio w szablony.

Służy głównie do:

- klikalnych wierszy tabel,
- leniwego ładowania miniatur zdjęć w widoku palety.

Klikalne wiersze działają tak:

```javascript
document.querySelectorAll('.clickable-row').forEach((row) => {
  const href = row.dataset.href;
  row.addEventListener('click', () => {
    window.location.href = href;
  });
});
```

Lazy loading zdjęć używa `IntersectionObserver`, czyli obrazek ładuje się dopiero wtedy, gdy zbliża się do widoku użytkownika.

## 19. Bezpieczeństwo repozytorium

Repozytorium ma `.gitignore`, który ignoruje m.in.:

- `inventory.db`,
- `PALETY/`,
- `.thumb_cache/`,
- `.env`,
- środowiska wirtualne,
- cache Pythona,
- pliki IDE.

To ważne, bo:

- baza może zawierać realne dane sprzedaży,
- zdjęcia produktów mogą być prywatne,
- `.env` mógłby kiedyś zawierać sekrety.

## 20. Najważniejsze wzorce, których się tutaj uczysz

Ten projekt pokazuje kilka praktycznych wzorców:

### 20.1. CRUD

CRUD to:

- Create — tworzenie,
- Read — odczyt,
- Update — aktualizacja,
- Delete — usuwanie.

W projekcie przykłady CRUD:

- palety: dodanie, wyświetlenie, aktualizacja ceny/notatek, usunięcie,
- buty: dodanie, wyświetlenie, edycja danych, usunięcie,
- konta Vinted: dodanie, wyświetlenie, edycja.

### 20.2. ORM

ORM to mapowanie tabel na klasy.

Zamiast pisać ręcznie SQL:

```sql
SELECT * FROM shoes WHERE status = 'sold';
```

piszesz Pythonowo:

```python
session.query(Shoe).filter(Shoe.status == "sold").all()
```

### 20.3. Server-side rendering

Backend generuje HTML po stronie serwera:

```python
return render_template("home.html", pallets=pallets)
```

Szablon dostaje zmienne i robi z nich stronę.

### 20.4. Relacje bazodanowe

Masz relacje:

- Pallet 1 → wiele Shoe,
- Shoe 1 → wiele ShoePhoto,
- VintedAccount 1 → wiele Shoe.

### 20.5. Dane plikowe poza bazą

Zdjęcia są na dysku, a baza trzyma tylko ścieżki. To jest częsty i sensowny wzorzec.

## 21. Co można kiedyś ulepszyć

Potencjalne dalsze ulepszenia:

- dodać logowanie użytkownika,
- dodać prawdziwe migracje Alembic,
- dodać komunikaty błędów zamiast cichych redirectów,
- dodać upload zdjęć przez aplikację,
- dodać usuwanie kont Vinted,
- dodać filtrowanie po koncie Vinted,
- dodać historię zmian statusów,
- dodać eksport większej liczby raportów,
- wynieść konfigurację do `.env`, jeśli aplikacja będzie wdrażana produkcyjnie.

## 22. Mentalny model działania

Najprościej zapamiętać projekt tak:

```text
Przeglądarka
  ↓ request GET/POST
Flask route w app/main.py
  ↓ sesja SQLAlchemy
SQLite inventory.db
  ↓ dane
Jinja2 template
  ↓ gotowy HTML
Przeglądarka
```

Zdjęcia idą obok bazy:

```text
PALETY/.../zdjecie.jpg
  ↓ synchronizacja
shoe_photos.file_path w bazie
  ↓ /media/<ścieżka>
obrazek w HTML
```

Konta Vinted są dodatkową tabelą połączoną z butami:

```text
vinted_accounts.id
  ↓
shoes.vinted_account_id
```

To jest cały rdzeń techniczny aplikacji.
