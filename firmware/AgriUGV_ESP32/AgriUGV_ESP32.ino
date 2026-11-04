#include <Arduino.h>
#include "config.h"
#include "MotorController.h"
#include "EncoderController.h"
#include "MovementController.h"
#include "SensorController.h"
#include "Communication.h"

void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println();
  Serial.println("===== AGRI UGV ESP32 =====");

  initMotors();
  initEncoders();
  initMovement();
  initSensors();
  updateSensors();
  initCommunication();

  stopMotors();
  Serial.println("UGV controller ready");
}

void loop() {
  handleCommunication();
  updateSensors();
  updateMovement();
  delay(2);
}
