#ifndef ENCODER_CONTROLLER_H
#define ENCODER_CONTROLLER_H

#include <Arduino.h>

void initEncoders();
void resetEncoders();
long getLeftTicks();
long getRightTicks();

#endif
