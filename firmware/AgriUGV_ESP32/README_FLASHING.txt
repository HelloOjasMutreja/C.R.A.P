AGRIUGV ESP32 - NO ULTRASONIC SENSORS BUILD
===========================================

This project version removes ALL ultrasonic sensor code, pins, readings,
obstacle detection and ultrasonic wiring references. It supports:
- L298N controlling left and right motor groups
- Two single-channel wheel encoders
- 3-pin DHT22 humidity/temperature module
- Wi-Fi TCP communication with the phone

PIN CONNECTIONS
---------------
L298N:
ENA=GPIO25, IN1=GPIO26, IN2=GPIO27
ENB=GPIO14, IN3=GPIO32, IN4=GPIO33
Left motors: OUT1/OUT2. Right motors: OUT3/OUT4.

Encoders:
Left encoder OUT=GPIO34
Right encoder OUT=GPIO35
Encoder VCC/GND according to module voltage requirements.
GPIO34 and GPIO35 have no internal pull-ups on classic ESP32 boards.
If the encoder output is open-collector/open-drain, add an external pull-up
to 3.3V. Never pull an ESP32 input up to 5V.

3-pin DHT22:
+ = 3.3V
- = GND
OUT = GPIO4

INSTALLATION
------------
1. Install Arduino IDE 2.x.
2. In Arduino IDE > Preferences, add this Boards Manager URL if needed:
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
3. Open Boards Manager, search "esp32", install "esp32 by Espressif Systems".
4. Install these libraries using Library Manager:
   - DHT sensor library by Adafruit
   - Adafruit Unified Sensor
   - ArduinoJson version 7
5. Extract this folder and open AgriUGV_ESP32.ino.
   Keep all .h and .cpp files in the same project folder.
6. Select Tools > Board > esp32 > ESP32 Dev Module (or your exact board).
7. Select the correct USB/COM port.
8. Compile, then upload. If connecting fails, hold BOOT during upload start.
9. Open Serial Monitor at 115200 baud.

PHONE CONNECTION
----------------
Wi-Fi SSID: AgriUGV
Password: agriugv123
ESP32 IP: 192.168.4.1
TCP port: 3333

Phone app opens a TCP socket to 192.168.4.1:3333.
Send one JSON command per line, ending with newline.

Examples:
{"cmd":"FORWARD","speed":120}
{"cmd":"STOP"}
{"cmd":"MOVE_CM","distance":50,"speed":120}
{"cmd":"TURN_DEG","angle":90,"speed":110}
{"cmd":"SENSORS"}

Telemetry JSON includes humidity, temperature, left_ticks, right_ticks,
movement_active and movement_result. There are no ultrasonic fields.

IMPORTANT CALIBRATION / SAFETY
------------------------------
- Values in config.h for wheel diameter, track width and encoder pulses per
  wheel revolution are example values. Measure/calibrate the actual rover.
- Code counts one rising edge per encoder slot. Confirm actual pulses per
  wheel revolution and encoder electrical output type.
- GPIO34/35 have no internal pull-ups on classic ESP32 boards.
- Common ground is required between ESP32, motor driver and sensor supply.
- Check L298N current/thermal capability. Two motors in parallel per side
  can exceed its safe current, especially at startup or stall.
- Test with wheels raised before ground testing.
- Ultrasonic sensors are not connected or used in this build. There is NO
  automatic obstacle detection in this version. Operate slowly under direct
  supervision and use a physical emergency stop that cuts motor power.
- This prototype is not a certified safety system.
- Change the example Wi-Fi password before deployment.
