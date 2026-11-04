#ifndef SENSOR_CONTROLLER_H
#define SENSOR_CONTROLLER_H

#include <Arduino.h>

struct SensorData {
  float humidity;
  float temperature;
};

void initSensors();
void updateSensors();
SensorData getSensorData();

#endif
