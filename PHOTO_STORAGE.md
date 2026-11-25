# Bezpieczny lokalny audyt zdjęć i próbki kompresji

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
