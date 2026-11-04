#ifndef MOVEMENT_CONTROLLER_H
#define MOVEMENT_CONTROLLER_H

#include <Arduino.h>

void initMovement();
void moveForward(int speed);
void moveBackward(int speed);
void turnLeft(int speed);
void turnRight(int speed);
// These return false, and leave the robot stopped, if the move is too small to measure.
bool moveDistance(float cm, int speed);
bool rotateAngle(float degrees, int speed);
void updateMovement();
bool isMovementComplete();
bool isMovementActive();
void cancelMovement();
const char* getMovementResult();
void clearMovementResult();

#endif
