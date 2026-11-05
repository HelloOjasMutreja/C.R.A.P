"""A stand-in for the rover's ESP32, for testing the phone app without hardware.

    python firmware/simulate_esp32.py [--stall]
    adb reverse tcp:3333 tcp:3333
    adb shell am start -n com.crap.speedtest/.LiveActivity --es robot_host 127.0.0.1

Speaks the same JSON lines as firmware/AgriUGV_ESP32, including the silence stop.
--stall makes moves end as STALLED, as if an encoder wire had come off.
"""

import argparse
import json
import math
import socket
import threading
import time

PORT = 3333
WHEEL_DIAMETER_CM = 6.5
TRACK_WIDTH_CM = 25.0
PULSES_PER_REV = 20.0
CM_PER_SECOND = 25.0
SILENCE_LIMIT_S = 1.0
TELEMETRY_S = 0.5


def ticks_for(cm):
    return round(abs(cm) / (math.pi * WHEEL_DIAMETER_CM) * PULSES_PER_REV)


class Rover:
    def __init__(self, link, stall):
        self.link = link
        self.stall = stall
        self.ends_at = None
        self.running = False
        self.last_command = time.monotonic()
        self.ticks = 0
        self.lock = threading.Lock()

    def send(self, message):
        self.link.sendall((json.dumps(message) + "\n").encode())

    def status(self, words):
        print("  ->", words, flush=True)
        self.send({"type": "STATUS", "status": words})

    def begin(self, travel_cm, started):
        if ticks_for(travel_cm) <= 0:
            self.status("TOO_SMALL")
            return
        self.ticks += ticks_for(travel_cm)
        self.running = True
        self.ends_at = time.monotonic() + (1.5 if self.stall else abs(travel_cm) / CM_PER_SECOND)
        self.status(started)

    def command(self, message):
        cmd = message.get("cmd", "")
        with self.lock:
            self.last_command = time.monotonic()
            if cmd == "PING":
                return
            print("command", message, flush=True)
            if cmd == "STOP":
                self.running = False
                self.ends_at = None
                self.status("STOPPED")
            elif cmd == "MOVE_CM":
                self.begin(message.get("distance", 0), "MOVEMENT_STARTED")
            elif cmd == "TURN_DEG":
                self.begin(math.pi * TRACK_WIDTH_CM * abs(message.get("angle", 0)) / 360, "TURN_STARTED")
            else:
                self.status("UNKNOWN_COMMAND")

    def tick(self):
        with self.lock:
            now = time.monotonic()
            if self.running and now - self.last_command > SILENCE_LIMIT_S:
                self.running = False
                self.ends_at = None
                self.status("SILENCE_STOP")
            if self.ends_at is not None and now >= self.ends_at:
                self.running = False
                self.ends_at = None
                self.status("STALLED" if self.stall else "COMPLETE")


def serve(link, stall, make_rover=Rover):
    rover = make_rover(link, stall)
    rover.status("CONNECTED")

    def background():
        last = 0.0
        while True:
            rover.tick()
            if time.monotonic() - last >= TELEMETRY_S:
                last = time.monotonic()
                rover.send({
                    "type": "TELEMETRY",
                    "humidity": 74.0,
                    "temperature": 29.5,
                    "left_ticks": rover.ticks,
                    "right_ticks": rover.ticks,
                    "movement_active": rover.running,
                })
            time.sleep(0.02)

    threading.Thread(target=background, daemon=True).start()
    for line in link.makefile():
        if line.strip():
            rover.command(json.loads(line))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stall", action="store_true")
    args = parser.parse_args()

    server = socket.create_server(("127.0.0.1", PORT))
    print("Simulated ESP32 on port", PORT, flush=True)
    while True:
        link, _ = server.accept()
        print("phone connected", flush=True)
        try:
            serve(link, args.stall)
        except OSError:
            pass
        print("phone disconnected", flush=True)


if __name__ == "__main__":
    main()
