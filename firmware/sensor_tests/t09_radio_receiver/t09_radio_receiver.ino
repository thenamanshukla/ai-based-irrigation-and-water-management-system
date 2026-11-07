// TEST 9b: NRF24L01 radio, RECEIVER (upload to Arduino B, the gateway)
// Wiring: same as the sender (VCC 3.3V ONLY, CE D8, CSN D7, SPI D11-D13, capacitor).
// Serial Monitor 9600 baud. Prints every counter received.
// Expect: numbers arriving once per second with no gaps. Gaps = lost messages.
#include <SPI.h>
#include <RF24.h>

RF24 radio(8, 7);
const uint8_t ADDRESS[6] = "IRRG1";
unsigned long last = 0, missed = 0;

void setup() {
  Serial.begin(9600);
  if (!radio.begin()) { Serial.println(F("radio NOT FOUND")); while (1) {} }
  radio.setChannel(90);
  radio.setDataRate(RF24_250KBPS);
  radio.setPALevel(RF24_PA_HIGH);
  radio.openReadingPipe(1, ADDRESS);
  radio.startListening();
  Serial.println(F("Receiver listening"));
}

void loop() {
  if (!radio.available()) return;
  unsigned long n;
  radio.read(&n, sizeof(n));
  if (last && n > last + 1) missed += n - last - 1;
  last = n;
  Serial.print(F("received ")); Serial.print(n);
  Serial.print(F("   missed so far ")); Serial.println(missed);
}
