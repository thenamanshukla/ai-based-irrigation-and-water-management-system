// Field node (Arduino UNO A): reads sensors, logs to SD, shows status on the LCD,
// sends readings to the gateway, and drives the irrigation valve with its own fail safes.
//
// Libraries (Arduino IDE > Library Manager):
//   RF24 by TMRh20, LiquidCrystal I2C by Frank de Brabander, DHT sensor library by Adafruit
//   (SD, SPI, Wire and SoftwareSerial are built in)
//
// Pins (system document, Table 1):
//   D2/D3 MAX485 RO/DI, D6 MAX485 DE+RE, D4 DHT22, D5 relay, D7/D8 NRF CSN/CE,
//   D10 SD CS, D11-D13 SPI, A0 rain, A1 IR distance, A4/A5 I2C (RTC 0x68, LCD 0x27)

#include <SPI.h>
#include <Wire.h>
#include <SD.h>
#include <SoftwareSerial.h>
#include <RF24.h>
#include <LiquidCrystal_I2C.h>
#include <DHT.h>
#include <avr/wdt.h>
#include "packets.h"

// ===================================================================== settings
// Soil probe (confirm with tools/find_soil_registers.py on the Pi before field use)
const uint8_t  SOIL_ADDR = 1;
const long     SOIL_BAUD = 4800;
const uint16_t REG_MOIST = 0x0000, REG_TEMP = 0x0001, REG_EC = 0x0002, REG_PH = 0x0003,
               REG_N = 0x0004, REG_P = 0x0005, REG_K = 0x0006;

const unsigned long SEND_INTERVAL_MS = 300000UL;   // one reading every 5 minutes
const unsigned long POLL_INTERVAL_MS = 30000UL;    // ask the gateway for commands every 30 s
const unsigned long CHECK_INTERVAL_MS = 30000UL;   // fail safe check while the valve is open
const unsigned long HUB_TIMEOUT_MS = 1800000UL;    // close the valve if the hub is silent 30 min

const bool     RELAY_ACTIVE_HIGH = true;           // set false for active low relay boards
const int      RAIN_WET_BELOW = 500;               // A0 raw value; wet plate reads lower
const int16_t  SOIL_FULL_X10 = 300;                // 30.0 %: field capacity, valve closes
const uint16_t TANK_RESERVE_MM = 270;              // IR distance at the reserve level
const uint16_t MAX_VALVE_MIN = 90;

// Sharp GP2Y0A41SK0F (4 to 30 cm): d[cm] = IR_A * V^IR_B. Re-fit from your own tank table.
const float IR_A = 12.08, IR_B = -1.058;

// ===================================================================== pins
const uint8_t PIN_RS485_RX = 2, PIN_RS485_TX = 3, PIN_DHT = 4, PIN_RELAY = 5, PIN_RS485_EN = 6,
              PIN_NRF_CSN = 7, PIN_NRF_CE = 8, PIN_SD_CS = 10, PIN_RAIN = A0, PIN_IR = A1;
const uint8_t DS3231_ADDR = 0x68;

SoftwareSerial rs485(PIN_RS485_RX, PIN_RS485_TX);
RF24 radio(PIN_NRF_CE, PIN_NRF_CSN);
LiquidCrystal_I2C lcd(0x27, 16, 2);
DHT dht(PIN_DHT, DHT22);

Reading rd;
bool valveOpen = false, sdOk = false;
unsigned long valveStartMs = 0, valveMs = 0, lastSendMs = 0, lastPollMs = 0, lastCheckMs = 0, lastHubMs = 0;
uint32_t lastCmdId = 0;
const char* closeReason = "";

// ===================================================================== valve
void relay(bool on) {
  digitalWrite(PIN_RELAY, (on == RELAY_ACTIVE_HIGH) ? HIGH : LOW);
  valveOpen = on;
}

// Returns why the valve must stay closed, or nullptr if it may open
const char* failsafe() {
  if (rd.flags & F_RAIN) return "rain";
  if ((rd.flags & F_SOIL_OK) && rd.moisture_x10 >= SOIL_FULL_X10) return "soil wet";
  if (!(rd.flags & F_IR_OK)) return "no tank level";
  if (rd.tank_mm >= TANK_RESERVE_MM) return "tank low";
  if (millis() - lastHubMs > HUB_TIMEOUT_MS) return "hub silent";
  return nullptr;
}

void openValve(uint16_t minutes_x10) {
  if (minutes_x10 == 0 || minutes_x10 > MAX_VALVE_MIN * 10) { closeReason = "bad time"; return; }
  const char* why = failsafe();
  if (why) { closeReason = why; return; }
  valveMs = (unsigned long)minutes_x10 * 6000UL;          // minutes x10 -> ms
  valveStartMs = millis();
  relay(true);
  closeReason = "";
}

void checkValve() {
  if (!valveOpen) return;
  if (millis() - valveStartMs >= valveMs) { relay(false); closeReason = "done"; return; }
  const char* why = failsafe();
  if (why) { relay(false); closeReason = why; }
}

// ===================================================================== DS3231 (minimal)
uint8_t bcd2bin(uint8_t v) { return v - 6 * (v >> 4); }
uint8_t bin2bcd(uint8_t v) { return v + 6 * (v / 10); }
const uint8_t DAYS_IN_MONTH[] PROGMEM = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30};

uint32_t toSeconds(uint16_t y, uint8_t mo, uint8_t d, uint8_t h, uint8_t mi, uint8_t s) {
  if (y >= 2000) y -= 2000;
  uint16_t days = d;
  for (uint8_t i = 1; i < mo; ++i) days += pgm_read_byte(DAYS_IN_MONTH + i - 1);
  if (mo > 2 && y % 4 == 0) ++days;
  days += 365 * y + (y + 3) / 4 - 1;
  return ((days * 24UL + h) * 60 + mi) * 60 + s;
}

bool rtcRead(uint32_t &out) {
  Wire.beginTransmission(DS3231_ADDR);
  Wire.write((uint8_t)0);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom(DS3231_ADDR, (uint8_t)7) != 7) return false;
  uint8_t s = bcd2bin(Wire.read() & 0x7F), mi = bcd2bin(Wire.read()), h = bcd2bin(Wire.read() & 0x3F);
  Wire.read();                                            // day of week
  uint8_t d = bcd2bin(Wire.read()), mo = bcd2bin(Wire.read() & 0x1F);
  uint16_t y = bcd2bin(Wire.read()) + 2000;
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return false;
  out = toSeconds(y, mo, d, h, mi, s);
  return true;
}

bool rtcSet(uint16_t y, uint8_t mo, uint8_t d, uint8_t h, uint8_t mi, uint8_t s) {
  Wire.beginTransmission(DS3231_ADDR);
  Wire.write((uint8_t)0);
  Wire.write(bin2bcd(s)); Wire.write(bin2bcd(mi)); Wire.write(bin2bcd(h));
  Wire.write((uint8_t)1);
  Wire.write(bin2bcd(d)); Wire.write(bin2bcd(mo)); Wire.write(bin2bcd(y - 2000));
  if (Wire.endTransmission() != 0) return false;
  Wire.beginTransmission(DS3231_ADDR);                    // clear the oscillator stop flag
  Wire.write((uint8_t)0x0F); Wire.write((uint8_t)0x00);
  return Wire.endTransmission() == 0;
}

uint16_t num(const char* b, uint8_t pos, uint8_t len) {
  uint16_t v = 0;
  for (uint8_t i = 0; i < len; ++i) {
    char c = b[pos + i];
    if (c < '0' || c > '9') return 9999;                   // forces a validation failure
    v = v * 10 + (c - '0');
  }
  return v;
}

// Serial Monitor (9600 baud): "SET 2026-11-07 10:30:00" sets the RTC
void serialCommands() {
  static char buf[32];
  static uint8_t len = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      buf[len] = 0;
      // fixed layout: SET YYYY-MM-DD HH:MM:SS
      if (len == 23 && !strncmp(buf, "SET ", 4)) {
        uint16_t y = num(buf, 4, 4);
        uint8_t mo = num(buf, 9, 2), d = num(buf, 12, 2), h = num(buf, 15, 2), mi = num(buf, 18, 2), s = num(buf, 21, 2);
        bool ok = y >= 2024 && y < 2100 && mo >= 1 && mo <= 12 && d >= 1 && d <= 31 && h < 24 && mi < 60 && s < 60;
        Serial.println(ok && rtcSet(y, mo, d, h, mi, s) ? F("RTC set") : F("RTC set failed: use SET YYYY-MM-DD HH:MM:SS"));
      }
      len = 0;
    } else if (len < sizeof(buf) - 1) {
      buf[len++] = c;
    }
  }
}

// ===================================================================== Modbus RTU soil probe
uint16_t crc16(const uint8_t* b, uint8_t n) {
  uint16_t crc = 0xFFFF;
  for (uint8_t i = 0; i < n; ++i) {
    crc ^= b[i];
    for (uint8_t j = 0; j < 8; ++j) crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
  }
  return crc;
}

bool readRegister(uint16_t reg, uint16_t &val) {
  uint8_t q[8] = {SOIL_ADDR, 0x03, (uint8_t)(reg >> 8), (uint8_t)reg, 0, 1, 0, 0};
  uint16_t c = crc16(q, 6);
  q[6] = c & 0xFF; q[7] = c >> 8;
  while (rs485.available()) rs485.read();
  digitalWrite(PIN_RS485_EN, HIGH);
  rs485.write(q, 8);
  rs485.flush();
  digitalWrite(PIN_RS485_EN, LOW);
  uint8_t r[7], n = 0;
  unsigned long t0 = millis();
  while (n < 7 && millis() - t0 < 300) if (rs485.available()) r[n++] = rs485.read();
  if (n < 7 || r[0] != SOIL_ADDR || r[1] != 0x03 || r[2] != 2) return false;
  if (crc16(r, 5) != (uint16_t)(r[5] | (r[6] << 8))) return false;
  val = (r[3] << 8) | r[4];
  return true;
}

bool readSoil() {
  uint16_t m, t, ec, ph, n, p, k;
  bool ok = readRegister(REG_MOIST, m) && readRegister(REG_TEMP, t) && readRegister(REG_EC, ec) &&
            readRegister(REG_PH, ph) && readRegister(REG_N, n) && readRegister(REG_P, p) && readRegister(REG_K, k);
  if (!ok) return false;
  rd.moisture_x10 = (int16_t)m;            // probe reports 0.1 % units
  rd.soil_temp_x10 = (int16_t)t;           // 0.1 deg C, signed
  rd.ec = ec;
  rd.ph_x10 = (uint8_t)min(ph, (uint16_t)140);
  rd.n = n; rd.p = p; rd.k = k;
  return true;
}

// ===================================================================== other sensors
bool readTank() {
  long sum = 0;
  for (uint8_t i = 0; i < 25; ++i) { sum += analogRead(PIN_IR); delay(4); }
  float v = (sum / 25.0) * 5.0 / 1023.0;
  if (v < 0.25) return false;                              // out of range or unplugged
  float mm = 10.0 * IR_A * pow(v, IR_B);
  if (mm < 20 || mm > 600) return false;
  rd.tank_mm = (uint16_t)mm;
  return true;
}

void readQuick() {                                         // rain and tank: cheap, used by fail safes
  bool rain = analogRead(PIN_RAIN) < RAIN_WET_BELOW;
  rd.flags = (rd.flags & ~(F_RAIN | F_IR_OK)) | (rain ? F_RAIN : 0) | (readTank() ? F_IR_OK : 0);
}

void readAll() {
  wdt_reset();
  uint8_t f = 0;
  uint32_t ts;
  if (rtcRead(ts)) { rd.ts = ts; f |= F_RTC_OK; } else rd.ts = 0;
  if (readSoil()) f |= F_SOIL_OK;
  wdt_reset();
  float t = dht.readTemperature(), h = dht.readHumidity();
  if (!isnan(t) && !isnan(h)) {
    rd.air_temp_x10 = (int16_t)(t * 10);
    rd.air_rh = (uint8_t)constrain(h, 0, 100);
    f |= F_DHT_OK;
  }
  rd.flags = f | (sdOk ? F_SD_OK : 0);
  readQuick();
  if (valveOpen) rd.flags |= F_VALVE;
}

// ===================================================================== output
void logSd() {
  if (!sdOk) return;
  File fh = SD.open("LOG.CSV", FILE_WRITE);
  if (!fh) { sdOk = false; return; }
  fh.print(rd.ts); fh.print(','); fh.print(rd.seq); fh.print(',');
  fh.print(rd.moisture_x10 / 10.0, 1); fh.print(','); fh.print(rd.soil_temp_x10 / 10.0, 1); fh.print(',');
  fh.print(rd.ec); fh.print(','); fh.print(rd.ph_x10 / 10.0, 1); fh.print(',');
  fh.print(rd.n); fh.print(','); fh.print(rd.p); fh.print(','); fh.print(rd.k); fh.print(',');
  fh.print(rd.tank_mm); fh.print(','); fh.print(rd.air_temp_x10 / 10.0, 1); fh.print(',');
  fh.print(rd.air_rh); fh.print(','); fh.println(rd.flags, HEX);
  fh.close();
}

void lcdLine(uint8_t row, const char* text) {               // prints exactly 16 characters
  lcd.setCursor(0, row);
  uint8_t i = 0;
  for (; text[i] && i < 16; ++i) lcd.write(text[i]);
  for (; i < 16; ++i) lcd.write(' ');
}

void showLcd(bool hubOk) {
  char line[24], v[8];
  strcpy(line, "M");
  if (rd.flags & F_SOIL_OK) { dtostrf(rd.moisture_x10 / 10.0, 1, 1, v); strcat(line, v); strcat(line, "%"); }
  else strcat(line, "--");
  strcat(line, " T");
  if (rd.flags & F_IR_OK) { dtostrf(rd.tank_mm / 10.0, 1, 1, v); strcat(line, v); strcat(line, "cm"); }
  else strcat(line, "--");
  lcdLine(0, line);

  if (valveOpen) {
    unsigned long left = (valveMs - (millis() - valveStartMs)) / 60000UL + 1;
    strcpy(line, "V:ON ");
    ultoa(left, v, 10);
    strcat(line, v);
    strcat(line, "min");
  } else {
    strcpy(line, "V:OFF ");
    strncat(line, closeReason, 7);
  }
  uint8_t n = strlen(line);
  while (n < 13) line[n++] = ' ';
  line[n] = 0;
  strcat(line, hubOk ? "HUB" : "---");
  lcdLine(1, line);
}

// Sends a message; any valve command from the hub arrives in the acknowledgement
bool sendRadio(const void* msg, uint8_t len) {
  if (!radio.write(msg, len)) return false;
  lastHubMs = millis();
  while (radio.available()) {
    Command c;
    uint8_t n = radio.getDynamicPayloadSize();
    if (n == sizeof(Command)) {
      radio.read(&c, sizeof(c));
      if (c.type == MSG_COMMAND && c.id != lastCmdId) {       // ignore repeats of the same command
        lastCmdId = c.id;
        rd.last_cmd = c.id;
        readQuick();                                           // fresh rain and tank before opening
        openValve(c.minutes_x10);
      }
    } else {
      radio.flush_rx();
    }
  }
  return true;
}

int freeRam() {                                            // bytes between heap and stack
  extern int __heap_start, *__brkval;
  int v;
  return (int)&v - (__brkval == 0 ? (int)&__heap_start : (int)__brkval);
}

void sendReading() {
  rd.type = MSG_READING;
  rd.node = 'A';
  rd.seq++;
  if (valveOpen) rd.flags |= F_VALVE; else rd.flags &= ~F_VALVE;
  bool ok = sendRadio(&rd, sizeof(rd));
  Serial.print(F("seq ")); Serial.print(rd.seq);
  Serial.print(F(" moist ")); Serial.print(rd.moisture_x10 / 10.0, 1);
  Serial.print(F(" tank_mm ")); Serial.print(rd.tank_mm);
  Serial.print(F(" flags 0x")); Serial.print(rd.flags, HEX);
  Serial.print(F(" free_ram ")); Serial.print(freeRam());
  Serial.println(ok ? F(" sent") : F(" NOT ACKED"));
}

// ===================================================================== setup and loop
void setup() {
  pinMode(PIN_RELAY, OUTPUT);
  relay(false);                                            // valve shut first, always
  pinMode(PIN_RS485_EN, OUTPUT);
  digitalWrite(PIN_RS485_EN, LOW);
  pinMode(PIN_SD_CS, OUTPUT);
  Serial.begin(9600);
  rs485.begin(SOIL_BAUD);
  Wire.begin();
  dht.begin();
  lcd.init();
  lcd.backlight();
  lcd.print(F("Field node start"));
  sdOk = SD.begin(PIN_SD_CS);
  if (!radio.begin()) Serial.println(F("NRF24L01 not found"));
  radio.setChannel(RADIO_CHANNEL);
  radio.setDataRate(RF24_250KBPS);                         // longest range
  radio.setPALevel(RF24_PA_HIGH);
  radio.enableDynamicPayloads();
  radio.enableAckPayload();
  radio.setRetries(5, 15);
  radio.openWritingPipe((const uint8_t*)FIELD_ADDRESS);
  radio.stopListening();
  lastHubMs = millis();
  memset(&rd, 0, sizeof(rd));
  wdt_enable(WDTO_8S);                                     // reboot if anything hangs
  readAll();
  sendReading();
  lastSendMs = lastPollMs = lastCheckMs = millis();
}

void loop() {
  wdt_reset();
  serialCommands();
  unsigned long now = millis();

  if (valveOpen && now - lastCheckMs >= CHECK_INTERVAL_MS) {
    lastCheckMs = now;
    readQuick();
    uint16_t m;
    if (readRegister(REG_MOIST, m)) rd.moisture_x10 = (int16_t)m;
  }
  checkValve();

  if (now - lastSendMs >= SEND_INTERVAL_MS) {
    lastSendMs = now;
    readAll();
    checkValve();
    sendReading();
    logSd();
  } else if (now - lastPollMs >= POLL_INTERVAL_MS) {
    lastPollMs = now;
    Poll p = {MSG_POLL, 'A'};
    sendRadio(&p, sizeof(p));
  }

  static unsigned long lastLcd = 0;
  if (now - lastLcd >= 1000) {
    lastLcd = now;
    showLcd(millis() - lastHubMs < 600000UL);
  }
}
