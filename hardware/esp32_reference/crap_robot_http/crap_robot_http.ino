// C.R.A.P reference firmware: drive or arm ESP32 speaking the laptop's HTTP contract.
//
// UNTESTED STARTING POINT for the hardware teams. Pin numbers, motor driver
// wiring and servo angles are placeholders: change them to match your build.
//
//   GET /drive?cmd=forward|back|left|right|stop&ms=500   -> {"ok":true}
//   GET /arm?pose=home|inspect|flag                       -> {"ok":true,"pose":"inspect"}
//   GET /status                                           -> {"ok":true,...}
//
// Safety: every move is timed and stops by itself; "stop" always wins; moves
// longer than MAX_MOVE_MS are refused.
//
// Build: Arduino IDE with the ESP32 board package. The arm role also needs the
// "ESP32Servo" library. Set ROLE below, flash one board per role, and read the
// IP address from the Serial Monitor. Then on the laptop:
//   python -m live --drive-url http://<drive ip> --arm-url http://<arm ip>

#include <WiFi.h>
#include <WebServer.h>

#define ROLE_DRIVE 1
#define ROLE_ARM 2
#define ROLE ROLE_DRIVE   // <-- change to ROLE_ARM for the arm board

const char* WIFI_SSID = "YOUR_WIFI_OR_PHONE_HOTSPOT";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";
const unsigned long MAX_MOVE_MS = 3000;

WebServer server(80);

void sendJson(int code, const String& body) {
  server.send(code, "application/json", body);
}

#if ROLE == ROLE_DRIVE
// ---------- drive: L298N-style driver, two channels (left and right sides) ----------
const int LEFT_IN1 = 25, LEFT_IN2 = 26, RIGHT_IN1 = 27, RIGHT_IN2 = 14;   // placeholders

unsigned long moveEndsAt = 0;
String currentCmd = "stop";

void setSide(int in1, int in2, int dir) {   // dir: 1 forward, -1 back, 0 stop
  digitalWrite(in1, dir > 0 ? HIGH : LOW);
  digitalWrite(in2, dir < 0 ? HIGH : LOW);
}

void setMotors(int left, int right) {
  setSide(LEFT_IN1, LEFT_IN2, left);
  setSide(RIGHT_IN1, RIGHT_IN2, right);
}

void stopMotors() {
  setMotors(0, 0);
  moveEndsAt = 0;
  currentCmd = "stop";
}

void handleDrive() {
  String cmd = server.arg("cmd");
  unsigned long ms = server.hasArg("ms") ? server.arg("ms").toInt() : 500;

  if (cmd == "stop") { stopMotors(); sendJson(200, "{\"ok\":true}"); return; }
  if (ms > MAX_MOVE_MS) { sendJson(400, "{\"ok\":false,\"error\":\"ms too large\"}"); return; }

  if (cmd == "forward")    setMotors(1, 1);
  else if (cmd == "back")  setMotors(-1, -1);
  else if (cmd == "left")  setMotors(-1, 1);
  else if (cmd == "right") setMotors(1, -1);
  else { sendJson(400, "{\"ok\":false,\"error\":\"unknown cmd\"}"); return; }

  currentCmd = cmd;
  moveEndsAt = millis() + ms;
  sendJson(200, "{\"ok\":true}");
}

void handleStatus() {
  bool busy = moveEndsAt != 0;
  sendJson(200, String("{\"ok\":true,\"role\":\"drive\",\"busy\":") + (busy ? "true" : "false") +
                ",\"cmd\":\"" + currentCmd + "\"}");
}

void setupRole() {
  int pins[] = {LEFT_IN1, LEFT_IN2, RIGHT_IN1, RIGHT_IN2};
  for (int pin : pins) pinMode(pin, OUTPUT);
  stopMotors();
  server.on("/drive", handleDrive);
}

void loopRole() {
  if (moveEndsAt != 0 && (long)(millis() - moveEndsAt) >= 0) stopMotors();   // timed stop
}

#else
// ---------- arm: one servo per joint, fixed poses ----------
#include <ESP32Servo.h>

const int JOINT_PINS[] = {18, 19, 21};                 // base, shoulder, elbow (placeholders)
const int POSE_HOME[] = {90, 40, 150};                 // angles in degrees (placeholders)
const int POSE_INSPECT[] = {90, 100, 80};
const int POSE_FLAG[] = {120, 120, 60};
const int JOINTS = sizeof(JOINT_PINS) / sizeof(JOINT_PINS[0]);

Servo servos[JOINTS];
String currentPose = "home";

void moveTo(const int* angles) {
  for (int i = 0; i < JOINTS; i++) servos[i].write(angles[i]);
}

void handleArm() {
  String pose = server.arg("pose");
  if (pose == "home")         moveTo(POSE_HOME);
  else if (pose == "inspect") moveTo(POSE_INSPECT);
  else if (pose == "flag")    moveTo(POSE_FLAG);
  else { sendJson(400, "{\"ok\":false,\"error\":\"unknown pose\"}"); return; }

  currentPose = pose;
  sendJson(200, "{\"ok\":true,\"pose\":\"" + pose + "\"}");
}

void handleDriveStop() {
  // The arm board has no wheels; accept stop so a shared stop call never fails.
  sendJson(200, "{\"ok\":true}");
}

void handleStatus() {
  sendJson(200, "{\"ok\":true,\"role\":\"arm\",\"pose\":\"" + currentPose + "\"}");
}

void setupRole() {
  for (int i = 0; i < JOINTS; i++) servos[i].attach(JOINT_PINS[i]);
  moveTo(POSE_HOME);
  server.on("/arm", handleArm);
  server.on("/drive", handleDriveStop);
}

void loopRole() {}
#endif

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) { delay(300); Serial.print("."); }
  Serial.print("\nReady at http://");
  Serial.println(WiFi.localIP());

  setupRole();
  server.on("/status", handleStatus);
  server.onNotFound([]() { sendJson(404, "{\"ok\":false,\"error\":\"not found\"}"); });
  server.begin();
}

void loop() {
  server.handleClient();
  loopRole();
}
