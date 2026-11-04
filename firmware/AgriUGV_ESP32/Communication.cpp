#include "Communication.h"
#include "config.h"
#include "MotorController.h"
#include "EncoderController.h"
#include "MovementController.h"
#include "SensorController.h"

#include <WiFi.h>
#include <ArduinoJson.h>
#include <math.h>
#include <string.h>

static WiFiServer server(TCP_PORT);
static WiFiClient client;
static String inputBuffer;
static unsigned long lastTelemetry = 0;
static bool movementWasActive = false;
static bool hadClient = false;

static void sendDoc(JsonDocument& doc) {
  if (client && client.connected()) {
    serializeJson(doc, client);
    client.println();
  }
}

static void sendStatus(const char* status) {
  JsonDocument doc;
  doc["type"] = "STATUS";
  doc["status"] = status;
  sendDoc(doc);
}

static void sendTelemetry() {
  if (!client || !client.connected()) return;

  SensorData s = getSensorData();
  JsonDocument doc;
  doc["type"] = "TELEMETRY";

  if (isnan(s.humidity)) doc["humidity"] = nullptr;
  else doc["humidity"] = s.humidity;

  if (isnan(s.temperature)) doc["temperature"] = nullptr;
  else doc["temperature"] = s.temperature;

  doc["left_ticks"] = getLeftTicks();
  doc["right_ticks"] = getRightTicks();
  doc["movement_active"] = isMovementActive();
  doc["movement_result"] = getMovementResult();
  sendDoc(doc);
}

static void processCommand(const String& message) {
  JsonDocument doc;
  DeserializationError error = deserializeJson(doc, message);
  if (error) {
    sendStatus("INVALID_JSON");
    return;
  }

  const char* cmd = doc["cmd"] | "";

  if (strcmp(cmd, "STOP") == 0) {
    cancelMovement();
    movementWasActive = false;
    sendStatus("STOPPED");
  }
  else if (strcmp(cmd, "FORWARD") == 0) {
    moveForward(constrain((int)(doc["speed"] | DEFAULT_SPEED), 0, PWM_MAX));
    movementWasActive = false;
    sendStatus("FORWARD");
  }
  else if (strcmp(cmd, "BACKWARD") == 0) {
    moveBackward(constrain((int)(doc["speed"] | DEFAULT_SPEED), 0, PWM_MAX));
    movementWasActive = false;
    sendStatus("BACKWARD");
  }
  else if (strcmp(cmd, "LEFT") == 0) {
    turnLeft(constrain((int)(doc["speed"] | DEFAULT_SPEED), 0, PWM_MAX));
    movementWasActive = false;
    sendStatus("TURNING_LEFT");
  }
  else if (strcmp(cmd, "RIGHT") == 0) {
    turnRight(constrain((int)(doc["speed"] | DEFAULT_SPEED), 0, PWM_MAX));
    movementWasActive = false;
    sendStatus("TURNING_RIGHT");
  }
  else if (strcmp(cmd, "DRIVE") == 0) {
    cancelMovement();
    int left = constrain((int)(doc["left"] | 0), -PWM_MAX, PWM_MAX);
    int right = constrain((int)(doc["right"] | 0), -PWM_MAX, PWM_MAX);
    driveMotors(left, right);
    movementWasActive = false;
    sendStatus("DRIVING");
  }
  else if (strcmp(cmd, "MOVE_CM") == 0) {
    float distance = doc["distance"] | 0.0f;
    int speed = doc["speed"] | DEFAULT_SPEED;
    if (distance == 0) {
      sendStatus("INVALID_DISTANCE");
      return;
    }
    moveDistance(distance, speed);
    movementWasActive = isMovementActive();
    sendStatus("MOVEMENT_STARTED");
  }
  else if (strcmp(cmd, "TURN_DEG") == 0) {
    float angle = doc["angle"] | 0.0f;
    int speed = doc["speed"] | 130;
    if (angle == 0) {
      sendStatus("INVALID_ANGLE");
      return;
    }
    rotateAngle(angle, speed);
    movementWasActive = isMovementActive();
    sendStatus("TURN_STARTED");
  }
  else if (strcmp(cmd, "SENSORS") == 0) {
    sendTelemetry();
  }
  else {
    sendStatus("UNKNOWN_COMMAND");
  }
}

void initCommunication() {
  WiFi.mode(WIFI_AP);
  WiFi.softAP(WIFI_SSID, WIFI_PASSWORD);
  server.begin();
  server.setNoDelay(true);

  Serial.println("Wi-Fi access point started");
  Serial.print("SSID: ");
  Serial.println(WIFI_SSID);
  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.softAPIP());
  Serial.print("TCP port: ");
  Serial.println(TCP_PORT);
}

void handleCommunication() {
  if (!client || !client.connected()) {
    if (hadClient) {
      cancelMovement();
      movementWasActive = false;
      Serial.println("Phone disconnected: motors stopped");
      hadClient = false;
    }

    WiFiClient newClient = server.available();
    if (newClient) {
      client = newClient;
      client.setNoDelay(true);
      inputBuffer = "";
      hadClient = true;
      sendStatus("CONNECTED");
    }
  }

  if (client && client.connected()) {
    while (client.available()) {
      char c = (char)client.read();
      if (c == '\n') {
        if (inputBuffer.length() > 0) processCommand(inputBuffer);
        inputBuffer = "";
      } else if (c != '\r') {
        if (inputBuffer.length() < 512) inputBuffer += c;
        else {
          inputBuffer = "";
          sendStatus("COMMAND_TOO_LONG");
        }
      }
    }

    if (movementWasActive && !isMovementActive()) {
      sendStatus(getMovementResult());
      movementWasActive = false;
    }

    if (millis() - lastTelemetry >= TELEMETRY_INTERVAL_MS) {
      lastTelemetry = millis();
      sendTelemetry();
    }
  }
}
