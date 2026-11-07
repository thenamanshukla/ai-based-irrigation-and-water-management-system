// TEST 3: DHT22 air temperature and humidity
// Wiring: VCC 5V, GND, DATA -> D4 (bare 4 pin sensor: 10 k resistor between DATA and VCC).
// Library: "DHT sensor library" by Adafruit.
// Serial Monitor 9600 baud. Prints every 3 s (the DHT22 cannot be read faster than every 2 s).
// Expect: temperature close to a room thermometer (within about 0.5 C), humidity 30 to 90 %.
// Breathe on it: humidity jumps up, temperature rises slightly.
// "READ FAILED": check the DATA wire and pull up resistor.
#include <DHT.h>

DHT dht(4, DHT22);
float tMax = -100, tMin = 100;

void setup() {
  Serial.begin(9600);
  dht.begin();
  Serial.println(F("DHT22 test"));
  delay(2000);
}

void loop() {
  float t = dht.readTemperature(), h = dht.readHumidity();
  if (isnan(t) || isnan(h)) {
    Serial.println(F("READ FAILED"));
  } else {
    if (t > tMax) tMax = t;
    if (t < tMin) tMin = t;
    Serial.print(F("Air temperature ")); Serial.print(t, 1);
    Serial.print(F(" C   humidity ")); Serial.print(h, 0);
    Serial.print(F(" %   (since start: max ")); Serial.print(tMax, 1);
    Serial.print(F(" C, min ")); Serial.print(tMin, 1); Serial.println(F(" C)"));
  }
  delay(3000);
}
