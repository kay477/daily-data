// Skopiuj ten plik jako config.h (w tym samym folderze) i uzupełnij.
// config.h jest w .gitignore – hasło do Wi-Fi nie trafi na GitHuba.
#pragma once

#define WIFI_SSID "nazwa_sieci"        // tylko Wi-Fi 2,4 GHz!
#define WIFI_PASS "haslo"

// Adres obrazka z GitHub Pages: https://<twoj-login>.github.io/<nazwa-repo>/news.bin
#define IMAGE_URL "https://twoj-login.github.io/news-map/news.bin"

// Strefa czasowa (Polska) – nie zmieniaj
#define TZ_INFO "CET-1CEST,M3.5.0,M10.5.0/3"

// O której minucie każdej godziny się budzić (GitHub Actions startuje o :07 i chwilę mieli)
#define WAKE_MINUTE 25

// Cisza nocna: między tymi godzinami ekran się nie odświeża
#define NIGHT_START 23
#define NIGHT_END   6
