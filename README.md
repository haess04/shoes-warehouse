# Magazynier

Lokalna aplikacja webowa do zarządzania magazynem butów przechowywanych w paletach lub boxach. Projekt pozwala ewidencjonować palety, dodawać buty, oznaczać sprzedaż, synchronizować zdjęcia z katalogów na dysku i analizować wyniki na dashboardzie.
<img width="1107" height="815" alt="image" src="https://github.com/user-attachments/assets/51007f2b-141d-446b-8218-1a213f3734f7" />
<img width="1112" height="448" alt="image" src="https://github.com/user-attachments/assets/34d0f825-ffb5-4ea8-8d51-6795bef804fd" />

## Funkcje

- dodawanie i usuwanie palet,
- dodawanie i usuwanie butów w palecie,
- filtrowanie oraz wyszukiwanie butów po identyfikatorze lub nazwie,
- oznaczanie buta jako dostępny/sprzedany,
- zapisywanie ceny i daty sprzedaży,
- synchronizacja zdjęć z lokalnej struktury katalogów,
- galeria zdjęć produktu z powiększaniem po kliknięciu,
- dashboard sprzedaży, kosztów i stanu magazynu,
- prosty inspektor bazy danych.

<img width="991" height="841" alt="image" src="https://github.com/user-attachments/assets/7c786341-a9c5-4afe-8c4d-639ee8064130" />
<img width="973" height="782" alt="image" src="https://github.com/user-attachments/assets/7e9aba34-b906-43c7-8ad0-6454f09cd6f7" />
<img width="843" height="845" alt="image" src="https://github.com/user-attachments/assets/2a475baf-a3ec-400d-b281-a9871641a44f" />


## Technologie

- Python,
- Flask,
- SQLAlchemy,
- SQLite,
- Jinja2,
- HTML/CSS/JavaScript.

## Interfejs — Material 3

Pierwsza partia wizualna wprowadza ciemny grafitowo-zielony motyw inspirowany
Material Design 3: tonalne powierzchnie, wspólne kolory semantyczne, większe pola
dotykowe, widoczny fokus oraz lokalne ikony SVG. Nie wymaga zewnętrznych fontów,
CDN ani frameworka JavaScript. To własny lekki interfejs, nie oficjalna biblioteka Google.

Na stronie głównej formularz nowej palety jest zwijany; po błędzie otwiera się
automatycznie. Lista palet ma formę tabeli na komputerze i kart na telefonie.
Dashboard zachowuje dotychczasowe statystyki.

Druga partia wizualna porządkuje paletę i kartę buta:

- edycja notatek, kosztu oraz dodawanie produktu są zwijane; błędny formularz
  otwiera się automatycznie, bez utraty danych;
- lista produktów pokazuje miniaturę, ID, nazwę i status; na telefonie przechodzi
  w kompaktowe wiersze kart, bez technicznego ID rekordu;
- karta buta ma galerię i osobny panel sprzedaży; na telefonie sprzedaż jest
  dostępna przed galerią, a usuwanie pozostaje w sekcji „Więcej działań”;
- przywrócenie dostępności wymaga potwierdzenia utraty danych sprzedaży;
- wspólny lokalny skrypt obsługuje zwijanie formularzy, nawigację po wierszach
  i podgląd zdjęć z przywracaniem fokusu po zamknięciu;
- formularze nadal działają jako natywne formularze HTML. Logika i schemat bazy
  nie zmieniają się w partiach wizualnych.

### Opcjonalne testy przeglądarkowe

Podstawowy zestaw testów pozostaje dostępny bez dodatkowych zależności:

```powershell
python -m unittest discover -s tests -v
```

Dodatkowo dostępny jest osobny zestaw Playwright, uruchamiający prawdziwą
przeglądarkę Edge w trybie bez okna. Korzysta z tymczasowej bazy i danych
demonstracyjnych oraz serwera wyłącznie na lokalnym, losowym porcie:

```powershell
python -m pip install -r requirements-ui.txt
python tests/browser_smoke.py -v
```

Wymagany jest zainstalowany Microsoft Edge. Testy sprawdzają szerokości 320, 390,
768 i 1440 px, brak poziomego przepełnienia stron, otwieranie formularza, fokus,
zachowanie danych po błędzie, obsługę klawiatury i brak zewnętrznych zasobów.
Zrzuty ekranu z danych demonstracyjnych trafiają do ignorowanego `.ui-artifacts/`.
Test kontrastu w podstawowym zestawie sprawdza wybrane pary tokenów tekst/tło;
nie zastępuje pełnego audytu dostępności.

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

### Konfiguracja i testy — partia 1

Domyślna baza i zdjęcia są odnajdywane względem katalogu projektu, nie bieżącego
katalogu terminala. Istniejące dane nie są przenoszone. Dotychczasowe uruchomienie
`python -m app.main` oraz `python app/main.py` pozostają dostępne.

Aplikację można również utworzyć przez fabrykę `app.create_app()`; alternatywny start:

```powershell
python -m flask --app app:create_app run --host 0.0.0.0
```

Samo importowanie modułów nie otwiera bazy, nie tworzy katalogów i nie aktualizuje
schematu. Inicjalizacja następuje dopiero podczas wywołania fabryki. Przy osadzaniu
aplikacji można przekazać `DATA_ROOT` — katalog zawierający `inventory.db` i `PALETY`.
Ścieżka względna jest rozwiązywana względem projektu. Nie wskazuj przypadkowego
katalogu: nowa lokalizacja oznacza nowy magazyn, a nie przeniesienie starego.

Testy korzystają wyłącznie z tymczasowych baz i zdjęć; tryb `TESTING` wymaga
oddzielnego `DATA_ROOT`. Nie wymagają instalowania dodatkowych zależności:

```powershell
python -m unittest discover -s tests -v
```

Ta partia nie wprowadza jeszcze logowania, automatycznych kopii ani produkcyjnego
serwera. Aplikacja nadal jest przeznaczona wyłącznie do zaufanej sieci lokalnej.

### Walidacja i media — partia 2

- Formularze sprawdzają wymagane pola, duplikaty, długości tekstów i poprawność dat.
- Ceny przyjmują przecinek lub kropkę, maksymalnie dwa miejsca po przecinku,
  zakres od 0 do 9 999 999 999,99 zł. Ujemne kwoty, NaN, nieskończoność i zapis
  wykładniczy są odrzucane. Schemat przechowywania cen nie zmienia się w tej partii.
- Po błędzie strona zwraca HTTP 422, pokazuje podsumowanie i zachowuje dane formularza.
  Przy włączonym JavaScript błędy pojawiają się też przy odpowiednich polach.
  Poprawny zapis kończy się przekierowaniem z jednorazowym potwierdzeniem.
- Kody palet i ID muszą być bezpiecznymi nazwami katalogów Windows; istniejące
  rekordy nie są automatycznie przemianowywane.
- Adresy mediów udostępniają tylko istniejące obrazy z `PALETY/`. Starszy układ
  `<KOD_PALETY>/<ID_BUTA>/zdjecie.jpg` działa tylko dla poprawnie przypisanych
  rekordów zdjęć w bazie. Brak możliwości pobrania bazy, konfiguracji czy kodu
  przez trasę mediów. Nowe zdjęcia umieszczaj w standardowym katalogu `PALETY/`.
- Synchronizacja informuje o liczbie dodanych i usuniętych powiązań oraz brakujących
  folderach. Błąd w trakcie synchronizacji wycofuje transakcję, bez usuwania plików.

Do podpisywania sesji z potwierdzeniami aplikacja tworzy lokalny plik `.session-key`
w katalogu danych. Jest ignorowany przez Git; nie publikuj go ani nie edytuj ręcznie.
Klucz pozostaje taki sam po restarcie. Samych danych błędnego formularza nie zapisuje
się w ciasteczkach. Nie jest to jeszcze system logowania ani ochrona CSRF — te
zabezpieczenia stanowią następną partię.

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
