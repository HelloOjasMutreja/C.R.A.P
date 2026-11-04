#include "MovementController.h"
#include "MotorController.h"
#include "EncoderController.h"
#include "config.h"
#include <math.h>

enum MoveMode { MODE_IDLE, MODE_DISTANCE, MODE_ANGLE };

static MoveMode mode = MODE_IDLE;
static long targetLeft = 0;
static long targetRight = 0;
static int baseSpeed = DEFAULT_SPEED;
static int leftDirection = 1;
static int rightDirection = 1;
static unsigned long startedAt = 0;
static unsigned long timeoutMs = 0;
static const char* resultText = "IDLE";
static bool continuousForward = false;

static long cmToTicks(float cm) {
  const float circumference = PI * WHEEL_DIAMETER_CM;
  return lroundf((fabsf(cm) / circumference) * ENCODER_PULSES_PER_WHEEL_REV);
}

static void startMove(long leftTarget, long rightTarget, int leftDir, int rightDir,
                      int speed, float estimatedTravelCm) {
  cancelMovement();
  if (leftTarget <= 0 || rightTarget <= 0) return;

  resetEncoders();
  targetLeft = leftTarget;
  targetRight = rightTarget;
  leftDirection = leftDir;
  rightDirection = rightDir;
  baseSpeed = constrain(abs(speed), MIN_MOVEMENT_SPEED, PWM_MAX);

  timeoutMs = MOVEMENT_TIMEOUT_BASE_MS +
              (unsigned long)(fabsf(estimatedTravelCm) * 10.0f *
                              MOVEMENT_TIMEOUT_PER_METER_MS / 100.0f);
  startedAt = millis();
  mode = MODE_DISTANCE;
  resultText = "RUNNING";
  driveMotors(leftDirection * baseSpeed, rightDirection * baseSpeed);
}

void initMovement() {
  mode = MODE_IDLE;
  continuousForward = false;
  resultText = "IDLE";
  stopMotors();
}

void moveForward(int speed) {
  cancelMovement();
  continuousForward = true;
  driveMotors(abs(speed), abs(speed));
  resultText = "CONTINUOUS";
}

void moveBackward(int speed) {
  cancelMovement();
  continuousForward = false;
  driveMotors(-abs(speed), -abs(speed));
  resultText = "CONTINUOUS";
}

void turnLeft(int speed) {
  cancelMovement();
  continuousForward = false;
  driveMotors(-abs(speed), abs(speed));
  resultText = "CONTINUOUS";
}

void turnRight(int speed) {
  cancelMovement();
  continuousForward = false;
  driveMotors(abs(speed), -abs(speed));
  resultText = "CONTINUOUS";
}

void moveDistance(float cm, int speed) {
  if (cm == 0) return;
  long ticks = cmToTicks(cm);
  startMove(ticks, ticks, cm > 0 ? 1 : -1, cm > 0 ? 1 : -1, speed, fabsf(cm));
}

void rotateAngle(float degrees, int speed) {
  if (degrees == 0) return;
  float arc = PI * TRACK_WIDTH_CM * fabsf(degrees) / 360.0f;
  long ticks = cmToTicks(arc);
  int leftDir = degrees > 0 ? 1 : -1;  // positive = clockwise/right
  int rightDir = -leftDir;
  startMove(ticks, ticks, leftDir, rightDir, speed, arc);
  mode = MODE_ANGLE;
}

void updateMovement() {
  if (mode == MODE_IDLE) return;

  if (millis() - startedAt > timeoutMs) {
    stopMotors();
    mode = MODE_IDLE;
    resultText = "TIMEOUT";
    return;
  }

  long left = labs(getLeftTicks());
  long right = labs(getRightTicks());

  bool leftDone = left >= targetLeft;
  bool rightDone = right >= targetRight;

  if (leftDone && rightDone) {
    stopMotors();
    mode = MODE_IDLE;
    resultText = "COMPLETE";
    return;
  }

  int leftSpeed = leftDone ? 0 : baseSpeed;
  int rightSpeed = rightDone ? 0 : baseSpeed;

  if (!leftDone && !rightDone) {
    long difference = left - right;
    int correction = constrain((int)(labs(difference) * 2), 0, 60);
    if (difference > 0) leftSpeed = max(MIN_MOVEMENT_SPEED, baseSpeed - correction);
    else if (difference < 0) rightSpeed = max(MIN_MOVEMENT_SPEED, baseSpeed - correction);
  }

  driveMotors(leftDirection * leftSpeed, rightDirection * rightSpeed);
}

bool isMovementComplete() { return mode == MODE_IDLE; }
bool isMovementActive() { return mode != MODE_IDLE; }

void cancelMovement() {
  stopMotors();
  continuousForward = false;
  mode = MODE_IDLE;
  resultText = "STOPPED";
}

const char* getMovementResult() { return resultText; }
void clearMovementResult() { resultText = "IDLE"; }
