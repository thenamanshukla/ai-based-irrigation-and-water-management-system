// TEST 7: I2C bus scan and 16x2 LCD
// Wiring: LCD backpack VCC 5V, GND, SDA -> A4, SCL -> A5 (the RTC can stay connected).
// Library: "LiquidCrystal I2C" by Frank de Brabander.
// Serial Monitor 9600 baud. First lists every device found on the I2C bus:
//   0x68 = DS3231 clock, 0x27 or 0x3F = LCD backpack, 0x57 = EEPROM on many DS3231 boards.
// Then writes to the LCD at the address it found and counts seconds.
// Blank LCD with backlight on: turn the small blue contrast screw on the back.
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

LiquidCrystal_I2C* lcd = nullptr;

bool present(uint8_t a) {
  Wire.beginTransmission(a);
  return Wire.endTransmission() == 0;
}

void setup() {
  Serial.begin(9600);
  Wire.begin();
  Serial.println(F("I2C scan:"));
  uint8_t count = 0;
  for (uint8_t a = 1; a < 127; ++a) {
    if (present(a)) {
      Serial.print(F("  found 0x")); if (a < 16) Serial.print('0'); Serial.print(a, HEX);
      if (a == 0x68) Serial.print(F("  DS3231 clock"));
      if (a == 0x27 || a == 0x3F) Serial.print(F("  LCD backpack"));
      if (a == 0x57) Serial.print(F("  EEPROM on the clock board"));
      Serial.println();
      ++count;
    }
  }
  if (!count) Serial.println(F("  nothing found: check SDA/SCL and power"));
  uint8_t addr = present(0x27) ? 0x27 : (present(0x3F) ? 0x3F : 0);
  if (!addr) { Serial.println(F("No LCD found at 0x27 or 0x3F")); return; }
  static LiquidCrystal_I2C l(addr, 16, 2);
  lcd = &l;
  lcd->init();
  lcd->backlight();
  lcd->print(F("LCD test OK"));
  Serial.print(F("LCD at 0x")); Serial.println(addr, HEX);
}

void loop() {
  if (!lcd) return;
  lcd->setCursor(0, 1);
  lcd->print(F("Seconds: "));
  lcd->print(millis() / 1000);
  delay(500);
}
