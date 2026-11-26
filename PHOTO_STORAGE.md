# Bezpieczny lokalny audyt zdjęć, próbki i archiwum oryginałów

Narzędzie [audytu](tools/photo_storage.py) działa niezależnie od aplikacji.
Nie importuje jej fabryki, nie tworzy bazy, schematu, sesji ani kont użytkowników.
Nie zmienia oryginałów, rekordów, miniatur ani sposobu serwowania zdjęć.
Nie ma funkcji migracji, podmiany, kasowania ani przesyłania danych.

## Uruchamianie

Wymagany Python 3.12+ oraz Pillow z zależności projektu. W terminalu w katalogu
projektu uruchom poniższe polecenia (każda nowa operacja wymaga nowej nazwy wyniku):

1. Audyt bez generowania obrazów: [`python tools/photo_storage.py audit --run audit-local`](tools/photo_storage.py:419)
2. Audyt i najwyżej 36 próbek: [`python tools/photo_storage.py sample --run trial-local --count 36`](tools/photo_storage.py:419)
3. Ponowny odczyt podsumowania: [`python tools/photo_storage.py report --run trial-local`](tools/photo_storage.py:419)

Punkt wejścia: [narzędzie CLI](tools/photo_storage.py).
Parametr [`--data-root`](tools/photo_storage.py:422) musi wskazywać **rzeczywisty katalog danych skonfigurowany
w aplikacji**, nie sam katalog zdjęć. Domyślnie jest nim katalog projektu,
zgodnie z [konfiguracją aplikacji](app/config.py:11).
Narzędzie nie zakłada, że zmienna środowiskowa automatycznie konfiguruje aplikację.
Nie obsługuje niezależnego zewnętrznego katalogu zdjęć: obecne
[reguły bezpieczeństwa mediów](app/media.py:14) ograniczają media do głównego katalogu danych.

## Zakres i ograniczenia odczytu

- Rekurencyjny przegląd [standardowego katalogu zdjęć](PALETY/) obejmuje rozszerzenia
  JPG/JPEG, PNG i WebP. Pliki poza standardową głębokością synchronizacji są oznaczane,
  a nie uznawane automatycznie za dostępne w aplikacji.
- Stare lokalizacje to bezpośrednie obrazy w katalogach paleta/but znanych z bazy
  oraz zarejestrowane zdjęcia pasujące do powiązanej palety i buta. Uwzględniane są
  również obrazy jeszcze niezsynchronizowane, także gdy istnieje standardowy katalog.
  Nie jest to obietnica ich dostępności przez aplikację przed rejestracją. Brak
  standardowego katalogu nie pomija odczytu starych lokalizacji.
- SQLite jest otwierane bezpośrednio w trybie tylko do odczytu i bez zapisu plików
  pomocniczych. **Na czas audytu baza powinna być nieaktywna.** Istniejący WAL lub
  dziennik rollback oznacza
  odmowę odczytu bazy i jawny błąd w raporcie; narzędzie nie wykonuje checkpointu.
  Nie wolno usuwać dzienników ręcznie. Zmiana rozmiaru/czasu modyfikacji bazy podczas
  odczytu jest zgłaszana jako błąd. Nie jest to narzędzie do spójnych kopii aktywnej bazy.
- Braki plików, nieprawidłowe ścieżki, błędy nagłówków, uprawnień i bazy są raportowane.
  Częściowy audyt nie oznacza braku danych. Dowiązania i punkty połączeń są odrzucane.
- Liczby, bajty, typy i wymiary pochodzą z plików. Wymiary audytu to wymiary nagłówka
  przed orientacją EXIF. Audyt nie dekoduje pikseli całej kolekcji.
  Bajty to suma logicznych rozmiarów plików, nie pomiar fizycznej alokacji bloków
  systemu plików ani deduplikacji dysku.
- Tani przegląd przenośności zgłasza kolizje wielkości liter, niezgodność wielkości
  liter zarejestrowanej ścieżki oraz separatory Windows. To nie jest pełny audyt migracji
  na Linux ani obietnica zgodności nazw z każdym docelowym systemem plików.

## Próba na kopiach

Dobór jest deterministyczny, z pokryciem formatów, zakresów rozdzielczości i rozmiarów.
Po zapewnieniu pokrycia rzadkich grup pozostałe miejsca są przydzielane proporcjonalnie.
To **nie jest losowa próba statystyczna**; jej wyniku nie należy bezpośrednio mnożyć
przez rozmiar całej kolekcji. Można porównywać także wyniki dla samego dominującego formatu.

Każdy wybrany obraz otrzymuje sześć wariantów: JPEG z jakością 85 i WebP z jakością 82,
każdy w rozdzielczości natywnej oraz z dłuższym bokiem maksymalnie 1600 i 2000 pikseli.
Liczby jakości różnych kodeków nie są równoważne. Mniejsze obrazy nie są powiększane;
proporcje są zachowane, orientacja EXIF zastosowana, przezroczystość łączona z białym tłem.
Kopie powstają na nowym płótnie bez EXIF/GPS, XMP i profili ICC. Usunięcie profilu może
wpływać na kolory — oceń je wizualnie. Animacje i obrazy powyżej 40 mln pikseli są pomijane.

Limity: domyślnie 36, maksymalnie 48 zdjęć; maksymalnie 24 MiB na zakodowaną kopię,
512 MiB łącznie na obrazy, minimum 1 GiB rezerwy wolnego miejsca. Przed utworzeniem
katalogu wymagane jest miejsce na pełny limit i rezerwę; rezerwa jest sprawdzana także
przed każdym zapisem. Kodowanie jest sekwencyjne i ograniczone liczbą/pikselami, bez
gwarancji czasu wykonania na wolnym komputerze. Raporty tekstowe zajmują dodatkowe miejsce.
Przekroczenie limitu jest jawnie raportowane; częściowe próbki są zachowane.
Zapis jest atomowy, bez nadpisywania istniejących plików. System plików musi obsługiwać
twarde dowiązania w prywatnym katalogu wyników (np. NTFS).

## Prywatne wyniki i ocena jakości

Wyniki trafiają wyłącznie do [ignorowanego katalogu prywatnego](.photo-audit/), poza
katalogami synchronizacji zdjęć. Każdy przebieg zawiera raport JSON i lokalną galerię
HTML; próba dodatkowo zawiera ponumerowane kopie bez identyfikatorów magazynowych w nazwach.
Galeria pokazuje kopie oraz odsyłacze do lokalnych oryginałów. **Oryginały zachowują swoje
metadane** — nie należy ich udostępniać przez galerię. Galeria nie korzysta z serwera ani sieci.

Raporty i galeria zawierają prywatne ścieżki. Nie dodawać ich do Git, nie przesyłać
ich do usług zewnętrznych ani nie publikować. Ignorowanie Git nie wyłącza ewentualnej
zewnętrznej synchronizacji całego Pulpitu; tę konfigurację kontroluje użytkownik.

Porównuj etykiety, drobne napisy, fakturę materiału, szwy, uszkodzenia i kolory przy
powiększeniu 100%. Oszczędności są pomiarami bajtów **próbek**, nie gwarancją jakości
ani prognozą całej kolekcji. Narzędzie nie oblicza i nie deklaruje SSIM.

**Kopie tymczasowo zwiększają zajęte miejsce.** Faktyczne zwolnienie przestrzeni wymaga
późniejszej, osobno zatwierdzonej strategii zastępowania lub archiwizacji, z kopią
zapasową i sprawdzeniem powiązań w bazie. W tym etapie nie ma takiej operacji.

## Testy

[Testy narzędzia](tests/test_photo_storage.py) używają wyłącznie syntetycznych obrazów
i tymczasowych baz SQLite. Obejmują brak efektów ubocznych, stare lokalizacje, WAL,
ścieżki, limity, orientację, GPS, brak powiększania, proporcje, przezroczystość,
deterministyczny dobór, atomowość oraz niezmienność plików źródłowych.
Test rzeczywistego dowiązania może być pominięty, jeśli Windows nie udziela uprawnień;
testy blokowania komponentów dowiązań i punktów połączeń działają niezależnie od tego.

## Etap archiwizacji — bez konwersji i usuwania

Osobne [narzędzie archiwizacji](tools/photo_archive.py) kopiuje oryginały do nowego,
unikalnego katalogu na wskazanym dysku. Nie importuje aplikacji, nie synchronizuje
zdjęć i nie zmienia rekordów magazynu. Nie zawiera operacji podmiany ani kasowania.

- Start wymaga jawnego katalogu danych i istniejącego katalogu docelowego poza nim:
  [polecenie start](tools/photo_archive.py:347) z argumentami katalogu danych i archiwum.
  Opcjonalny limit pozwala najpierw skopiować małą partię.
- [Polecenie wznowienia](tools/photo_archive.py:350) wymaga dokładnego katalogu
  istniejącego przebiegu. **Po przerwaniu nie uruchamiać ponownie startu.**
  Przebieg z niedokończoną inicjalizacją jest odrzucany i wymaga osobnej analizy;
  narzędzie nie usuwa go automatycznie.
- Prywatny manifest SQLite zawiera ścieżki, rozmiary, identyfikatory plików,
  SHA-256, powiązania zdjęć i stan każdego pliku. Zapis stanu jest zatwierdzany
  po każdym zweryfikowanym zdjęciu. Manifest i kopie muszą pozostać poza Git.
- Zachowane są ścieżki względne: obrazy wszystkich głębokości standardowego
  katalogu, wszystkie zarejestrowane pliki oraz bezpośrednie obrazy znanych
  starych lokalizacji. Pliki niezarejestrowane nie są odrzucane. Nie jest to kopia
  dowolnych innych plików całego dysku ani nieznanych katalogów poza tym zakresem.
- Bazy magazynu i opcjonalna baza logowania są kopiowane przez
  [SQLite backup API](tools/photo_archive.py:164), ze sprawdzeniem integralności.
  Opcjonalny klucz sesji jest również kopiowany. Archiwum zawiera zatem **sekrety**:
  nie publikować, chronić dostęp i dysk. Kopie poszczególnych baz nie stanowią
  wspólnej transakcji pomiędzy bazami.
- Przed kopiowaniem wymagane jest miejsce na wszystkie zaplanowane oryginały
  oraz 2 GiB rezerwy. Wolne miejsce jest sprawdzane także przed każdym zapisem.
  Plik tymczasowy jest utrwalany, haszowany i publikowany atomowo bez nadpisywania.
  Dysk docelowy musi obsługiwać twarde dowiązania, np. NTFS.
- Rozmiar/czas/identyfikator źródła oraz jego hash są sprawdzane ponownie.
  Istniejący cel może zostać przyjęty po przerwaniu tylko przy zgodności hashy.
  Wznowienie ponownie czyta i haszuje także już zweryfikowane pary źródło/kopia.
  Zmienione źródło, konflikt lub uszkodzona kopia zatrzymują pracę bez nadpisania.
  Dodatkowy obraz wykryty podczas końcowego przeglądu blokuje status kompletności.
- Blokada systemowa wyklucza dwa procesy tego samego przebiegu i znika po awarii
  procesu. Nie obejmuje aplikacji ani innego, niezależnego przebiegu.
- Na Windows konserwatywna kontrola procesów odmawia pracy przy innym procesie
  Python lub znanym serwerze aplikacji; kontrola działa przed startem i każdym
  zdjęciem. Nie zabija procesów i w razie błędu kontroli odmawia pracy.
  **Nie jest to wyłączna blokada aplikacji**: nie zapobiega jej uruchomieniu między
  kontrolami ani nie wykrywa dowolnego przemianowanego programu. Podczas kopiowania
  nie uruchamiać aplikacji. Ten mechanizm nie uprawnia do konwersji lub kasowania.

Status kompletnego archiwum oznacza zgodność sprawdzonych kopii z oryginałami,
nie zwolnienie miejsca na dysku źródłowym. Kolejny etap musi osobno zapewnić
rzeczywiste wykluczenie zapisów aplikacji, świeżą kopię bazy, ponowną walidację
źródeł, pełne dekodowanie nowych obrazów, bezkolizyjne nazwy, transakcyjną zmianę
powiązań i odzyskiwanie po awarii. Dopiero wtedy można usunąć dokładnie te
oryginały, których archiwum i podmiana zostały zweryfikowane. Bez tych zabezpieczeń
pozostajemy na etapie archiwum; nie powstają dodatkowe warianty w katalogu synchronizacji.

[Testy archiwizacji](tests/test_photo_archive.py) pracują wyłącznie na tymczasowych,
syntetycznych danych. Obejmują wznowienie, przerwanie przed zapisem manifestu,
uszkodzone kopie, zmianę źródła także z zachowaniem jego rozmiaru i czasu,
brak miejsca, błąd publikacji, WAL, brak nadpisywania, wspólne powiązania,
nietypowe głębokości, blokadę równoległego przebiegu i odmowę przy aktywnym procesie.
Nie testują konwersji ani wycofywania podmiany, bo narzędzie ich nie implementuje.

## Druga partia: ręczna migracja offline z odzyskiwaniem

[Narzędzie migracji](tools/photo_migrate.py) jest osobne od pierwszej partii.
Nie importuje aplikacji, nie uruchamia fabryki ani ORM. Bez `--execute` wszystkie
polecenia są tylko odczytem: plan wypisuje zakres, pozostałe polecenia pokazują
metadane dziennika, **nie wykonują** przygotowania, migracji ani pełnej weryfikacji.
Pełna weryfikacja wymaga `verify --execute` i wyłączności tak jak migracja.

### Blokada i warunki wejściowe

[Każda fabryka aplikacji](app/__init__.py) zakłada przed inicjalizacją sesji,
bazy i logowania [wyłączną blokadę systemową](tools/offline_lock.py) na cały czas
życia aplikacji. Obejmuje start modułowy, fabrykę Flask i CLI Flask, także komendy
administracyjne logowania. Jeden proces może współdzielić uchwyt pomiędzy swoimi
fabrykami; inne procesy (także drugi serwer) nie mogą wejść jednocześnie.
Nie uruchamiać kilku workerów ani reloadera. Wszystkie żądania, również GET oraz
logowanie, mają wcześniejszą kontrolę konserwacji i w jej trakcie zwracają 503.

Przed operacją zamknąć aplikację normalnie, także stare procesy sprzed wdrożenia
tej blokady. Migracja konserwatywnie odmawia pracy przy innym procesie Python,
Flask, Waitress, Uvicorn, Gunicorn lub znanym programie magazynu na Windows.
Sprawdza procesy przed i po zajęciu blokady, a następnie podczas pętli roboczych.
Błąd inspekcji oznacza odmowę. Narzędzie nigdy nie zabija procesów. Nie jest to
zabezpieczenie przed niezależnym programem obchodzącym protokół, przemianowaną
starą aplikacją ani ręcznymi zapisami na dysku: tych zapisów nie wykonywać.

Przygotowanie tworzy trwałego właściciela konserwacji w katalogu danych.
Awaria zwalnia uchwyt systemowy, lecz **nie** właściciela: aplikacja pozostaje
zablokowana. Tylko wznowienie lub rollback dokładnie tego dziennika może zakończyć
konserwację. Nie usuwać ręcznie znacznika, nie edytować dziennika ani hashy.
Nie odłączać dysku archiwum; nie używać narzędzia na udziale sieciowym.

### Powtarzalna procedura (Windows, cmd)

W poniższych komendach użyć rzeczywistego katalogu danych i dokładnego, kompletnego
przebiegu pierwszej partii. Przykładowe nazwy są umowne, nie wskazują prywatnych danych.

```bat
python -m tools.photo_migrate plan --data-root "C:\DANE" --archive "I:\ARCHIWUM\archive-RUN"
python -m tools.photo_migrate plan --data-root "C:\DANE" --archive "I:\ARCHIWUM\archive-RUN" --execute
```

Druga komenda tworzy **nowy** podkatalog migracji wewnątrz archiwum. Zanotować
zwróconą ścieżkę i używać jej w każdym następnym poleceniu:

```bat
python -u -m tools.photo_migrate prepare --run "I:\ARCHIWUM\archive-RUN\migration-RUN" --execute
python -u -m tools.photo_migrate apply --run "I:\ARCHIWUM\archive-RUN\migration-RUN" --execute
python -u -m tools.photo_migrate verify --run "I:\ARCHIWUM\archive-RUN\migration-RUN" --execute
```

Długie zadanie uruchamiać w trwałym lokalnym procesie z przekierowaniem wyjścia i
błędów do prywatnych logów; nie zamykać komputera. Postęp jest wypisywany co 25
plików. Przerwanie nie wymaga nowej partii: powtórzyć `prepare` dla stanu
`preparing`, a `apply` dla `publishing`, `switched`, `removing` lub `verified`.
Stan `planning` oznacza nieukończony plan: utworzyć nowy plan; konserwacja nie
została jeszcze przejęta. Po rozpoczęciu rollbacku kontynuować wyłącznie rollback.

```bat
python -u -m tools.photo_migrate rollback --run "I:\ARCHIWUM\archive-RUN\migration-RUN" --execute
```

Rollback odtwarza brakujące oryginały z trwałego archiwum bez nadpisania innych
plików, przywraca dokładne pierwotne wartości powiązań, sprawdza całą bazę i usuwa
wyłącznie własne, zgodne hashami wyniki. Działa również po usunięciu oryginałów i
po zakończeniu partii, o ile od tego czasu nie zmieniono danych. Nie przywraca
całej starej bazy przez nadpisanie: jakakolwiek obca zmiana bazy zatrzymuje operację.
Zmiana źródła, archiwum, snapshotu, dziennika lokalizacji, konflikt pliku lub
odłączenie dysku oznacza bezpieczny błąd, a nie zgodę na pominięcie kontroli.
Przywrócić zaufany dysk/dane przed kontynuacją; nie wymuszać obejścia blokady.

### Zakres i dowody bezpieczeństwa

- Plan zapisuje dokładny inwentarz, fingerprinty, wszystkie identyfikatory i
  oryginalne ciągi ścieżek oraz logiczny skrót **całej** bazy. Przed przygotowaniem
  baza musi być identyczna. Snapshot planu i nowa kopia offline powstają przez
  SQLite backup API z kontrolą integralności; nie jest kopiowany sam plik WAL.
- Prywatny dziennik SQLite z synchronizacją FULL, snapshoty i sekwencyjnie
  przygotowane wyniki znajdują się na dysku archiwum. Trwałe archiwum pierwszej
  partii nie jest modyfikowane. Miejsca wymagają również lokalne pliki tymczasowe;
  sprawdzana jest rezerwa 2 GiB na obu dyskach.
- JPEG/PNG: WebP quality 82, maksymalnie 1600×1600, bez powiększania, orientacja
  EXIF, białe tło dla przezroczystości, nowe płótno RGB bez EXIF/GPS/ICC/XMP.
  Każdy wynik przechodzi pełne dekodowanie i kontrolę oczekiwanych wymiarów.
  Istniejące WebP nie są ponownie stratnie kodowane. Animowane, uszkodzone,
  ponad 24 MiB / 40 mln pikseli oraz wyniki nie mniejsze od źródła pozostają
  oryginalne z jawnym powodem w dzienniku. Nietypowe i niezarejestrowane obrazy
  z zakresu archiwum podlegają tej samej polityce; nie są porzucane.
- Nazwa wyniku zawiera SHA-256 **pełnej ścieżki źródłowej**, więc JPEG i PNG o tym
  samym rdzeniu nie kolidują. Wynik trafia z etapu na I do lokalnego pliku
  tymczasowego, jest utrwalany i publikowany atomowym twardym dowiązaniem NTFS
  bez nadpisania. Ścieżki są względne do katalogu danych, nowe używają `/`;
  przejścia poza katalog, ścieżki specjalne Windows i reparse points są odrzucane.
- Jedna transakcja zmienia wyłącznie `ShoePhoto.file_path`, dla **wszystkich**
  identyfikatorów współdzielących źródło. Numery, kolejność, pozostałe kolumny,
  tabele i schemat muszą być dokładnie zgodne ze snapshotem. Pliki legacy
  pozostają w swoim katalogu, więc istniejąca polityka serwowania nie rozszerza
  dostępu do prywatnych katalogów. Dotychczasowa synchronizacja nadal wybiera
  katalog standardowy zamiast legacy, gdy oba istnieją; nie uruchamiać jej jako
  testu na rzeczywistej bazie.
- Dopiero po przełączeniu bazy usuwany jest **pojedynczy dokładny** oryginał,
  po ponownym sprawdzeniu fingerprintu i SHA-256 źródła oraz trwałego archiwum,
  a także hashy i dekodowania wyniku. Żaden katalog nie jest zbiorczo kasowany.
  Końcowa kontrola wymaga kompletności plików i powiązań oraz braku dodatkowych
  obrazów/oryginałów powodujących duplikaty synchronizacji.

[Testy drugiej partii](tests/test_photo_migrate.py) obejmują wyłącznie dane
syntetyczne: awarie na granicach trwałości, wznowienie i wycofanie po kasowaniu,
zmienione źródła/archiwa/bazy, współdzielone referencje, duplikaty rdzeni,
blokady startu i żądań, brak powiększania, orientację, przezroczystość,
kolizje, odłączenie nośnika i brak miejsca. Raporty, logi, źródła, snapshoty,
znacznik konserwacji i dziennik nie należą do repozytorium. Automatyczny ingest
oraz miniatury pozostają poza zakresem tej ręcznej partii.
