#include "EncoderController.h"
#include "config.h"

static volatile long leftTicks = 0;
static volatile long rightTicks = 0;

void IRAM_ATTR leftEncoderISR() { leftTicks++; }
void IRAM_ATTR rightEncoderISR() { rightTicks++; }

void initEncoders() {
  // GPIO 34 and 35 have no internal pull-ups on classic ESP32 boards.
  // Add external pull-ups to 3.3V if the encoder output is open-collector.
  pinMode(LEFT_ENCODER_PIN, INPUT);
  pinMode(RIGHT_ENCODER_PIN, INPUT);
  attachInterrupt(digitalPinToInterrupt(LEFT_ENCODER_PIN), leftEncoderISR, RISING);
  attachInterrupt(digitalPinToInterrupt(RIGHT_ENCODER_PIN), rightEncoderISR, RISING);
}

void resetEncoders() {
  noInterrupts();
  leftTicks = 0;
  rightTicks = 0;
  interrupts();
}

long getLeftTicks() {
  noInterrupts();
  long value = leftTicks;
  interrupts();
  return value;
}

long getRightTicks() {
  noInterrupts();
  long value = rightTicks;
  interrupts();
  return value;
}
