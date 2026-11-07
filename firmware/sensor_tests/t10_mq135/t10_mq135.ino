// TEST 10 (optional): MQ 135 gas sensor
// Wiring: VCC 5V, GND, AO -> A2. The heater gets warm: this is normal.
// Serial Monitor 9600 baud. Prints the raw value every 2 s.
// Expect: the value drifts for the first minutes while the heater warms up; a brand new sensor
// needs about 24 hours of first time warm up before its readings settle.
// Hold an open bottle of ammonia based cleaner (or urea fertiliser solution) near it: the value rises.
// The raw value is relative, not ppm; use it only to compare "normal" with "ammonia present".

const uint8_t PIN_MQ = A2;
int baseline = -1;

void setup() {
  Serial.begin(9600);
  Serial.println(F("MQ-135 test (warming up)"));
}

void loop() {
  int v = analogRead(PIN_MQ);
  unsigned long s = millis() / 1000;
  if (s > 120 && baseline < 0) baseline = v;          // take clean air baseline after 2 minutes
  Serial.print(F("t=")); Serial.print(s); Serial.print(F(" s  raw ")); Serial.print(v);
  if (baseline >= 0) {
    Serial.print(F("  change from clean air ")); Serial.print(v - baseline);
  } else {
    Serial.print(F("  (warming up, baseline at 120 s)"));
  }
  Serial.println();
  delay(2000);
}
