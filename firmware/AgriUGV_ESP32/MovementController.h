#ifndef MOVEMENT_CONTROLLER_H
#define MOVEMENT_CONTROLLER_H

#include <Arduino.h>

void initMovement();
void moveForward(int speed);
void moveBackward(int speed);
void turnLeft(int speed);
void turnRight(int speed);
void moveDistance(float cm, int speed);
void rotateAngle(float degrees, int speed);
void updateMovement();
bool isMovementComplete();
bool isMovementActive();
void cancelMovement();
const char* getMovementResult();
void clearMovementResult();

#endif
