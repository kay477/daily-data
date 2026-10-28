/*
  News Map – firmware dla Seeed reTerminal E1002 (7,3" E Ink Spectra 6, XIAO ESP32-S3)

  Co robi:
    1. budzi się, łączy z Wi-Fi, ustawia czas z NTP,
    2. pobiera ramkę bieżącego ekranu (800x480, 4 bity/piksel) z GitHub Pages,
    3. jeśli obrazek się zmienił – rysuje go na ekranie,
    4. zasypia do następnej aktualizacji (w nocy śpi do rana).

  Trzy ekrany, wybierane przyciskami (patrząc od przodu):
    lewy      -> MAPA      (news.bin)
    środkowy  -> RYNKI     (rynki.bin)
    prawy     -> BRIEFING  (briefing.bin)
  Przycisk bieżącego ekranu wymusza jego odświeżenie. Dioda świeci, gdy urządzenie pracuje.
  Pierwsza aktualizacja po nocy przełącza na MORNING_SCREEN (domyślnie briefing).

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
// przyciski są aktywne stanem niskim; KEY0 = prawy (zielony), KEY1 = środkowy, KEY2 = lewy
#define KEY0 GPIO_NUM_3
#define KEY1 GPIO_NUM_4
#define KEY2 GPIO_NUM_5
#define LED_PIN 6               // dioda na obudowie, LOW = świeci

// ---- ekrany ----
enum Screen : uint8_t { SCR_MAP = 0, SCR_MARKETS = 1, SCR_BRIEF = 2, SCR_COUNT = 3 };
static const char* SCREEN_FILE[SCR_COUNT] = {"news.bin", "rynki.bin", "briefing.bin"};
static const char* SCREEN_NAME[SCR_COUNT] = {"MAPA", "RYNKI", "BRIEFING"};

// starsze config.h nie mają tych ustawień – wtedy wartości domyślne
#ifndef MORNING_SCREEN
#define MORNING_SCREEN SCR_BRIEF   // ustaw -1, żeby rano nie przełączał ekranu
#endif

static const uint16_t W = 800, H = 480;
static const size_t FRAME_BYTES = (size_t)W * H / 2;  // 192 000

// Kolejność MUSI zgadzać się z PALETTE_RGB w newsmap/render.py
static const uint16_t COLORS[6] = {GxEPD_BLACK, GxEPD_WHITE, GxEPD_YELLOW, GxEPD_RED, GxEPD_BLUE, GxEPD_GREEN};

SPIClass hspi(HSPI);
GxEPD2_7C<GxEPD2_730c_GDEP073E01, GxEPD2_730c_GDEP073E01::HEIGHT / 4>
    display(GxEPD2_730c_GDEP073E01(EPD_CS, EPD_DC, EPD_RST, EPD_BUSY));

RTC_DATA_ATTR uint32_t lastHash = 0;     // przetrwa deep sleep
RTC_DATA_ATTR uint32_t failCount = 0;
RTC_DATA_ATTR uint8_t screen = SCR_MAP;   // co jest teraz na ekranie
RTC_DATA_ATTR bool sleptOverNight = false;

// deklaracje z góry – Arduino IDE nie musi ich wtedy zgadywać
uint32_t fnv1a(const uint8_t* p, size_t n);
bool connectWifi();
bool syncTime();
String screenUrl(uint8_t scr);
bool download(uint8_t* buf, const String& url);
void drawFrame(const uint8_t* buf);
uint64_t secondsToNextUpdate();
void goToSleep(uint64_t seconds);
int screenFromWakeup();

// ---------------------------------------------------------------------------

uint32_t fnv1a(const uint8_t* p, size_t n) {
  uint32_t h = 2166136261u;
  for (size_t i = 0; i < n; i++) { h ^= p[i]; h *= 16777619u; }
  return h;
}

// Sieci z config.h w kolejności priorytetu; puste nazwy są pomijane.
#ifndef WIFI_SSID2
#define WIFI_SSID2 ""
#define WIFI_PASS2 ""
#endif
#ifndef WIFI_SSID3
#define WIFI_SSID3 ""
#define WIFI_PASS3 ""
#endif
#ifndef EDUROAM_LOGIN
#define EDUROAM_LOGIN ""
#define EDUROAM_PASS ""
#endif

bool waitConnected(uint32_t ms) {
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < ms) delay(250);
  return WiFi.status() == WL_CONNECTED;
}

bool visible(int n, const char* ssid) {
  for (int i = 0; i < n; i++)
    if (WiFi.SSID(i) == ssid) return true;
  return false;
}

// Skanuje okolicę i łączy się z pierwszą widoczną znaną siecią (dom, hotspot telefonu, eduroam...).
bool connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  int n = WiFi.scanNetworks();
  Serial.printf("Wi-Fi: widzę %d sieci\n", n);
  const char* ssids[3] = {WIFI_SSID, WIFI_SSID2, WIFI_SSID3};
  const char* passes[3] = {WIFI_PASS, WIFI_PASS2, WIFI_PASS3};
  for (int k = 0; k < 3; k++) {
    if (!ssids[k][0] || (n > 0 && !visible(n, ssids[k]))) continue;
    Serial.printf("Wi-Fi: łączę z %s\n", ssids[k]);
    WiFi.begin(ssids[k], passes[k]);
    if (waitConnected(15000)) { Serial.println("Wi-Fi: OK"); return true; }
    WiFi.disconnect();
  }
  if (EDUROAM_LOGIN[0] && (n <= 0 || visible(n, "eduroam"))) {
    Serial.println("Wi-Fi: łączę z eduroam");
    WiFi.begin("eduroam", WPA2_AUTH_PEAP, EDUROAM_LOGIN, EDUROAM_LOGIN, EDUROAM_PASS);
    if (waitConnected(20000)) { Serial.println("Wi-Fi: OK"); return true; }
  }
  Serial.println("Wi-Fi: BRAK – żadna znana sieć nie odpowiada");
  return false;
}

bool syncTime() {
  configTzTime(TZ_INFO, "pool.ntp.org", "time.google.com");
  struct tm t;
  return getLocalTime(&t, 10000);
}

// Pobiera ramkę do bufora w PSRAM. Zwraca true, gdy przyszło dokładnie 192 000 bajtów.
// Adres pliku danego ekranu: IMAGE_URL z config.h to .../news.bin, podmieniamy nazwę pliku.
String screenUrl(uint8_t scr) {
  String base = IMAGE_URL;
  return base.substring(0, base.lastIndexOf('/') + 1) + SCREEN_FILE[scr];
}

bool download(uint8_t* buf, const String& url) {
  WiFiClientSecure client;
  client.setInsecure();               // nie sprawdzamy certyfikatu – to tylko obrazek
  HTTPClient http;
  http.setTimeout(20000);
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
  Serial.println(url);
  if (!http.begin(client, url)) return false;
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
  sleptOverNight = night;
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
  digitalWrite(LED_PIN, HIGH);  // dioda gaśnie
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  esp_sleep_enable_timer_wakeup(seconds * 1000000ULL);
  const gpio_num_t keys[3] = {KEY0, KEY1, KEY2};
  uint64_t mask = 0;
  for (gpio_num_t k : keys) {
    rtc_gpio_pullup_en(k);
    rtc_gpio_pulldown_dis(k);
    mask |= 1ULL << k;
  }
  esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ANY_LOW);  // dowolny przycisk budzi
  esp_deep_sleep_start();
}

// Który przycisk obudził urządzenie -> który ekran. -1 = nie przycisk.
int screenFromWakeup() {
  if (esp_sleep_get_wakeup_cause() != ESP_SLEEP_WAKEUP_EXT1) return -1;
  uint64_t st = esp_sleep_get_ext1_wakeup_status();
  if (st & (1ULL << KEY2)) return SCR_MAP;
  if (st & (1ULL << KEY1)) return SCR_MARKETS;
  if (st & (1ULL << KEY0)) return SCR_BRIEF;
  return -1;
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);  // dioda świeci = pracuję
  delay(300);

  int pressed = screenFromWakeup();
  bool byButton = pressed >= 0;
  bool forceDraw = byButton;
  if (byButton) {
    screen = pressed;
  } else if (esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER && sleptOverNight
             && MORNING_SCREEN >= 0 && MORNING_SCREEN < SCR_COUNT && screen != MORNING_SCREEN) {
    screen = MORNING_SCREEN;   // dzień dobry – zaczynamy od briefingu
    forceDraw = true;
  }
  if (screen >= SCR_COUNT) screen = SCR_MAP;
  Serial.printf("\n== News Map == ekran: %s (przycisk: %d)\n", SCREEN_NAME[screen], byButton);

  uint8_t* buf = (uint8_t*)ps_malloc(FRAME_BYTES);
  if (!buf) {
    Serial.println("Brak PSRAM! Ustaw Tools -> PSRAM -> OPI PSRAM");
    goToSleep(3600);
  }

  bool ok = connectWifi() && download(buf, screenUrl(screen));
  syncTime();
  if (ok) {
    failCount = 0;
    uint32_t h = fnv1a(buf, FRAME_BYTES);
    if (h != lastHash || forceDraw) {
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
