// TEST 5: IR distance sensor for tank level (Sharp GP2Y0A41SK0F, 4 to 30 cm)
// Wiring: red VCC 5V, black GND, yellow Vout -> A1. Mount on the tank lid facing straight down.
// Serial Monitor 9600 baud. Prints every second: raw value, voltage, distance and water depth.
// Expect: hold your hand 10 cm away -> about 10 cm. Distance falls as the water rises.
// The sensor cannot read closer than about 4 cm: keep it at least 5 cm above the highest water.
//
// Calibration (do this once with your real tank):
//   1. Set SENSOR_TO_FLOOR_CM to the distance from the sensor to the empty tank floor.
//   2. Fill in steps (for example every 2 litres) and write down "distance" at each step.
//   3. Compare with a ruler. If the error is more than 1 cm, re fit IR_A and IR_B from your table
//      (the software lead can do this from your numbers).

const uint8_t PIN_IR = A1;
const float IR_A = 12.08, IR_B = -1.058;     // d[cm] = IR_A * V^IR_B
const float SENSOR_TO_FLOOR_CM = 30.0;

void setup() {
  Serial.begin(9600);
  Serial.println(F("IR tank level test"));
}

void loop() {
  long sum = 0;
  for (uint8_t i = 0; i < 25; ++i) { sum += analogRead(PIN_IR); delay(4); }
  float raw = sum / 25.0;
  float v = raw * 5.0 / 1023.0;
  Serial.print(F("raw ")); Serial.print(raw, 0);
  Serial.print(F("  volts ")); Serial.print(v, 2);
  if (v < 0.25) {
    Serial.println(F("  -> OUT OF RANGE (too far, or sensor unplugged)"));
  } else {
    float cm = IR_A * pow(v, IR_B);
    Serial.print(F("  distance ")); Serial.print(cm, 1); Serial.print(F(" cm"));
    Serial.print(F("  water depth ")); Serial.print(max(0.0, SENSOR_TO_FLOOR_CM - cm), 1);
    Serial.print(F(" cm"));
    if (cm < 4) Serial.print(F("  (TOO CLOSE: reading not reliable)"));
    Serial.println();
  }
  delay(1000);
}
