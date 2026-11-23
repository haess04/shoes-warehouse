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

Pierwsza partia wizualna wprowadza ciemny motyw inspirowany
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

Trzecia partia zamyka podstawowy redesign:

- podgląd zdjęć działa jako natywny dialog: licznik, poprzednie/następne zdjęcie,
  strzałki klawiatury, poziome przesunięcie palcem, Escape i powrót fokusu;
- błąd wczytania obrazu pokazuje komunikat i możliwość ponowienia; dla jednego
  zdjęcia przyciski przełączania są wyłączone;
- usuwanie i cofanie sprzedaży mają dialog z domyślnym focusem na „Anuluj”;
  anulowanie niczego nie wysyła, a akceptacja wysyła formularz tylko raz;
- bez JavaScriptu przyciski operacji wymagających potwierdzenia są ukryte,
  pozostałe formularze działają, a zdjęcia otwierają się przez zwykłe linki;
- inspektor pokazuje podsumowania, odnośniki do rekordów, przewijane klawiaturą
  tabele i filtry lokalne; filtry nie zmieniają rekordów ani statystyk;
- strony błędów zawierają instrukcję powrotu i nie zachęcają do ponawiania zapisu
  bez sprawdzenia aktualnego stanu.

Dialog potwierdzenia nie zastępuje autoryzacji ani CSRF. Logowanie i CSRF są już
wdrożone, a backup pozostaje kolejną partią. Interfejs zakłada współczesną przeglądarkę
obsługującą natywne dialogi HTML (aktualny Chrome, Edge, Firefox lub Safari).

Po testach na rzeczywistych ekranach dopracowano czytelność: tło jest ciemniejsze,
powierzchnie mają chłodniejsze odcienie grafitu, jaśniejsze obramowania i oddzielone
poziomy kart. Turkusowo-zielony pozostaje akcentem działań i wyników.
Układ na dużych monitorach ma do 1760 px, a strona główna od 1280 px pokazuje
przyklejone podsumowanie magazynu i miesiąca obok listy palet. Na mniejszych ekranach
te dane pozostają w pełnych statystykach, bez dodatkowego powtarzania panelu.

Poprawiono również dopasowanie dużych zdjęć: podgląd używa tego samego pliku co
miniatura i oblicza rozmiar z dostępnej przestrzeni oraz naturalnych wymiarów obrazu.
Cały kadr pozostaje widoczny, proporcje są zachowane, a małe pliki nie są rozciągane
ponad oryginalny rozmiar. Dopasowanie aktualizuje się po zmianie rozmiaru okna.
Testy obejmują duże obrazy pionowe i poziome oraz mały obraz, nie tylko miniatury.

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

3. Przy pierwszym uruchomieniu utwórz konto właściciela lokalnie w terminalu:

```powershell
python -m flask --app app:create_app init-owner
```

Podaj hasło dwukrotnie (minimum 12 znaków). Znaki nie będą wyświetlane podczas
wpisywania. Nie przekazuj hasła jako argumentu polecenia ani nie zapisuj go w repozytorium.
Polecenie nie nadpisuje istniejącego konta i nie usuwa danych magazynu.

4. Uruchom aplikację:

```powershell
python -m app.main
```

5. Otwórz w przeglądarce i zaloguj się ustawionym hasłem:

```text
http://localhost:5000
```

### Logowanie i ochrona — partia 3

- Nie ma domyślnego hasła ani rejestracji w przeglądarce. Bez utworzonego konta
  magazyn pozostaje zamknięty, a ekran logowania wyświetla instrukcję konfiguracji.
- Konto ma jedno hasło właściciela, zapisane jako skrót scrypt z losową solą.
- Zwykła sesja trwa maksymalnie 12 godzin. „Zapamiętaj to urządzenie” tworzy trwałe
  ciasteczko na maksymalnie 30 dni. W obu przypadkach termin sprawdza też serwer.
  Przywracanie sesji przez samą przeglądarkę zależy od jej ustawień.
- Wylogowanie unieważnia aktualną sesję po stronie serwera. Zmiana hasła usuwa
  wszystkie sesje i zapamiętane urządzenia.
- Limit logowania: 5 prób z jednego adresu w oknie 5 minut i 30 prób łącznie
  w tym samym oknie. Limity są trwałe, wspólne dla procesów i nie resetują się
  przez ponowne uruchomienie. Aplikacja nie ufa nagłówkowi X-Forwarded-For.
- Flask-WTF chroni logowanie, wylogowanie i wszystkie formularze zapisu przez CSRF.
  Token jest związany z sesją; wygasły formularz trzeba odświeżyć przed zapisem.
- Ochrona obejmuje strony, zdjęcia i inspektor. Publiczne są jedynie logowanie,
  pliki interfejsu i `/health` ze statusem procesu. Prywatne odpowiedzi mają no-store.
- Dane dostępu są oddzielone od magazynu: `.auth.sqlite3` przechowuje skrót hasła,
  skróty losowych tokenów sesji i liczniki prób. `.session-key` podpisuje ciasteczka.
  Oba pliki są prywatne i ignorowane przez Git, również pliki dziennika SQLite.
- Normalne uruchomienie nie włącza debuggera. Waitress i automatyczny backup
  pozostają osobnymi etapami.

Reset zapomnianego hasła (wyłącznie lokalnie na komputerze z magazynem):

```powershell
python -m flask --app app:create_app reset-owner-password
```

Reset zachowuje produkty, sprzedaż i zdjęcia, ale wylogowuje wszystkie urządzenia
i zeruje limit prób. Nie usuwaj bazy konta jako sposobu resetowania hasła.
Na telefonie w tej samej zaufanej sieci użyj adresu komputera i portu 5000,
a następnie tego samego hasła. Samo logowanie nie szyfruje HTTP — nie otwieraj
portu routera i nie używaj aplikacji w niezaufanej sieci bez szyfrowanego połączenia.

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

Partia 1 przygotowała fundament. Logowanie i CSRF opisano w partii 3 powyżej;
automatyczny backup i produkcyjny serwer pozostają do osobnego wdrożenia.

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
się w ciasteczkach. Obecnie klucz służy również do sesji logowania i tokenów CSRF.

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
- `.auth.sqlite3` z danymi dostępu i `.session-key` z kluczem sesji są ignorowane,
- lokalne środowiska wirtualne są ignorowane,
- pliki IDE i cache Pythona są ignorowane.

W obecnym kodzie nie ma kluczy API, tokenów ani haseł. Konfiguracja bazy wskazuje na lokalny plik SQLite i nie zawiera sekretów.

## Uwaga produkcyjna

Aplikacja jest lokalnym narzędziem magazynowym z logowaniem i CSRF, nie gotowym
publicznym serwisem. HTTP w LAN nie szyfruje hasła ani ciasteczek. Nie wystawiaj
portu 5000 do Internetu, nie uruchamiaj debuggera i ogranicz Zaporę Windows do
zaufanej sieci. Dostęp zdalny, HTTPS, produkcyjny serwer WSGI i automatyczny backup
wymagają osobnej konfiguracji. Przy HTTPS należy włączyć SESSION_COOKIE_SECURE.
