// TEST 2: 7 in 1 soil probe over RS485 (MAX485 module)
// Wiring: probe A -> MAX485 A, probe B -> MAX485 B, probe VCC/GND as its label says (5 V or 12 V).
//         MAX485 VCC 5V, GND, RO -> D2, DI -> D3, DE and RE joined -> D6.
// Serial Monitor 9600 baud. Prints all 7 values every 3 s.
// Expect (dry room soil): moisture 5 to 25 %, temperature near room temperature,
//         pH 5 to 8, EC 50 to 1500 uS/cm. Pour water near the probe: moisture should rise.
// "NO REPLY": swap A and B, check probe power, try BAUD 9600, or run tools/find_soil_registers.py.
// Values clearly wrong: your probe uses a different register map; update the REG_ list.
#include <SoftwareSerial.h>

const uint8_t ADDR = 1;
const long BAUD = 4800;
const uint8_t PIN_RX = 2, PIN_TX = 3, PIN_EN = 6;
const uint16_t REG[] = {0x0000, 0x0001, 0x0002, 0x0003, 0x0004, 0x0005, 0x0006};
const char* const NAME[] = {"Moisture", "Temperature", "EC", "pH", "Nitrogen N", "Phosphorus P", "Potassium K"};
const char* const UNIT[] = {" %", " C", " uS/cm", "", " mg/kg", " mg/kg", " mg/kg"};
const bool TENTHS[] = {true, true, false, true, false, false, false};

SoftwareSerial rs485(PIN_RX, PIN_TX);

uint16_t crc16(const uint8_t* b, uint8_t n) {
  uint16_t crc = 0xFFFF;
  for (uint8_t i = 0; i < n; ++i) {
    crc ^= b[i];
    for (uint8_t j = 0; j < 8; ++j) crc = (crc & 1) ? (crc >> 1) ^ 0xA001 : crc >> 1;
  }
  return crc;
}

bool readRegister(uint16_t reg, uint16_t &val) {
  uint8_t q[8] = {ADDR, 0x03, (uint8_t)(reg >> 8), (uint8_t)reg, 0, 1, 0, 0};
  uint16_t c = crc16(q, 6);
  q[6] = c & 0xFF; q[7] = c >> 8;
  while (rs485.available()) rs485.read();
  digitalWrite(PIN_EN, HIGH);
  rs485.write(q, 8);
  rs485.flush();
  digitalWrite(PIN_EN, LOW);
  uint8_t r[7], n = 0;
  unsigned long t0 = millis();
  while (n < 7 && millis() - t0 < 300) if (rs485.available()) r[n++] = rs485.read();
  if (n < 7 || r[0] != ADDR || r[1] != 0x03 || r[2] != 2) return false;
  if (crc16(r, 5) != (uint16_t)(r[5] | (r[6] << 8))) return false;
  val = (r[3] << 8) | r[4];
  return true;
}

void setup() {
  pinMode(PIN_EN, OUTPUT);
  digitalWrite(PIN_EN, LOW);
  Serial.begin(9600);
  rs485.begin(BAUD);
  Serial.println(F("Soil probe test"));
}

void loop() {
  Serial.println(F("------------------------------"));
  for (uint8_t i = 0; i < 7; ++i) {
    uint16_t v;
    Serial.print(NAME[i]);
    Serial.print(F(": "));
    if (readRegister(REG[i], v)) {
      if (TENTHS[i]) Serial.print((int16_t)v / 10.0, 1); else Serial.print(v);
      Serial.print(UNIT[i]);
      Serial.print(F("   (raw ")); Serial.print(v); Serial.println(')');
    } else {
      Serial.println(F("NO REPLY"));
    }
    delay(50);
  }
  delay(3000);
}
