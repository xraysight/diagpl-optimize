# Współtworzenie projektu

Dziękujemy za zainteresowanie rozwojem DIAG.pl Optimize.

## Zgłaszanie błędów

W zgłoszeniu podaj:

- wersję Pythona (`python3 --version`),
- system operacyjny,
- używany interfejs (WWW lub CLI),
- kroki pozwalające odtworzyć problem,
- oczekiwany i rzeczywisty rezultat,
- komunikat błędu bez danych prywatnych.

Nie dołączaj lokalnej bazy SQLite ani pełnych eksportów danych, jeśli nie są niezbędne do odtworzenia błędu.

## Przygotowanie środowiska

Podstawowy projekt nie ma obowiązkowych zależności zewnętrznych:

```bash
git clone URL_TWOJEGO_REPOZYTORIUM
cd diagpl-optimize
python3 -m unittest discover -s tests -v
```

Opcjonalny solver ILP wymaga `numpy` i `scipy`. Instaluj je w środowisku wirtualnym, nie globalnie.

## Zasady zmian

- zachowaj polski język interfejsu użytkownika,
- nie dodawaj zależności bez wyraźnej korzyści,
- nie zapisuj w repozytorium baz SQLite, snapshotów API ani sekretów,
- dla poprawki błędu dodaj test regresyjny, jeśli istnieje odpowiedni wzorzec testów,
- ogranicz zmiany formatowania do modyfikowanego fragmentu,
- nie zakładaj stabilności zewnętrznego API DIAG.pl.

## Weryfikacja

Przed wysłaniem pull requesta uruchom:

```bash
python3 -m py_compile \
  diagpl_optimize_core.py \
  diagpl-optimize-cli.py \
  diagpl-optimize-gui.py \
  tests/*.py
python3 -m unittest discover -s tests -v
```

Opisz w pull requeście zmianę zachowania, sposób weryfikacji oraz znane ograniczenia.
