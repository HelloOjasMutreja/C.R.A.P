#ifndef MOTOR_CONTROLLER_H
#define MOTOR_CONTROLLER_H

#include <Arduino.h>

void initMotors();
void driveMotors(int leftSpeed, int rightSpeed);
void stopMotors();
bool motorsAreRunning();

#endif
