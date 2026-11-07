// TEST 9a: NRF24L01 radio, SENDER (upload to Arduino A, the field node)
// Upload t09_radio_receiver to Arduino B at the same time.
// Wiring: VCC 3.3V ONLY (or 5 V into an adapter board), GND, CE -> D8, CSN -> D7,
//         MOSI -> D11, MISO -> D12, SCK -> D13. 10 uF capacitor across VCC and GND.
// Library: "RF24" by TMRh20.
// Serial Monitor 9600 baud. Sends a counter every second and reports if it was received.
// Expect: "delivered" almost every time with the boards a few metres apart.
// Then walk the sender towards the real field position: the delivered % shows real range.
// "radio NOT FOUND": wiring or power. Mostly "LOST": power (add the capacitor or an adapter), range.
#include <SPI.h>
#include <RF24.h>

RF24 radio(8, 7);
const uint8_t ADDRESS[6] = "IRRG1";
unsigned long sent = 0, ok = 0;

void setup() {
  Serial.begin(9600);
  pinMode(10, OUTPUT); digitalWrite(10, HIGH);      // keep the SD card off the SPI bus
  if (!radio.begin()) { Serial.println(F("radio NOT FOUND")); while (1) {} }
  radio.setChannel(90);                             // same settings as the real firmware
  radio.setDataRate(RF24_250KBPS);
  radio.setPALevel(RF24_PA_HIGH);
  radio.setRetries(5, 15);
  radio.openWritingPipe(ADDRESS);
  radio.stopListening();
  Serial.println(F("Sender ready"));
}

void loop() {
  ++sent;
  bool delivered = radio.write(&sent, sizeof(sent));
  if (delivered) ++ok;
  Serial.print(F("message ")); Serial.print(sent);
  Serial.print(delivered ? F("  delivered") : F("  LOST"));
  Serial.print(F("   success ")); Serial.print(100.0 * ok / sent, 0); Serial.println('%');
  delay(1000);
}
