// TEST 1: Relay and 12 V solenoid valve
// Wiring: relay VCC 5V, GND, IN -> D5. Battery + -> relay COM, relay NO -> valve +,
//         valve - -> battery -, 1N4007 across the valve (stripe to valve +).
// Serial Monitor 9600 baud, line ending "Newline". Type:
//   1  open the valve (closes by itself after 10 s for safety)
//   0  close the valve
// Expect: a click from the relay, the relay LED on, and water flowing while open.
// If the valve opens on "0" and closes on "1", your relay is active low: set ACTIVE_HIGH false.

const uint8_t PIN_RELAY = 5;
const bool ACTIVE_HIGH = true;
const unsigned long AUTO_OFF_MS = 10000;

bool open_ = false;
unsigned long openedAt = 0;

void setValve(bool on) {
  digitalWrite(PIN_RELAY, (on == ACTIVE_HIGH) ? HIGH : LOW);
  open_ = on;
  if (on) openedAt = millis();
  Serial.println(on ? F("VALVE OPEN  (auto close in 10 s)") : F("VALVE CLOSED"));
}

void setup() {
  pinMode(PIN_RELAY, OUTPUT);
  Serial.begin(9600);
  setValve(false);
  Serial.println(F("Relay test. Send 1 to open, 0 to close."));
}

void loop() {
  if (Serial.available()) {
    char c = Serial.read();
    if (c == '1') setValve(true);
    if (c == '0') setValve(false);
  }
  if (open_ && millis() - openedAt > AUTO_OFF_MS) setValve(false);
}
