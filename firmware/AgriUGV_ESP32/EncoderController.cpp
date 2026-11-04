#include "EncoderController.h"
#include "config.h"
#include <esp_timer.h>

static volatile long leftTicks = 0;
static volatile long rightTicks = 0;
static volatile int64_t leftLastEdge = 0;
static volatile int64_t rightLastEdge = 0;

void IRAM_ATTR leftEncoderISR() {
  int64_t now = esp_timer_get_time();
  if (now - leftLastEdge >= ENCODER_DEBOUNCE_US) {
    leftLastEdge = now;
    leftTicks++;
  }
}

void IRAM_ATTR rightEncoderISR() {
  int64_t now = esp_timer_get_time();
  if (now - rightLastEdge >= ENCODER_DEBOUNCE_US) {
    rightLastEdge = now;
    rightTicks++;
  }
}

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
