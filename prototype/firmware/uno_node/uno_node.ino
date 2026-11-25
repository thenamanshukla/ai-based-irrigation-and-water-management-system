// Field controller for the prototype: one Arduino UNO, plugged into the Raspberry Pi 5 by USB.
//
// Every SEND_MS it reads all sensors and prints ONE JSON line on USB serial (115200 baud) for the
// Pi hub, writes the same line to the SD card, and forwards it to the ESP32 (Wi-Fi module).
// The Pi decides when to water and sends {"cmd":"valve","minutes":45,"id":"ab12cd34"}.
// The UNO enforces the safety rules itself: it never opens the valve on wet soil, closes it at the
// stop level, limits the run time, and waters on its own (35 % start, 40 % stop) only if the Pi is silent.
//
// Wiring (team pin list):
//   7 in 1 soil probe via MAX485: RO -> D9, RE -> D8, DE -> D7, DI -> D6   (Modbus RTU, 4800 baud)
//   DHT11 data -> A0          IR obstacle sensor OUT -> A1      Resistive soil sensor AO -> A2
//   MQ135 AO -> A3            DS3231 RTC SDA/SCL -> A4/A5       ESP32: UNO D10 -> ESP32 RX, ESP32 TX -> UNO D11
//   Relay IN -> PIN_RELAY     SD card: CS -> PIN_SD_CS, MOSI D11, MISO D12, SCK D13
// Note: the SD card uses D11 to D13 (SPI). D11 is also the ESP32 line, so the sketch turns SD logging
// off while the ESP32 sits on D10/D11. Move the ESP32 to D2/D3 (change PIN_ESP_*) to use both.
// ESP32 pins are 3.3 V: put a divider (1 k / 2 k) on the UNO D10 -> ESP32 RX line.

#include <SoftwareSerial.h>
#include <Wire.h>
#include <SPI.h>
#include <SD.h>
#include <DHT.h>
#include <avr/wdt.h>

// ============================================================== pins
const uint8_t PIN_RS485_RO = 9, PIN_RS485_RE = 8, PIN_RS485_DE = 7, PIN_RS485_DI = 6;
const uint8_t PIN_DHT = A0, PIN_IR = A1, PIN_SOIL2 = A2, PIN_MQ135 = A3;
const uint8_t PIN_ESP_TX = 10, PIN_ESP_RX = 11;        // UNO side: D10 sends to ESP32, D11 receives
const uint8_t PIN_RELAY = 5;                           // set to the relay pin used on the board
const uint8_t PIN_SD_CS = 4;                           // set to the SD module CS pin

// ============================================================== settings
const bool RELAY_ACTIVE_HIGH = false;                  // most blue relay boards switch on LOW
const bool IR_ACTIVE_LOW = true;                       // obstacle modules pull OUT low on detection
const unsigned long SEND_MS = 30000UL;                 // one reading every 30 s
const unsigned long PI_TIMEOUT_MS = 1800000UL;         // Pi silent for 30 min -> local control
const uint16_t START_X10 = 350, STOP_X10 = 400;        // 35.0 % start, 40.0 % stop (tomato prototype)
const uint16_t LOCAL_RUN_MIN = 45;                     // local watering run (about 1000 ml on the rig)
const uint16_t MAX_RUN_MIN = 90;
const int SOIL2_DRY = 1000, SOIL2_WET = 400;           // A2 raw in dry air and in water; calibrate

const uint8_t SOIL_ADDR = 1;
const long SOIL_BAUD = 4800;

// ============================================================== state
SoftwareSerial rs485(PIN_RS485_RO, PIN_RS485_DI);
SoftwareSerial esp(PIN_ESP_RX, PIN_ESP_TX);
DHT dht(PIN_DHT, DHT11);

bool valveOpen = false, sdOk = false, soilOk = false, localMode = false;
unsigned long valveStart = 0, valveRunMs = 0, lastSend = 0, lastPi = 0;
int16_t moist = 0, soilT = 0, moist2 = 0;            // x10; moist2 = resistive sensor
uint16_t ec = 0, ph = 0, nN = 0, nP = 0, nK = 0;      // ph x10
char lastReason[12] = "";
File logFile;

// ============================================================== output: one line to the Pi, the ESP32 and the SD card at once
class Tee : public Print {
 public:
  size_t write(uint8_t c) override {
    Serial.write(c);
    esp.write(c);
    if (logFile) logFile.write(c);
    return 1;
  }
} out;

void putX10(long v) {                                  // 123 -> "12.3", -5 -> "-0.5"
  if (v < 0) { out.print('-'); v = -v; }
  out.print(v / 10); out.print('.'); out.print(v % 10);
}
void key(const __FlashStringHelper* k) { out.print(F(",\"")); out.print(k); out.print(F("\":")); }

// ============================================================== relay
void relay(bool on) {
  digitalWrite(PIN_RELAY, on == RELAY_ACTIVE_HIGH ? HIGH : LOW);
  valveOpen = on;
}

int16_t soilNow() { return soilOk ? moist : moist2; }  // 7 in 1 probe; resistive sensor if the probe fails

const char* blockReason() {                            // why the valve must not run, or nullptr
  if (soilNow() >= (int16_t)STOP_X10) return "soil wet";
  return nullptr;
}

const char* openValve(uint16_t minutes) {
  if (minutes == 0) { relay(false); return "stopped"; }
  if (minutes > MAX_RUN_MIN) return "too long";
  const char* why = blockReason();
  if (why) return why;
  valveRunMs = (unsigned long)minutes * 60000UL;
  valveStart = millis();
  relay(true);
  return "";
}

void checkValve() {
  if (valveOpen) {
    const char* why = blockReason();
    if (millis() - valveStart >= valveRunMs) { relay(false); strcpy(lastReason, "done"); }
    else if (why) { relay(false); strncpy(lastReason, why, sizeof(lastReason) - 1); }
  }
  localMode = millis() - lastPi > PI_TIMEOUT_MS;       // Pi silent: follow the 35/40 rule locally
  if (localMode && !valveOpen && soilNow() < (int16_t)START_X10) {
    if (!openValve(LOCAL_RUN_MIN)[0]) strcpy(lastReason, "local");
  }
}

// ============================================================== DS3231 RTC
uint8_t bcd2bin(uint8_t v) { return v - 6 * (v >> 4); }
uint8_t bin2bcd(uint8_t v) { return v + 6 * (v / 10); }

bool rtcString(char* out) {                            // "YYYY-MM-DD HH:MM:SS"
  Wire.beginTransmission(0x68);
  Wire.write((uint8_t)0);
  if (Wire.endTransmission() != 0 || Wire.requestFrom((uint8_t)0x68, (uint8_t)7) != 7) return false;
  uint8_t s = bcd2bin(Wire.read() & 0x7F), mi = bcd2bin(Wire.read()), h = bcd2bin(Wire.read() & 0x3F);
  Wire.read();
  uint8_t d = bcd2bin(Wire.read()), mo = bcd2bin(Wire.read() & 0x1F), y = bcd2bin(Wire.read());
  if (mo < 1 || mo > 12 || d < 1 || d > 31) return false;
  uint8_t v[6] = {y, mo, d, h, mi, s};
  const char sep[6] = {'-', '-', ' ', ':', ':', 0};
  out[0] = '2'; out[1] = '0';
  for (uint8_t i = 0; i < 6; ++i) {
    out[2 + i * 3] = '0' + v[i] / 10; out[3 + i * 3] = '0' + v[i] % 10; out[4 + i * 3] = sep[i];
  }
  return true;
}

uint8_t two(const char* p) { return (p[0] - '0') * 10 + (p[1] - '0'); }

bool rtcSet(const char* t) {                           // t = "YYYY-MM-DD HH:MM:SS"
  Wire.beginTransmission(0x68);
  Wire.write((uint8_t)0);
  Wire.write(bin2bcd(two(t + 17))); Wire.write(bin2bcd(two(t + 14))); Wire.write(bin2bcd(two(t + 11)));
  Wire.write((uint8_t)1);
  Wire.write(bin2bcd(two(t + 8))); Wire.write(bin2bcd(two(t + 5))); Wire.write(bin2bcd(two(t + 2)));
  return Wire.endTransmission() == 0;
}

// ============================================================== 7 in 1 soil probe (Modbus RTU)
uint16_t crc16(const uint8_t* b, uint8_t n) {
  uint16_t crc = 0xFFFF;
  for (uint8_t i = 0; i < n; ++i) {
    crc ^= b[i];
    for (uint8_t j = 0; j < 8; ++j) crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
  }
  return crc;
}

void rs485Transmit(bool tx) { digitalWrite(PIN_RS485_DE, tx); digitalWrite(PIN_RS485_RE, tx); }

bool readRegs(uint16_t* out, uint8_t count) {          // registers 0x0000.. in one request
  uint8_t q[8] = {SOIL_ADDR, 0x03, 0, 0, 0, count, 0, 0};
  uint16_t c = crc16(q, 6);
  q[6] = c & 0xFF; q[7] = c >> 8;
  rs485.listen();
  while (rs485.available()) rs485.read();
  rs485Transmit(true);
  rs485.write(q, 8);
  rs485.flush();
  rs485Transmit(false);
  uint8_t r[5 + 2 * 7], want = 5 + 2 * count, n = 0;
  unsigned long t0 = millis();
  while (n < want && millis() - t0 < 500) if (rs485.available()) r[n++] = rs485.read();
  if (n < want || r[0] != SOIL_ADDR || r[1] != 0x03 || r[2] != 2 * count) return false;
  if (crc16(r, want - 2) != (uint16_t)(r[want - 2] | (r[want - 1] << 8))) return false;
  for (uint8_t i = 0; i < count; ++i) out[i] = (r[3 + 2 * i] << 8) | r[4 + 2 * i];
  return true;
}

void readSoil() {
  uint16_t v[7];
  soilOk = readRegs(v, 7);
  if (!soilOk) return;
  moist = (int16_t)v[0]; soilT = (int16_t)v[1]; ec = v[2]; ph = v[3]; nN = v[4]; nP = v[5]; nK = v[6];
}

int avgAnalog(uint8_t pin) {
  long s = 0;
  for (uint8_t i = 0; i < 16; ++i) { s += analogRead(pin); delay(2); }
  return s / 16;
}

// ============================================================== one reading
void buildLine() {
  char ts[20] = {0};                                   // read everything first, then print
  bool haveTs = rtcString(ts);
  readSoil();
  long m2 = (long)(SOIL2_DRY - avgAnalog(PIN_SOIL2)) * 1000L / (SOIL2_DRY - SOIL2_WET);
  moist2 = (int16_t)constrain(m2, 0L, 1000L);
  float t = dht.readTemperature(), h = dht.readHumidity();
  int mq = avgAnalog(PIN_MQ135);
  bool ir = digitalRead(PIN_IR) == (IR_ACTIVE_LOW ? LOW : HIGH);

  out.print(F("{\"node\":\"UNO\""));
  if (haveTs) { key(F("ts")); out.print('"'); out.print(ts); out.print('"'); }
  key(F("moisture")); if (soilOk) putX10(moist); else out.print(F("null"));
  if (soilOk) {
    key(F("soil_temp")); putX10(soilT); key(F("ec")); out.print(ec); key(F("ph")); putX10(ph);
    key(F("n")); out.print(nN); key(F("p")); out.print(nP); key(F("k")); out.print(nK);
  }
  key(F("moisture2")); putX10(moist2);
  key(F("air_temp")); if (t == t) putX10(lround(t * 10)); else out.print(F("null"));
  key(F("air_rh")); if (h == h) putX10(lround(h * 10)); else out.print(F("null"));
  key(F("mq135")); out.print(mq);
  key(F("ir_object")); out.print(ir);
  key(F("valve")); out.print(valveOpen);
  key(F("mode")); if (localMode) out.print(F("\"local\"")); else out.print(F("\"pi\""));
  key(F("sd")); out.print(sdOk);
  out.print('}');
}

void sendReading() {
  wdt_reset();
  if (sdOk) {
    logFile = SD.open("LOG.TXT", FILE_WRITE);
    if (!logFile) sdOk = false;
  }
  buildLine();
  out.println();
  if (logFile) logFile.close();
  wdt_reset();
}

// ============================================================== commands from the Pi
char cmd[72];
uint8_t cmdLen = 0;

void ack(const char* id, const char* result) {
  Serial.print(F("{\"type\":\"ack\",\"id\":\"")); Serial.print(id);
  Serial.print(F("\",\"ok\":")); Serial.print(result[0] ? 0 : 1);
  Serial.print(F(",\"reason\":\"")); Serial.print(result); Serial.println(F("\"}"));
}

void handleCommand(char* c) {
  lastPi = millis();
  if (strstr(c, "\"cmd\":\"ping\"")) return;
  char* t = strstr(c, "\"t\":\"");
  if (strstr(c, "\"cmd\":\"time\"") && t && strlen(t + 5) >= 19) { rtcSet(t + 5); return; }
  if (!strstr(c, "\"cmd\":\"valve\"")) return;
  char id[9] = "";
  char* i = strstr(c, "\"id\":\"");
  if (i) { strncpy(id, i + 6, 8); id[8] = 0; char* q = strchr(id, '"'); if (q) *q = 0; }
  char* m = strstr(c, "\"minutes\":");
  if (!m) { ack(id, "no minutes"); return; }
  uint16_t minutes = (uint16_t)(atof(m + 10) + 0.5);
  const char* r = openValve(minutes);
  if (strcmp(r, "stopped") == 0) r = "";
  ack(id, r);
}

void readCommands() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      if (cmdLen) { cmd[cmdLen] = 0; handleCommand(cmd); cmdLen = 0; }
    } else if (cmdLen < sizeof(cmd) - 1) {
      cmd[cmdLen++] = ch;
    }
  }
}

// ============================================================== main
void setup() {
  relay(false);
  pinMode(PIN_RELAY, OUTPUT);
  relay(false);
  pinMode(PIN_RS485_DE, OUTPUT); pinMode(PIN_RS485_RE, OUTPUT); rs485Transmit(false);
  pinMode(PIN_IR, INPUT);
  Serial.begin(115200);
  esp.begin(9600);
  rs485.begin(SOIL_BAUD);
  rs485.listen();
  Wire.begin();
  dht.begin();
  bool spiClash = PIN_ESP_RX >= 11 && PIN_ESP_RX <= 13;
  sdOk = !spiClash && SD.begin(PIN_SD_CS);
  Serial.print(F("{\"type\":\"boot\",\"sd\":")); Serial.print(sdOk);
  Serial.println(spiClash ? F(",\"note\":\"SD off: ESP32 uses SPI pin\"}") : F("}"));
  lastPi = millis();
  wdt_enable(WDTO_8S);
  sendReading();
  lastSend = millis();
}

void loop() {
  wdt_reset();
  readCommands();
  if (millis() - lastSend >= SEND_MS) {
    lastSend = millis();
    sendReading();
  }
  checkValve();
}
