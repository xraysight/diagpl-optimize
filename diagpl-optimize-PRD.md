# DIAG.pl Optimize — PRD

## 1. Cel produktu

`diagpl-optimize-cli.py` to skrypt CLI w Pythonie do pobierania katalogu produktów DIAG.pl, zapisywania aktualnego snapshotu do SQLite oraz optymalizacji kosztu zakupu badań przez dobór najtańszej kombinacji pojedynczych produktów i pakietów.

Główny przypadek użycia: użytkownik podaje listę badań, a program wskazuje, czy bardziej opłaca się kupić je osobno, czy jako jeden lub więcej pakietów częściowo/całkowicie pokrywających tę listę.

## 2. Lokalizacja plików

- CLI: `diagpl-optimize-cli.py`
- Web GUI: `diagpl-optimize-gui.py`
- Wspólna logika: `diagpl_optimize_core.py`
- Domyślna baza SQLite: `diagpl-products.sqlite`
- Ten PRD: `diagpl-optimize-PRD.md`

Domyślna baza ma znajdować się w tym samym katalogu co skrypt, niezależnie od katalogu, z którego użytkownik uruchamia komendę.

## 3. Źródło danych

API:

```text
https://api-eshop.diag.pl/api/front/v1/products?filter[institution]=ID&limit=200&page=N&include=prices
```

Parametry:

- `institution`: wymagane ID wybrane z `lista-punktow`
- `limit`: `200`
- `include`: `prices`

API zwraca paginację w `meta`:

- `current_page`
- `last_page`
- `per_page`
- `total`

Skrypt musi pobrać wszystkie strony od `page=1` do `last_page`.

## 4. Interfejsy

Logika API, SQLite i optymalizacji znajduje się we wspólnym module `diagpl_optimize_core.py`.

Web GUI uruchamia się lokalnie bez dodatkowych zależności:

```bash
python3 diagpl-optimize-gui.py
```

Domyślnie aplikacja otwiera `http://127.0.0.1:8765`. Dostępne są opcje `--adres`, `--port`, `--baza` i `--bez-przegladarki`.

Przy pierwszym uruchomieniu GUI automatycznie inicjalizuje brakującą bazę i pobiera wyłącznie listę instytucji. Po otwarciu strony użytkownik musi najpierw wyszukać i wybrać punkt pobrań po nazwie, mieście lub adresie. Techniczne ID instytucji pozostaje ukryte w interfejsie. Wybór punktu pobiera i atomowo zapisuje produkty oraz ceny dla jego `institution_id`; podczas pobierania pozostałe kontrolki są zablokowane. Dopiero po zakończeniu pobierania dostępne są wyszukiwanie produktów, lista badań i optymalizacja. Ponowne otwarcie strony odtwarza ostatnio wybrany punkt z najnowszego snapshotu. Wybrana lista badań jest zachowywana lokalnie w przeglądarce dla aktywnej instytucji i może zostać usunięta przyciskiem `Wyczyść`. Zmiana punktu lub odświeżenie katalogu czyści bieżącą listę badań, aby nie mieszać nieaktualnych cen z różnych snapshotów.

### Komendy CLI

Uruchomienie skryptu bez podkomendy wyświetla tę samą główną pomoc co `-h` i kończy się kodem `0`.

### 4.1. `inicjalizuj`

Inicjalizuje bazę i pobiera listę instytucji. To wymagana pierwsza komenda dla nowej lub niepoprawnie zainicjalizowanej bazy:

```bash
python3 diagpl-optimize-cli.py inicjalizuj
```

Komenda nie pobiera cen produktów. Po inicjalizacji należy wybrać ID przez `lista-punktow`, a następnie wykonać `pobierz --punkt ID`.

### 4.2. `pobierz`

Pobiera pełny snapshot z API i odświeża bazę SQLite.

Przykład:

```bash
python3 diagpl-optimize-cli.py pobierz --punkt 889
```

Opcje:

```text
--baza PLIK                    ścieżka do SQLite
--plik-json [PLIK]             zapisz pełny katalog JSON; bez PLIKU tworzy datowany plik obok bazy
--punkt ID                     wymagany identyfikator punktu pobrań
--liczba-na-strone LICZBA      domyślnie 200
--adres-api URL                bazowy adres API
--czas-oczekiwania SEKUNDY     limit czasu żądania HTTP
--opoznienie SEKUNDY           opóźnienie między stronami
--wyczysc / --zachowaj         domyślnie --wyczysc
```

Wymagania:

- Domyślne `--wyczysc` buduje od zera kompletną bazę zastępczą w lokalnym katalogu tymczasowym, waliduje ją i podmienia plik docelowy.
- `--zachowaj` zachowuje wcześniejsze rekordy `fetch_runs` i `product_offers`, ale współdzielone tabele `products`, `media` i `package_items` są aktualizowane bieżącymi danymi; nie jest to pełna historia wszystkich wersji produktu.
- Przy `--plik-json` skrypt zapisuje pełny pobrany snapshot do JSON.
- Wynik komendy ma być wypisany jako JSON z informacją o:
  - ścieżce bazy,
  - ścieżce JSON albo `null`,
  - `fetch_run_id`,
  - liczbie stron,
  - liczbie produktów,
  - licznikach tabel.

Uwagi techniczne:

- Domyślna docelowa baza zawsze znajduje się obok skryptu: `diagpl-products.sqlite`.
- Dla domyślnego `--wyczysc` kompletna baza jest tymczasowo budowana i walidowana w `/tmp`, a następnie kopiowana do pliku stagingowego obok docelowej bazy i podmieniana. `/tmp` nie jest miejscem trwałego przechowywania bazy.
- Jawne `--baza PATH` zastępuje domyślną lokalizację; bez tej opcji aktualizowany jest plik obok skryptu.
- Po wymianie bazy należy usuwać ewentualne sidecary SQLite:
  - `*.sqlite-journal`
  - `*.sqlite-wal`
  - `*.sqlite-shm`

### 4.3. `lista-punktow`

Wyświetla wszystkie zapisane instytucje w formacie TSV, z ID jako pierwszym polem:

```bash
python3 diagpl-optimize-cli.py lista-punktow
```

```text
ID<TAB>nazwa<TAB>pełny adres
```

Opcjonalne `--szukaj TEKST` filtruje bez rozróżniania wielkości liter po ID, nazwie lub pełnym adresie, np.:

```bash
python3 diagpl-optimize-cli.py lista-punktow --szukaj "Łódź"
```

### 4.4. `lista-badan`

Wyświetla wszystkie dostępne produkty z ostatniego snapshotu.

Przykład:

```bash
python3 diagpl-optimize-cli.py lista-badan
```

Format wyjścia:

```text
Nazwa produktu | cena
```

Wymagania:

- Pokazuje tylko rekordy z `sell_state = 'available'`.
- Cena wyświetlana według priorytetu:
  1. `sale_gross`
  2. `regular_gross`
  3. `minimal_gross`
  4. `brak ceny`
- Cena formatowana po polsku, np. `232,75 PLN`.
- Sortowanie alfabetyczne po nazwie.

### 4.5. `lista-pakietow`

Wyświetla dostępne pakiety wraz z produktami wchodzącymi w ich skład.

Przykład:

```bash
python3 diagpl-optimize-cli.py lista-pakietow
```

Format wyjścia:

```text
Nazwa pakietu | cena pakietu
  - Nazwa produktu w pakiecie | cena produktu
```

Wymagania:

- Pokazuje tylko pakiety z `sell_state = 'available'`.
- Produkty w pakiecie mają być wypisane według pozycji z `package_items.position`.
- Ceny formatowane tak samo jak w `lista-badan`.

### 4.6. `pakiet`

Wyświetla jeden dostępny pakiet, jego cenę oraz ceny produktów składowych.

Przykład:

```bash
python3 diagpl-optimize-cli.py pakiet "Badania na nerki"
```

Format wyjścia:

```text
Badania na nerki | 65,00 PLN
  - Kreatynina | 16,15 PLN
  - Mocz - badanie ogólne | 17,10 PLN
  - Wskaźnik albumina/kreatynina w moczu (ACR) | 44,65 PLN
Suma cen pojedynczych produktów: 77,90 PLN
```

Wymagania:

- Argument może być nazwą pakietu, slugiem, `elab_code` albo unikalnym fragmentem nazwy.
- Exact match ma pierwszeństwo nad dopasowaniem substringiem.
- Jeśli pakiet nie istnieje albo nie jest dostępny, skrypt zwraca czytelny błąd.
- Jeśli dopasowanie jest niejednoznaczne, skrypt zwraca czytelny błąd z przykładowymi pasującymi pakietami.
- Ceny formatowane tak samo jak w `lista-badan`.
- Na końcu skrypt wypisuje sumę cen pojedynczych produktów składowych.

### 4.7. `optymalizuj`

Znajduje najtańszą mieszankę produktów i pakietów pokrywającą listę badań podaną przez użytkownika.

Przykład:

```bash
python3 diagpl-optimize-cli.py optymalizuj \
  "Hemoglobina glikowana (HbA1c)" \
  "Wskaźnik insulinooporności HOMA-IR"
```

Opcje algorytmu:

```text
--algorytm automatyczny|dokladny|ilp|zachlanny   domyślnie automatyczny
--maks-dokladnych-badan LICZBA                   próg dokładnego DP; domyślnie 20
```

Tryb `automatyczny`:

1. dla liczby produktów `<= --maks-dokladnych-badan` używa dokładnego DP po bitmaskach,
2. dla większych wejść próbuje dokładnego ILP przez `scipy.optimize.milp`,
3. jeśli ILP jest niedostępny w aktualnym interpreterze Pythona, używa fallbacku `zachlanny` i oznacza wynik jako przybliżony.

Ważne: `--algorytm ilp` wymaga pakietów `numpy` i `scipy` w tym samym interpreterze, którym uruchamiany jest skrypt. Jeśli użytkownik uruchamia `/usr/bin/python3`, zależności muszą być zainstalowane dla `/usr/bin/python3`; zależności w hermesowym venv nie są wtedy widoczne.

Format wyjścia:

```text
Algorytm: dokładny DP
Suma cen podanych produktów: 131,10 PLN
Suma cen optymalnej mieszanki: 99,00 PLN
Oszczędność: 32,10 PLN
Mieszanka:
- Pakiet: Badania na cukrzycę i insulinooporność | 99,00 PLN
  pokrywa: Hemoglobina glikowana (HbA1c), Wskaźnik insulinooporności HOMA-IR
```

Wymagania funkcjonalne:

- Argumentami są produkty do pokrycia.
- Optymalizacja używa najnowszego katalogu produktów zapisanego w bazie dla punktu wybranego wcześniej przez `pobierz --punkt ID`.
- Produkt może być podany jako:
  - pełna nazwa,
  - `slug`,
  - `elab_code`,
  - unikalny fragment nazwy.
- Exact match ma pierwszeństwo nad dopasowaniem substringiem.
- Jeśli produkt nie zostanie znaleziony, skrypt zwraca czytelny błąd.
- Jeśli dopasowanie jest niejednoznaczne, skrypt zwraca czytelny błąd z listą przykładowych pasujących nazw.
- Duplikaty wejściowe powinny być deduplikowane.
- Optymalizacja ma uwzględniać:
  - pojedyncze produkty,
  - pakiety zawierające co najmniej jeden z produktów wejściowych.
- Pakiet może zostać wybrany nawet jeśli zawiera dodatkowe produkty spoza listy wejściowej, o ile obniża koszt pokrycia produktów wejściowych.
- Wynik ma być optymalny cenowo dla aktualnego snapshotu w trybach `dokladny` i `ilp`.
- Tryb `zachlanny` oraz fallback do niego w `automatyczny` są przybliżone i muszą być wyraźnie oznaczone w wyniku.

## 5. Algorytm optymalizacji

Problem jest wariantem ważonego set cover.

Obecne podejście w trybie `automatyczny`:

1. Każdy żądany produkt dostaje indeks bitowy.
2. Każdy kandydat — pojedynczy produkt albo pakiet — dostaje maskę bitową produktów, które pokrywa.
3. Kandydaci zdominowani są usuwani:
   - jeśli kandydat A pokrywa podzbiór tego co B,
   - a A kosztuje tyle samo lub więcej niż B,
   - A może być usunięty.
4. Dla `N <= --maks-dokladnych-badan`, domyślnie `20`, dokładny DP po maskach bitowych wybiera minimalny koszt dla każdej maski.
5. Dla większego `N` skrypt próbuje dokładnego ILP przez `scipy.optimize.milp`.
6. Jeśli ILP jest niedostępny, skrypt awaryjnie używa algorytmu zachłannego i wypisuje ostrzeżenie, że wynik może nie być globalnie optymalny.

Złożoność:

- Dokładny DP: w najgorszym przypadku wykładnicza względem liczby produktów wejściowych.
- ILP: dokładny algorytm całkowitoliczbowy, zwykle dużo lepiej skaluje się dla większych list, ale nadal rozwiązuje problem NP-trudny.
- Algorytm zachłanny: szybki tryb przybliżony bez gwarancji globalnego optimum.

Ważne: domyślnie skrypt preferuje wynik dokładny. Algorytm zachłanny jest używany tylko jawnie przez `--algorytm zachlanny` albo jako tryb awaryjny, gdy wejście jest większe niż próg DP i ILP jest niedostępny.

## 6. Model SQLite

### 6.1. `fetch_runs`

Metadane pobrania snapshotu.

Najważniejsze pola:

- `id`
- `source_url`
- `institution_id`
- `limit_per_page`
- `page_count`
- `total_items`
- `fetched_at`
- `raw_meta_json`

### 6.2. `products`

Katalog produktów.

Najważniejsze pola:

- `id`
- `uuid`
- `slug`
- `name`
- `type`: `bloodtest` albo `package`
- `elab_code`
- `icd_code`
- `global_waiting_time`
- pola miniatury i additional info
- `raw_product_json`

### 6.3. `product_offers`

Ceny, dostępność i flagi produktu w konkretnym snapshotcie.

Najważniejsze pola:

- `fetch_run_id`
- `institution_id`
- `product_id`
- flagi ecommerce/konsultacji/wysyłki/etc.
- `sale_gross`, `sale_currency`
- `regular_gross`, `regular_currency`
- `minimal_gross`, `minimal_currency`
- `lowest_gross`, `lowest_currency`
- `vat_rate`
- `waiting_time`
- `sell_state`
- `raw_prices_json`

### 6.4. `package_items`

Relacja pakiet → produkt składowy.

Najważniejsze pola:

- `package_id`
- `child_product_id`
- `position`
- `child_status`

### 6.5. `institution_attributes` i `product_institution_attributes`

Słownik i relacja atrybutów instytucjonalnych typu `ECO`, `PPA`, `GIN`.

### 6.6. `media`

Metadane miniatur/grafik.

## 7. Kryteria akceptacji

### Pobieranie

- `pobierz` pobiera wszystkie strony API.
- `pobierz` tworzy/odświeża domyślną bazę obok skryptu.
- `pobierz --plik-json` zapisuje katalog JSON.
- Po imporcie `PRAGMA foreign_key_check` nie zwraca błędów.
- Komenda działa także gdy uruchomiona jest z innego katalogu niż katalog skryptu.

### Listowanie

- `lista-badan` zwraca produkty dostępne, nazwy i ceny.
- `lista-pakietow` zwraca pakiety dostępne oraz ich skład.
- Angielskie nazwy komend i opcji nie są obsługiwane; interfejs CLI jest w całości polski.

### Optymalizacja

- Dla produktów pokrywanych tańszym pakietem program wybiera pakiet.
- Dla produktu bez opłacalnego pakietu program wybiera produkt osobno.
- Dla częściowo pokrywających się pakietów program znajduje globalnie najtańszą kombinację, nie lokalnie najtańszą.
- Wynik pokazuje sumę cen produktów wejściowych, sumę optymalną, oszczędność i skład mieszanki.

## 8. Przykłady testowe

### 8.1. Pobieranie

```bash
python3 diagpl-optimize-cli.py pobierz --punkt 889 --opoznienie 0 --czas-oczekiwania 30
```

Oczekiwane:

- JSON na stdout z `pages`, `items`, `counts`.
- Baza istnieje: `diagpl-products.sqlite`.
- Brak plików `diagpl-products.sqlite-journal`, `diagpl-products.sqlite-wal`, `diagpl-products.sqlite-shm` po zakończeniu.

### 8.2. Lista badań

```bash
python3 diagpl-optimize-cli.py lista-badan | head
```

Oczekiwane:

- Linie w formacie `Nazwa | 123,45 PLN`.

### 8.3. Lista pakietów

```bash
python3 diagpl-optimize-cli.py lista-pakietow | head -20
```

Oczekiwane:

- Linie pakietów bez wcięcia.
- Produkty składowe poprzedzone `  - `.

### 8.4. Optymalizacja — pakiet tańszy niż produkty osobno

```bash
python3 diagpl-optimize-cli.py optymalizuj \
  "Hemoglobina glikowana (HbA1c)" \
  "Wskaźnik insulinooporności HOMA-IR"
```

Oczekiwane:

- Wynik wybiera pakiet `Badania na cukrzycę i insulinooporność`, jeśli aktualny snapshot zachowuje ceny obserwowane podczas implementacji.

### 8.5. Optymalizacja — pojedynczy produkt

```bash
python3 diagpl-optimize-cli.py optymalizuj "CRP, ilościowo"
```

Oczekiwane:

- Suma produktów i suma optymalna są takie same, chyba że aktualny snapshot zawiera tańszy pakiet obejmujący `CRP, ilościowo`.

## 9. Ograniczenia i przyszłe rozszerzenia

### Obecne ograniczenia

- Projekt zawiera testy regresyjne CLI, GUI, obsługi punktów pobrań, wyszukiwania i optymalizacji; nadal nie wszystkie ścieżki importu z zewnętrznego API mają osobne testy jednostkowe.
- Dopasowanie nazw jest proste: dokładna nazwa, skrót adresu, kod eLab albo fragment nazwy.
- Brak wyniku JSON dla komend listujących i optymalizacji.
- Brak limitu ochronnego dla bardzo dużej liczby produktów wejściowych w optymalizacji.

### Potencjalne rozszerzenia

- Dodać `--format tekst|json`.
- Dodać `--tylko-badania` / `--uwzglednij-pakiety` dla listowania.
- Dodać fuzzy matching z rankingiem podobieństwa.
- Dodać cache/snapshot history zamiast zawsze pełnego czyszczenia.
- Dodać testy jednostkowe dla:
  - formatowania cen,
  - dopasowywania produktów,
  - usuwania kandydatów zdominowanych,
  - DP set cover,
  - importu przykładowego JSON do SQLite.
- Dodać limit ochronny albo ostrzeżenie dla bardzo dużej liczby produktów wejściowych.
- Rozważyć branch and bound jako kolejny dokładny solver dla przypadków, w których ILP jest niedostępny.

## 10. Reguły utrzymania

- Projekt należy utrzymywać poza katalogami wewnętrznymi narzędzi i środowisk wykonawczych.
- Przed zmianami uruchomić:

```bash
python3 -m py_compile diagpl-optimize-cli.py
```

- Po zmianach w CLI sprawdzić:

```bash
python3 diagpl-optimize-cli.py --pomoc
```

- Po zmianach w imporcie sprawdzić:

```bash
python3 diagpl-optimize-cli.py pobierz --punkt 889 --opoznienie 0 --czas-oczekiwania 30
```

- Po zmianach w optymalizacji sprawdzić co najmniej:

```bash
python3 diagpl-optimize-cli.py optymalizuj \
  "Hemoglobina glikowana (HbA1c)" \
  "Wskaźnik insulinooporności HOMA-IR"
```