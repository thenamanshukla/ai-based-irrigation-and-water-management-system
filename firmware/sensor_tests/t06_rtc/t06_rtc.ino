// TEST 6: DS3231 real time clock
// Wiring: VCC 5V, GND, SDA -> A4, SCL -> A5. Fit the coin cell so it keeps time without power.
// Serial Monitor 9600 baud, line ending "Newline". Prints the time every second.
// Set the time by sending:  SET 2026-11-07 10:30:00
// Expect: seconds tick once per second. Unplug the Arduino for a minute, plug back in:
// the time should still be correct (the coin cell kept it running).
// "RTC NOT FOUND": check SDA/SCL wiring. "CLOCK STOPPED": set the time, check the coin cell.
#include <Wire.h>

const uint8_t ADDR = 0x68;

uint8_t bcd2bin(uint8_t v) { return v - 6 * (v >> 4); }
uint8_t bin2bcd(uint8_t v) { return v + 6 * (v / 10); }

uint16_t num(const char* b, uint8_t pos, uint8_t len) {
  uint16_t v = 0;
  for (uint8_t i = 0; i < len; ++i) {
    char c = b[pos + i];
    if (c < '0' || c > '9') return 9999;
    v = v * 10 + (c - '0');
  }
  return v;
}

void setTime(uint16_t y, uint8_t mo, uint8_t d, uint8_t h, uint8_t mi, uint8_t s) {
  Wire.beginTransmission(ADDR);
  Wire.write((uint8_t)0);
  Wire.write(bin2bcd(s)); Wire.write(bin2bcd(mi)); Wire.write(bin2bcd(h)); Wire.write((uint8_t)1);
  Wire.write(bin2bcd(d)); Wire.write(bin2bcd(mo)); Wire.write(bin2bcd(y - 2000));
  Wire.endTransmission();
  Wire.beginTransmission(ADDR);
  Wire.write((uint8_t)0x0F); Wire.write((uint8_t)0x00);   // clear oscillator stop flag
  Wire.endTransmission();
  Serial.println(F("Time set"));
}

void print2(uint8_t v) { if (v < 10) Serial.print('0'); Serial.print(v); }

void setup() {
  Serial.begin(9600);
  Wire.begin();
  Serial.println(F("RTC test. Send: SET YYYY-MM-DD HH:MM:SS"));
}

void loop() {
  static char buf[32];
  static uint8_t len = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      buf[len] = 0;
      if (len == 23 && !strncmp(buf, "SET ", 4)) {
        uint16_t y = num(buf, 4, 4);
        uint8_t mo = num(buf, 9, 2), d = num(buf, 12, 2), h = num(buf, 15, 2), mi = num(buf, 18, 2), s = num(buf, 21, 2);
        if (y >= 2024 && y < 2100 && mo && mo <= 12 && d && d <= 31 && h < 24 && mi < 60 && s < 60) setTime(y, mo, d, h, mi, s);
        else Serial.println(F("Bad format. Use: SET 2026-11-07 10:30:00"));
      }
      len = 0;
    } else if (len < sizeof(buf) - 1) buf[len++] = c;
  }

  static unsigned long last = 0;
  if (millis() - last < 1000) return;
  last = millis();
  Wire.beginTransmission(ADDR);
  Wire.write((uint8_t)0);
  if (Wire.endTransmission() != 0 || Wire.requestFrom(ADDR, (uint8_t)7) != 7) {
    Serial.println(F("RTC NOT FOUND"));
    return;
  }
  uint8_t s = bcd2bin(Wire.read() & 0x7F), mi = bcd2bin(Wire.read()), h = bcd2bin(Wire.read() & 0x3F);
  Wire.read();
  uint8_t d = bcd2bin(Wire.read()), mo = bcd2bin(Wire.read() & 0x1F), y = bcd2bin(Wire.read());
  Wire.beginTransmission(ADDR);
  Wire.write((uint8_t)0x0F);
  Wire.endTransmission();
  Wire.requestFrom(ADDR, (uint8_t)1);
  bool stopped = Wire.read() & 0x80;
  Serial.print(F("20")); print2(y); Serial.print('-'); print2(mo); Serial.print('-'); print2(d);
  Serial.print(' '); print2(h); Serial.print(':'); print2(mi); Serial.print(':'); print2(s);
  Serial.println(stopped ? F("   CLOCK STOPPED at some point: set the time") : F(""));
}
