// Gateway (Arduino UNO B): receives field readings by radio and prints them to the
// Raspberry Pi as one JSON line each; relays valve commands from the Pi to the field node.
//
// Library: RF24 by TMRh20 (SPI is built in)
// Pins: D7 NRF CSN, D8 NRF CE, D11-D13 SPI. USB cable to the Pi at 115200 baud.
//
// Pi -> gateway:  {"cmd":"valve","minutes":22.0,"id":"a1b2c3d4"}
// gateway -> Pi:  {"node":"A","ts":"2026-11-07 10:30:00","seq":12,"moisture":31.2,...,"valve":0}

#include <SPI.h>
#include <RF24.h>
#include <avr/wdt.h>
#include "packets.h"

const uint8_t PIN_NRF_CSN = 7, PIN_NRF_CE = 8;
const unsigned long COMMAND_EXPIRY_MS = 600000UL;   // drop an undelivered command after 10 min

RF24 radio(PIN_NRF_CE, PIN_NRF_CSN);
Command pending;
bool hasPending = false;
unsigned long pendingSinceMs = 0;

// ---------------------------------------------------------------- time
const uint8_t DAYS_IN_MONTH[] PROGMEM = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};

void printTime(uint32_t t) {                         // seconds since 2000-01-01, local time
  uint8_t s = t % 60; t /= 60;
  uint8_t mi = t % 60; t /= 60;
  uint8_t h = t % 24;
  uint16_t days = t / 24, y = 2000;
  for (;;) {
    uint16_t len = (y % 4 == 0) ? 366 : 365;
    if (days < len) break;
    days -= len; ++y;
  }
  uint8_t mo = 1;
  for (;; ++mo) {
    uint8_t len = pgm_read_byte(DAYS_IN_MONTH + mo - 1) + ((mo == 2 && y % 4 == 0) ? 1 : 0);
    if (days < len) break;
    days -= len;
  }
  char buf[26];
  snprintf(buf, sizeof(buf), "%04u-%02u-%02u %02u:%02u:%02u", y, mo, days + 1, h, mi, s);
  Serial.print(buf);
}

// ---------------------------------------------------------------- reading -> JSON
void printFixed(const __FlashStringHelper* key, int16_t x10, bool ok) {
  Serial.print(key);
  if (ok) Serial.print(x10 / 10.0, 1); else Serial.print(F("null"));
}

void printUint(const __FlashStringHelper* key, uint16_t v, bool ok) {
  Serial.print(key);
  if (ok) Serial.print(v); else Serial.print(F("null"));
}

void printReading(const Reading &r) {
  bool soil = r.flags & F_SOIL_OK, dhtOk = r.flags & F_DHT_OK, ir = r.flags & F_IR_OK;
  Serial.print(F("{\"node\":\"")); Serial.print((char)r.node); Serial.print('"');
  if (r.flags & F_RTC_OK) { Serial.print(F(",\"ts\":\"")); printTime(r.ts); Serial.print('"'); }
  Serial.print(F(",\"seq\":")); Serial.print(r.seq);
  printFixed(F(",\"moisture\":"), r.moisture_x10, soil);
  printFixed(F(",\"soil_temp\":"), r.soil_temp_x10, soil);
  printUint(F(",\"ec\":"), r.ec, soil);
  printFixed(F(",\"ph\":"), r.ph_x10, soil);
  printUint(F(",\"n\":"), r.n, soil);
  printUint(F(",\"p\":"), r.p, soil);
  printUint(F(",\"k\":"), r.k, soil);
  Serial.print(F(",\"rain\":")); Serial.print((r.flags & F_RAIN) ? 1 : 0);
  printFixed(F(",\"tank_cm\":"), (int16_t)r.tank_mm, ir);
  printFixed(F(",\"air_temp\":"), r.air_temp_x10, dhtOk);
  printUint(F(",\"air_rh\":"), r.air_rh, dhtOk);
  Serial.print(F(",\"valve\":")); Serial.print((r.flags & F_VALVE) ? 1 : 0);
  Serial.print(F(",\"sd_ok\":")); Serial.print((r.flags & F_SD_OK) ? 1 : 0);
  if (r.last_cmd) {
    char id[9];
    snprintf(id, sizeof(id), "%08lx", (unsigned long)r.last_cmd);
    Serial.print(F(",\"cmd_ack\":\"")); Serial.print(id); Serial.print('"');
  }
  Serial.println('}');
}

// ---------------------------------------------------------------- commands from the Pi
void loadAck() {
  if (hasPending) radio.writeAckPayload(1, &pending, sizeof(pending));
}

void handleCommandLine(char* line) {
  if (!strstr(line, "\"cmd\":\"valve\"")) return;
  char* m = strstr(line, "\"minutes\":");
  char* i = strstr(line, "\"id\":\"");
  if (!m || !i) return;
  float minutes = atof(m + 10);
  if (minutes <= 0 || minutes > 90) return;              // field node also enforces its own limit
  char idText[9];
  strncpy(idText, i + 6, 8);
  idText[8] = 0;
  pending.type = MSG_COMMAND;
  pending.node = 'A';
  pending.minutes_x10 = (uint16_t)(minutes * 10 + 0.5);
  pending.id = strtoul(idText, nullptr, 16);
  if (pending.id == 0) return;
  hasPending = true;
  pendingSinceMs = millis();
  radio.flush_tx();                                       // replace any older queued command
  loadAck();
}

void readPi() {
  static char buf[96];
  static uint8_t len = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (len) { buf[len] = 0; handleCommandLine(buf); }
      len = 0;
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = c;
    } else {
      len = 0;                                            // line too long: discard
    }
  }
}

// ---------------------------------------------------------------- setup and loop
void setup() {
  Serial.begin(115200);
  wdt_enable(WDTO_4S);
  if (!radio.begin()) {
    // Not JSON on purpose: the hub records it as a rejected line, which makes the fault visible
    Serial.println(F("gateway: NRF24L01 not found"));
  }
  radio.setChannel(RADIO_CHANNEL);
  radio.setDataRate(RF24_250KBPS);
  radio.setPALevel(RF24_PA_HIGH);
  radio.enableDynamicPayloads();
  radio.enableAckPayload();
  radio.openReadingPipe(1, (const uint8_t*)FIELD_ADDRESS);
  radio.startListening();
}

void loop() {
  wdt_reset();
  readPi();

  if (hasPending && millis() - pendingSinceMs > COMMAND_EXPIRY_MS) {
    hasPending = false;                                   // never deliver a stale command
    radio.flush_tx();
  }

  uint8_t pipe;
  while (radio.available(&pipe)) {
    uint8_t n = radio.getDynamicPayloadSize();
    if (n < 2 || n > 32) { radio.flush_rx(); break; }
    uint8_t buf[32];
    radio.read(buf, n);
    if (buf[0] == MSG_READING && n == sizeof(Reading)) {
      Reading r;
      memcpy(&r, buf, sizeof(r));
      if (hasPending && r.last_cmd == pending.id) {       // field node confirmed the command
        hasPending = false;
        radio.flush_tx();
      }
      printReading(r);
    }
    loadAck();                                            // re-arm for the next poll or reading
  }
}
