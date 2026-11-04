#include "SensorController.h"
#include "config.h"
#include <DHT.h>
#include <math.h>

static DHT dht(DHT_PIN, DHT22);
static SensorData latest = {NAN, NAN};
static unsigned long lastDhtRead = 0;
static bool dhtHasRead = false;
static int failures = 0;

void initSensors() {
  dht.begin();
}

void updateSensors() {
  unsigned long now = millis();

  // DHT22 should not be sampled more frequently than about every 2 seconds.
  if (!dhtHasRead || now - lastDhtRead >= SENSOR_INTERVAL_MS) {
    float h = dht.readHumidity();
    float t = dht.readTemperature();

    if (isnan(h) || isnan(t)) {
      // An old value must not pass as a current reading once the sensor has stopped working.
      if (++failures >= SENSOR_MAX_FAILURES) latest = {NAN, NAN};
    } else {
      failures = 0;
      latest = {h, t};
    }

    lastDhtRead = now;
    dhtHasRead = true;
  }
}

SensorData getSensorData() {
  return latest;
}
