# News Map

Mapa świata na ekranie e-paper (Seeed reTerminal E1002), która rano pokazuje, gdzie dzieje się coś nietypowego. Styl jest cyberpunkowy: czarne tło, ląd jako matryca kropek i siatka współrzędnych. Kraje, o których media nagle piszą dużo więcej niż zwykle, świecą na żółto albo czerwono. W USA podświetla się konkretny stan, a nie cały kraj. Pod mapą są maksymalnie cztery jednozdaniowe wyjaśnienia.

## Jak to działa

```
GDELT (co 15 min)  ->  GitHub Actions (co godzinę)  ->  GitHub Pages  ->  reTerminal
 zdarzenia z mediów     liczy anomalie, rysuje           news.bin         pobiera i wyświetla,
 z całego świata        obrazek 800x480                  preview.png      potem śpi
```

- **Dane**: GDELT 2.0 Events. Każde zdarzenie ma kraj i adres artykułu. Liczymy unikalne artykuły na kraj w każdej godzinie. W USA liczymy też osobno każdy stan (kod ADM1 z GDELT), więc pożar w Kalifornii zapala Kalifornię, a nie całe Stany.
- **Co znaczy „dzieje się coś”**: porównujemy udział kraju w światowym wolumenie newsów z ostatnich 24 h z tym samym oknem z poprzednich 30 dni (z-score). Liczy się udział, a nie surowa liczba, więc USA i Chiny nie świecą bez przerwy.
  - żółty: z ≥ 2 i co najmniej 1,6 raza więcej niż zwykle
  - czerwony: z ≥ 3,2 i co najmniej 2,5 raza więcej niż zwykle
  - musi być minimum 30 artykułów
- **Nagłówki**: najczęściej cytowane artykuły z danego kraju. Jeśli dodasz klucz API Anthropic, Claude streszcza je jednym zdaniem po polsku. Bez klucza pokazuje się oryginalny tytuł, zwykle po angielsku.
- **Obrazek** generuje się w całości w Pythonie. Urządzenie nic nie liczy, tylko pobiera gotową ramkę 192 000 bajtów (2 piksele na bajt, indeksy 6 kolorów) i ją wyświetla.

## Uruchomienie krok po kroku

### 1. GitHub

1. Załóż **publiczne** repo, np. `news-map`. Na darmowym koncie GitHub Pages działa tylko z publicznymi repozytoriami.
2. Wrzuć do niego wszystkie pliki z tego folderu, razem z ukrytym `.github/`:
   ```
   git init && git add . && git commit -m "news map"
   git branch -M main
   git remote add origin https://github.com/kay477/daily-data.git
   git push -u origin main
   ```
3. **Actions** → „Aktualizacja mapy” → **Run workflow**. Pierwsze uruchomienie pobiera 30 dni historii (ok. 2900 plików) i trwa ok. 15–30 min. Kolejne trwają około minuty.
4. **Settings → Pages** → Source: *Deploy from a branch* → branch `gh-pages`, folder `/ (root)` → Save.
5. Po chwili podgląd jest pod adresem `https://kay477.github.io/daily-data/preview.png`.

Od tej pory mapa aktualizuje się sama co godzinę (o :07, choć GitHub potrafi spóźnić się o kilkanaście minut).

### 2. Polskie streszczenia (opcjonalnie)

Settings → Secrets and variables → Actions → **New repository secret**:
- nazwa `ANTHROPIC_API_KEY`, wartość: klucz z console.anthropic.com

To jedno małe zapytanie na godzinę. API jest płatne, ale przy takiej skali koszt jest niewielki. Model zmienisz zmienną `NEWSMAP_MODEL` (domyślnie `claude-haiku-5-5`).

### 3. reTerminal E1002

1. Zainstaluj **Arduino IDE 2**, a w nim:
   - Boards Manager: **esp32 by Espressif Systems**
   - Library Manager: **GxEPD2** (Jean-Marc Zingg) i **Adafruit GFX Library**
2. Otwórz `firmware/news_map_display/news_map_display.ino`.
3. Skopiuj `config.example.h` jako `config.h` i wpisz:
   - Wi-Fi (tylko **2,4 GHz**)
   - `IMAGE_URL` = `https://kay477.github.io/daily-data/news.bin`
4. Tools:
   - Board: **XIAO_ESP32S3**
   - PSRAM: **OPI PSRAM** (bez tego nie zadziała)
   - Upload Speed: **115200**
5. Podłącz USB-C, włącz urządzenie przełącznikiem z tyłu i kliknij Upload.

Działanie: urządzenie budzi się co godzinę o :25, pobiera obrazek i odświeża ekran tylko wtedy, gdy obrazek się zmienił. Odświeżanie trwa ok. 20 s i ekran przy tym mruga, tak już działa ten typ e-papieru. Między 23 a 6 śpi. Przycisk na GPIO 3 budzi je i wymusza odświeżenie. Godziny zmienisz w `config.h`.

Na baterii 2000 mAh przy 17 odświeżeniach dziennie wytrzyma kilka tygodni. Jeśli stoi przy łóżku, trzymaj je po prostu na ładowarce USB-C.

## Test na własnym komputerze

```
pip install -r requirements.txt
python -m newsmap --fake --state test/state --out test                  # sztuczne dane, bez internetu
python -m newsmap --backfill-days 7 --state site/state --out site     # prawdziwe dane z GDELT
```
Wynik: `preview.png`, `news.bin` i `news.json` (wyniki wszystkich krajów, przydatne do strojenia).

## Strojenie

- Progi czułości: `newsmap/score.py` (`LEVEL1`, `LEVEL2`, `MIN_ARTICLES`, `MIN_STD`)
- Styl: na GitHubie Settings → Secrets and variables → Actions → zakładka **Variables** → zmienna `NEWSMAP_SCHEME` z jedną z wartości poniżej (lokalnie: `--scheme ...`):
  - `neon` (domyślny): czarne tło, niebieskie kropki, HUD
  - `2077`: klimat Cyberpunk 2077, czyli żółte tło, czarne kropki, czerwone i niebieskie alerty, ścięte rogi, pasy ostrzegawcze
  - `nightcity`: czarne tło, żółte kropki, czerwone akcenty
  - `matrix`: zielone kropki
  - `mono`: białe drobne kropki, najbezpieczniejszy kontrast
- Kraje dzielone na regiony: `SUBDIVIDED` w `newsmap/gdelt.py` (na razie tylko USA, bo tylko dla stanów są dołączone kształty)
- Liczba nagłówków: `--stories 3`
- Krótsze nazwy krajów na liście: `SHORT_NAMES` w `newsmap/render.py`

## Ograniczenia, o których warto wiedzieć

- Przez pierwsze dni historia jest krótka. Kraje zaczynają się zapalać po 3 dniach, a wiarygodnie po około 2 tygodniach. Do tego czasu w nagłówku widać „zbieram historię”. Jeśli od razu pobierzesz 30 dni (domyślnie), ten problem nie występuje.
- GDELT to głównie media anglojęzyczne i globalne. Lokalne polskie sprawy będą niedoreprezentowane.
- Przypisanie zdarzenia do kraju robi automat GDELT, więc zdarza się szum.
- GitHub wyłącza zaplanowane workflowy w repo, w którym przez 60 dni nie było żadnej aktywności. Jeśli mapa przestanie się aktualizować, wejdź w Actions i włącz workflow ponownie.

## Struktura

```
newsmap/gdelt.py      pobieranie GDELT, stan godzinowy (31 dni)
newsmap/score.py      wykrywanie anomalii
newsmap/headlines.py  tytuły artykułów + streszczenie po polsku
newsmap/render.py     obrazek 800x480, 6 kolorów, news.bin
data/countries.json   kształty krajów (Natural Earth 1:50m przez world-atlas), stanów USA (us-atlas) + mapowanie FIPS->ISO
firmware/             szkic Arduino dla reTerminal E1002
tools/                przebudowa countries.json, sztuczne dane testowe
```

Kształty krajów: Natural Earth (domena publiczna), pakiety world-atlas i us-atlas (licencja ISC, `data/*_LICENSE`). Czcionki: DejaVu (licencja wolna).
