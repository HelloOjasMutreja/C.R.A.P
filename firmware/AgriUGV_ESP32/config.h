#ifndef CONFIG_H
#define CONFIG_H

// L298N: left side on OUT1/OUT2, right side on OUT3/OUT4
#define ENA 25
#define IN1 26
#define IN2 27
#define ENB 14
#define IN3 32
#define IN4 33

// Set true if that side runs opposite to the intended direction
#define LEFT_MOTOR_INVERTED false
#define RIGHT_MOTOR_INVERTED false

// Single-channel encoder inputs; one rising edge is counted per slot
#define LEFT_ENCODER_PIN 34
#define RIGHT_ENCODER_PIN 35

// 3-pin DHT22 module: + to 3.3V, - to GND, OUT to GPIO 4
#define DHT_PIN 4

// CALIBRATE THESE VALUES ON THE ACTUAL ROVER
#define WHEEL_DIAMETER_CM 6.5f
#define TRACK_WIDTH_CM 25.0f
#define ENCODER_PULSES_PER_WHEEL_REV 20.0f

// Safety and control
#define PWM_MAX 255
#define DEFAULT_SPEED 150
#define MIN_MOVEMENT_SPEED 80
#define SENSOR_INTERVAL_MS 2000
#define TELEMETRY_INTERVAL_MS 500
#define MOVEMENT_TIMEOUT_BASE_MS 15000UL
#define MOVEMENT_TIMEOUT_PER_METER_MS 10000UL

// Wi-Fi access point
#define WIFI_SSID "AgriUGV"
#define WIFI_PASSWORD "agriugv123"
#define TCP_PORT 3333

#endif
