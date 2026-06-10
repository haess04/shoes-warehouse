# Magazynier

Lokalna aplikacja webowa do zarządzania magazynem butów przechowywanych w paletach lub boxach. Projekt pozwala ewidencjonować palety, dodawać buty, oznaczać sprzedaż, synchronizować zdjęcia z katalogów na dysku oraz eksportować raport sprzedanych butów do pliku Excel.

## Funkcje

- dodawanie i usuwanie palet,
- dodawanie i usuwanie butów w palecie,
- filtrowanie oraz wyszukiwanie butów po identyfikatorze lub nazwie,
- oznaczanie buta jako dostępny/sprzedany,
- zapisywanie ceny i daty sprzedaży,
- synchronizacja zdjęć z lokalnej struktury katalogów,
- podgląd zdjęć produktu,
- eksport raportu sprzedanych butów do pliku `.xlsx`,
- prosty inspektor bazy danych.

## Technologie

- Python,
- Flask,
- SQLAlchemy,
- SQLite,
- Jinja2,
- openpyxl,
- HTML/CSS/JavaScript.

## Struktura projektu

```text
app/
  main.py              # główna aplikacja Flask i trasy HTTP
  database.py          # konfiguracja SQLite / SQLAlchemy
  models.py            # modele: Pallet, Shoe, ShoePhoto
  static/              # CSS i ikona
  templates/           # szablony Jinja2
requirements.txt       # zależności Pythona
```

Lokalnie aplikacja korzysta też z plików, które nie powinny trafiać do repozytorium:

```text
inventory.db           # lokalna baza SQLite
PALETY/                # prywatne zdjęcia produktów
.thumb_cache/          # lokalny cache miniaturek
```

Te ścieżki są ignorowane przez `.gitignore`.

## Uruchomienie lokalne

1. Utwórz i aktywuj środowisko wirtualne:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Zainstaluj zależności:

```powershell
pip install -r requirements.txt
```

3. Uruchom aplikację:

```powershell
python -m app.main
```

4. Otwórz w przeglądarce:

```text
http://localhost:5000
```

## Zdjęcia produktów

Aplikacja nie wysyła zdjęć przez formularz. Zdjęcia należy umieszczać ręcznie w lokalnym katalogu `PALETY` według schematu:

```text
PALETY/<KOD_PALETY>/<ID_BUTA>/plik.jpg
```

Przykład:

```text
PALETY/PALETA_A/A001/zdjecie1.jpg
```

Następnie w aplikacji można użyć przycisku synchronizacji zdjęć dla jednego buta albo całej palety.

## Dane lokalne i bezpieczeństwo przed publikacją

Repozytorium zostało przygotowane tak, aby nie wysyłać na GitHub prywatnych danych operacyjnych:

- baza `inventory.db` jest ignorowana,
- katalog `PALETY/` ze zdjęciami jest ignorowany,
- katalog `.thumb_cache/` jest ignorowany,
- pliki `.env` są ignorowane,
- lokalne środowiska wirtualne są ignorowane,
- pliki IDE i cache Pythona są ignorowane.

W obecnym kodzie nie ma kluczy API, tokenów ani haseł. Konfiguracja bazy wskazuje na lokalny plik SQLite i nie zawiera sekretów.

## Uwaga produkcyjna

Aplikacja jest przygotowana jako lokalne narzędzie magazynowe. Przed wystawieniem jej publicznie warto dodać co najmniej logowanie, autoryzację, konfigurację przez zmienne środowiskowe oraz produkcyjny serwer WSGI.
