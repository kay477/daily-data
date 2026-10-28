// Skopiuj ten plik jako config.h (w tym samym folderze) i uzupełnij.
// config.h jest w .gitignore – hasło do Wi-Fi nie trafi na GitHuba.
#pragma once

#define WIFI_SSID "nazwa_sieci"        // tylko Wi-Fi 2,4 GHz!
#define WIFI_PASS "haslo"

// Zapasowe sieci (opcjonalnie) – urządzenie łączy się z pierwszą, którą widzi.
// Hotspot iPhone'a: w ustawieniach hotspotu włącz "Maksymalizuj zgodność" (2,4 GHz).
#define WIFI_SSID2 ""
#define WIFI_PASS2 ""
#define WIFI_SSID3 ""
#define WIFI_PASS3 ""

// eduroam (opcjonalnie): login w formie numer_albumu@ug.edu.pl albo taki, jak masz na telefonie
#define EDUROAM_LOGIN ""
#define EDUROAM_PASS ""

// Adres obrazka z GitHub Pages: https://<twoj-login>.github.io/<nazwa-repo>/news.bin
#define IMAGE_URL "https://kay477.github.io/daily-data/news.bin"

// Strefa czasowa (Polska) – nie zmieniaj
#define TZ_INFO "CET-1CEST,M3.5.0,M10.5.0/3"

// O której minucie każdej godziny się budzić (GitHub Actions startuje o :07 i chwilę mieli)
#define WAKE_MINUTE 25

// Cisza nocna: między tymi godzinami ekran się nie odświeża
#define NIGHT_START 23
#define NIGHT_END   6

// Który ekran pokazać przy pierwszej aktualizacji po nocy: 0 = mapa, 1 = rynki, 2 = briefing, -1 = bez zmiany
#define MORNING_SCREEN 2
// O której minucie godziny NIGHT_END ma być pierwsza aktualizacja po nocy (0 = 6:00)
#define MORNING_MINUTE 0
