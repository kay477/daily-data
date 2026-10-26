/*
  News Map – firmware dla Seeed reTerminal E1002 (7,3" E Ink Spectra 6, XIAO ESP32-S3)

  Co robi:
    1. budzi się, łączy z Wi-Fi, ustawia czas z NTP,
    2. pobiera news.bin (gotowa ramka 800x480, 4 bity/piksel) z GitHub Pages,
    3. jeśli obrazek się zmienił – rysuje go na ekranie,
    4. zasypia do następnej aktualizacji (w nocy śpi do rana).
  Przycisk (GPIO 3) budzi urządzenie i wymusza odświeżenie.

  Arduino IDE:
    Płytka:  esp32 by Espressif -> XIAO_ESP32S3
    PSRAM:   OPI PSRAM   (wymagane!)
    Upload Speed: 115200 (wyższe potrafią zrywać wgrywanie)
    Biblioteki: GxEPD2 (Jean-Marc Zingg) + Adafruit GFX Library
  Ustawienia Wi-Fi i adresu wpisz w config.h (skopiuj z config.example.h).
*/
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <SPI.h>
#include <time.h>
#include <esp_sleep.h>
#include <driver/rtc_io.h>
#include <GxEPD2_7C.h>
#include "config.h"

// ---- piny reTerminal E1002 ----
#define EPD_SCK   7
#define EPD_MOSI  9
#define EPD_CS   10
#define EPD_DC   11
#define EPD_RST  12
#define EPD_BUSY 13
#define BUTTON_PIN GPIO_NUM_3   // przyciski są aktywne stanem niskim

static const uint16_t W = 800, H = 480;
static const size_t FRAME_BYTES = (size_t)W * H / 2;  // 192 000

// Kolejność MUSI zgadzać się z PALETTE_RGB w newsmap/render.py
static const uint16_t COLORS[6] = {GxEPD_BLACK, GxEPD_WHITE, GxEPD_YELLOW, GxEPD_RED, GxEPD_BLUE, GxEPD_GREEN};

SPIClass hspi(HSPI);
GxEPD2_7C<GxEPD2_730c_GDEP073E01, GxEPD2_730c_GDEP073E01::HEIGHT / 4>
    display(GxEPD2_730c_GDEP073E01(EPD_CS, EPD_DC, EPD_RST, EPD_BUSY));

RTC_DATA_ATTR uint32_t lastHash = 0;   // przetrwa deep sleep
RTC_DATA_ATTR uint32_t failCount = 0;

// ---------------------------------------------------------------------------

uint32_t fnv1a(const uint8_t* p, size_t n) {
  uint32_t h = 2166136261u;
  for (size_t i = 0; i < n; i++) { h ^= p[i]; h *= 16777619u; }
  return h;
}

bool connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) delay(500);
  Serial.printf("Wi-Fi: %s\n", WiFi.status() == WL_CONNECTED ? "OK" : "BRAK");
  return WiFi.status() == WL_CONNECTED;
}

bool syncTime() {
  configTzTime(TZ_INFO, "pool.ntp.org", "time.google.com");
  struct tm t;
  return getLocalTime(&t, 10000);
}

// Pobiera ramkę do bufora w PSRAM. Zwraca true, gdy przyszło dokładnie 192 000 bajtów.
bool download(uint8_t* buf) {
  WiFiClientSecure client;
  client.setInsecure();               // nie sprawdzamy certyfikatu – to tylko obrazek
  HTTPClient http;
  http.setTimeout(20000);
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
  if (!http.begin(client, IMAGE_URL)) return false;
  int code = http.GET();
  Serial.printf("HTTP %d, rozmiar %d\n", code, http.getSize());
  if (code != HTTP_CODE_OK) { http.end(); return false; }

  WiFiClient* stream = http.getStreamPtr();
  size_t got = 0;
  uint32_t t0 = millis();
  while (got < FRAME_BYTES && millis() - t0 < 30000) {
    size_t avail = stream->available();
    if (avail) {
      got += stream->readBytes(buf + got, min(avail, FRAME_BYTES - got));
      t0 = millis();
    } else if (!http.connected()) {
      break;
    } else {
      delay(5);
    }
  }
  http.end();
  Serial.printf("Pobrano %u / %u B\n", (unsigned)got, (unsigned)FRAME_BYTES);
  return got == FRAME_BYTES;
}

void drawFrame(const uint8_t* buf) {
  hspi.begin(EPD_SCK, -1, EPD_MOSI, -1);
  display.init(115200, true, 2, false, hspi, SPISettings(2000000, MSBFIRST, SPI_MODE0));
  display.setRotation(0);
  display.setFullWindow();
  display.firstPage();
  do {
    display.fillScreen(GxEPD_WHITE);
    for (uint16_t y = 0; y < H; y++) {
      const uint8_t* row = buf + (size_t)y * (W / 2);
      for (uint16_t x = 0; x < W; x += 2) {
        uint8_t b = row[x / 2];
        uint8_t a = b >> 4, c = b & 0x0F;
        if (a != 1 && a < 6) display.drawPixel(x, y, COLORS[a]);       // biały już jest
        if (c != 1 && c < 6) display.drawPixel(x + 1, y, COLORS[c]);
      }
    }
  } while (display.nextPage());
  display.hibernate();
}

// Ile sekund spać: do minuty WAKE_MINUTE następnej godziny, a w nocy do rana.
uint64_t secondsToNextUpdate() {
  struct tm t;
  if (!getLocalTime(&t, 100)) return 3600;
  int now = t.tm_hour * 3600 + t.tm_min * 60 + t.tm_sec;
  int next = (t.tm_hour + (t.tm_min >= WAKE_MINUTE ? 1 : 0)) * 3600 + WAKE_MINUTE * 60;
  int nextHour = (next / 3600) % 24;
  bool night = NIGHT_START > NIGHT_END
                   ? (nextHour >= NIGHT_START || nextHour < NIGHT_END)
                   : (nextHour >= NIGHT_START && nextHour < NIGHT_END);
  if (night) {
    next = NIGHT_END * 3600 + WAKE_MINUTE * 60;
    if (next <= now) next += 24 * 3600;
  }
  int s = next - now;
  if (s < 60) s += 3600;
  return (uint64_t)s;
}

void goToSleep(uint64_t seconds) {
  Serial.printf("Śpię %llu s\n", seconds);
  Serial.flush();
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  esp_sleep_enable_timer_wakeup(seconds * 1000000ULL);
  rtc_gpio_pullup_en(BUTTON_PIN);
  rtc_gpio_pulldown_dis(BUTTON_PIN);
  esp_sleep_enable_ext0_wakeup(BUTTON_PIN, 0);
  esp_deep_sleep_start();
}

void setup() {
  Serial.begin(115200);
  delay(300);
  bool byButton = esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT0;
  Serial.printf("\n== News Map == (przycisk: %d)\n", byButton);

  uint8_t* buf = (uint8_t*)ps_malloc(FRAME_BYTES);
  if (!buf) {
    Serial.println("Brak PSRAM! Ustaw Tools -> PSRAM -> OPI PSRAM");
    goToSleep(3600);
  }

  bool ok = connectWifi() && download(buf);
  syncTime();
  if (ok) {
    failCount = 0;
    uint32_t h = fnv1a(buf, FRAME_BYTES);
    if (h != lastHash || byButton) {
      Serial.println("Nowy obrazek – rysuję (ok. 20 s)");
      drawFrame(buf);
      lastHash = h;
    } else {
      Serial.println("Bez zmian – nie odświeżam ekranu");
    }
    goToSleep(secondsToNextUpdate());
  } else {
    failCount++;
    // błąd sieci: spróbuj ponownie za 10 min, potem coraz rzadziej (max 1 h)
    goToSleep(min<uint64_t>(600ULL * failCount, 3600ULL));
  }
}

void loop() {}
