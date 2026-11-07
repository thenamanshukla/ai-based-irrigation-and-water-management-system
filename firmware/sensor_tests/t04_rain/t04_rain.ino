// TEST 4: Rain sensor plate and module
// Wiring: plate -> module (2 wires), module VCC 5V, GND, AO -> A0.
// Serial Monitor 9600 baud. Prints the raw value (0 to 1023) every second.
// Expect: dry plate about 900 to 1023. Drip water on it: the value falls, often below 500.
// Calibrate: note the dry value and the value with a few drops; set WET_BELOW halfway between.
// Copy that number into RAIN_WET_BELOW in field_node.ino.

const uint8_t PIN_RAIN = A0;
const int WET_BELOW = 500;

void setup() {
  Serial.begin(9600);
  Serial.println(F("Rain sensor test"));
}

void loop() {
  int v = analogRead(PIN_RAIN);
  Serial.print(F("Rain raw ")); Serial.print(v);
  Serial.print(F("   -> ")); Serial.print(v < WET_BELOW ? F("WET (rain)") : F("dry"));
  Serial.print(F("   ["));
  for (int i = 0; i < 20; ++i) Serial.print(i < (1023 - v) / 51 ? '#' : '.');
  Serial.println(F("] wetness"));
  delay(1000);
}
