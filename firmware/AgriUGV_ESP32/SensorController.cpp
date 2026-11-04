#include "SensorController.h"
#include "config.h"
#include <DHT.h>
#include <math.h>

static DHT dht(DHT_PIN, DHT22);
static SensorData latest = {NAN, NAN};
static unsigned long lastDhtRead = 0;
static bool dhtHasRead = false;

void initSensors() {
  dht.begin();
}

void updateSensors() {
  unsigned long now = millis();

  // DHT22 should not be sampled more frequently than about every 2 seconds.
  if (!dhtHasRead || now - lastDhtRead >= SENSOR_INTERVAL_MS) {
    float h = dht.readHumidity();
    float t = dht.readTemperature();

    if (!isnan(h)) latest.humidity = h;
    if (!isnan(t)) latest.temperature = t;

    lastDhtRead = now;
    dhtHasRead = true;
  }
}

SensorData getSensorData() {
  return latest;
}
