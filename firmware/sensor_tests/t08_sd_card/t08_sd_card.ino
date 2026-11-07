// TEST 8: SD card module
// Wiring: VCC 5V, GND, MOSI -> D11, MISO -> D12, SCK -> D13, CS -> D10. Card formatted FAT32.
// Serial Monitor 9600 baud. Writes a line to TEST.TXT every 5 s, then reads the whole file back.
// Expect: "card OK", then the file growing by one line each time.
// Take the card out afterwards and open TEST.TXT on a computer to confirm.
// "card FAILED": reformat as FAT32 (cards up to 32 GB), check wiring, try another card.
#include <SPI.h>
#include <SD.h>

const uint8_t PIN_CS = 10;
unsigned int n = 0;

void setup() {
  Serial.begin(9600);
  pinMode(PIN_CS, OUTPUT);
  pinMode(7, OUTPUT); digitalWrite(7, HIGH);        // keep the radio (CSN D7) off the SPI bus
  Serial.println(SD.begin(PIN_CS) ? F("SD card OK") : F("SD card FAILED"));
}

void loop() {
  File f = SD.open("TEST.TXT", FILE_WRITE);
  if (!f) { Serial.println(F("could not open TEST.TXT for writing")); delay(5000); return; }
  f.print(F("line ")); f.print(++n); f.print(F(" at ")); f.print(millis() / 1000); f.println(F(" s"));
  f.close();
  f = SD.open("TEST.TXT");
  Serial.print(F("TEST.TXT now holds ")); Serial.print(f.size()); Serial.println(F(" bytes:"));
  while (f.available()) Serial.write(f.read());
  f.close();
  Serial.println(F("--"));
  delay(5000);
}
