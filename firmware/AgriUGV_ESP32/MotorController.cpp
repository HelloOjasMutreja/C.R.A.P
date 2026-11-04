#include "MotorController.h"
#include "config.h"

static void setOneMotor(int speed, int enablePin, int inA, int inB, bool inverted) {
  speed = constrain(speed, -PWM_MAX, PWM_MAX);
  if (inverted) speed = -speed;

  if (speed > 0) {
    digitalWrite(inA, HIGH);
    digitalWrite(inB, LOW);
  } else if (speed < 0) {
    digitalWrite(inA, LOW);
    digitalWrite(inB, HIGH);
  } else {
    digitalWrite(inA, LOW);
    digitalWrite(inB, LOW);
  }

  analogWrite(enablePin, abs(speed));
}

void initMotors() {
  pinMode(ENA, OUTPUT);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(ENB, OUTPUT);
  pinMode(IN3, OUTPUT);
  pinMode(IN4, OUTPUT);
  analogWrite(ENA, 0);
  analogWrite(ENB, 0);
  stopMotors();
}

void driveMotors(int leftSpeed, int rightSpeed) {
  setOneMotor(leftSpeed, ENA, IN1, IN2, LEFT_MOTOR_INVERTED);
  setOneMotor(rightSpeed, ENB, IN3, IN4, RIGHT_MOTOR_INVERTED);
}

void stopMotors() {
  driveMotors(0, 0);
}
