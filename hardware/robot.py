"""Command interface between the software and the robot's single ESP32.

The ESP32 firmware listens on Bluetooth Classic serial (device ``UGV_ESP32``)
for newline-terminated text commands:

    F:1000  B:1000  L:500  R:500    timed drive, 1 to 10000 ms
    S                               stop
    V180                            set speed, 0 to 255

and sends ``sensor_data`` JSON lines with DHT22 readings about every 2.5 s.

The firmware sends no acknowledgement and silently ignores unknown commands, so
a successful send only means the command left the laptop. Arm commands are a
proposal the firmware does not implement yet, so they stay refused until the
robot is created with ``has_arm=True``:

    A:HOME  A:INSPECT  A:SPRAY      move arm to a pose, finish before the next command
    P:500                           squeeze the spray trigger for 500 ms

``SimulatedRobot`` offers the same methods, so the software can be tested
before the robot exists.
"""

import json
import threading
import time
from typing import Optional

DRIVE_COMMANDS = ("forward", "back", "left", "right", "stop")
ARM_POSES = ("home", "inspect", "spray")
MAX_MOVE_MS = 3000
MAX_SPRAY_MS = 2000
SENSOR_MAX_AGE_S = 30

DRIVE_LETTERS = {"forward": "F", "back": "B", "left": "L", "right": "R"}


class RobotError(Exception):
    """A command was invalid, or could not be sent to the robot."""


def check_drive(cmd: str, ms: int):
    if cmd not in DRIVE_COMMANDS:
        raise RobotError(f"Unknown drive command: {cmd}")
    if not 0 <= ms <= MAX_MOVE_MS:
        raise RobotError(f"Move time must be between 0 and {MAX_MOVE_MS} ms, got {ms}")


def check_pose(pose: str):
    if pose not in ARM_POSES:
        raise RobotError(f"Unknown arm pose: {pose}")


def check_spray(ms: int):
    if not 1 <= ms <= MAX_SPRAY_MS:
        raise RobotError(f"Spray time must be between 1 and {MAX_SPRAY_MS} ms, got {ms}")


class SimulatedRobot:
    """Records commands instead of moving anything. ``fail_on`` makes chosen commands fail."""

    has_arm = True

    def __init__(self, fail_on: Optional[set] = None, sensor_reading: Optional[dict] = None):
        self.log: list[tuple] = []
        self.arm_pose = "home"
        self.fail_on = set(fail_on or ())
        self.sensor_reading = sensor_reading or {}

    def drive(self, cmd: str, ms: int = 500) -> dict:
        check_drive(cmd, ms)
        if cmd in self.fail_on:
            raise RobotError(f"Simulated failure on drive {cmd}")
        self.log.append(("drive", cmd, ms))
        return {"ok": True}

    def arm(self, pose: str) -> dict:
        check_pose(pose)
        if pose in self.fail_on:
            raise RobotError(f"Simulated failure on arm {pose}")
        self.log.append(("arm", pose))
        self.arm_pose = pose
        return {"ok": True, "pose": pose}

    def spray(self, ms: int = 500) -> dict:
        check_spray(ms)
        if "spray_trigger" in self.fail_on:
            raise RobotError("Simulated failure on spray")
        self.log.append(("spray", ms))
        return {"ok": True}

    def stop(self) -> dict:
        self.log.append(("drive", "stop", 0))
        return {"ok": True}

    def sensors(self) -> dict:
        return dict(self.sensor_reading)

    def status(self) -> dict:
        return {"connected": True, "simulated": True, "has_arm": self.has_arm, "arm_pose": self.arm_pose}


class BluetoothRobot:
    """Talks to the ESP32 through the COM port Windows creates when it is paired.

    A background thread keeps the port open, reconnects if it drops, and reads
    sensor lines, so a slow Bluetooth link never blocks the web server.
    """

    def __init__(self, port: str, has_arm: bool = False, baud: int = 115200, opener=None):
        self.port = port
        self.has_arm = has_arm
        self.baud = baud
        self._opener = opener if opener is not None else self._open_serial
        self._link = None
        self._write_lock = threading.Lock()
        self._reading: dict = {}
        self._reading_at = 0.0
        self._closed = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _open_serial(self):
        import serial

        return serial.Serial(self.port, self.baud, timeout=0.5, write_timeout=2)

    def _run(self):
        while not self._closed:
            try:
                if self._link is None:
                    self._link = self._opener()
                line = self._link.readline()
                if line:
                    self._on_line(line)
            except OSError:
                self._drop_link()
                time.sleep(2)

    def _drop_link(self):
        link, self._link = self._link, None
        if link is not None:
            try:
                link.close()
            except OSError:
                pass

    def _on_line(self, line: bytes):
        try:
            message = json.loads(line.decode("utf-8", errors="ignore"))
        except ValueError:
            return

        # Failed and simulated readings must never become evidence in the dossier.
        if (
            not isinstance(message, dict)
            or message.get("type") != "sensor_data"
            or not message.get("valid")
            or message.get("simulated")
        ):
            return

        self._reading = {
            "temperature_c": message.get("temperature_c"),
            "humidity_rh": message.get("humidity_rh"),
        }
        self._reading_at = time.monotonic()

    def _send(self, command: str):
        with self._write_lock:
            link = self._link
            if link is None:
                raise RobotError(f"Robot is not connected on {self.port}")
            try:
                link.write(f"{command}\n".encode("ascii"))
            except OSError as err:
                self._drop_link()
                raise RobotError(f"Lost the robot on {self.port}: {err}") from err

    def drive(self, cmd: str, ms: int = 500) -> dict:
        check_drive(cmd, ms)
        if cmd == "stop":
            return self.stop()
        # An untimed move would need heartbeats, so every move here has a time limit.
        if ms < 1:
            raise RobotError("Moves must have a time limit of at least 1 ms")
        self._send(f"{DRIVE_LETTERS[cmd]}:{ms}")
        return {"ok": True}

    def arm(self, pose: str) -> dict:
        check_pose(pose)
        self._require_arm()
        self._send(f"A:{pose.upper()}")
        return {"ok": True, "pose": pose}

    def spray(self, ms: int = 500) -> dict:
        check_spray(ms)
        self._require_arm()
        self._send(f"P:{ms}")
        return {"ok": True}

    def _require_arm(self):
        if not self.has_arm:
            raise RobotError("Arm commands are not in the ESP32 firmware yet")

    def stop(self) -> dict:
        self._send("S")
        return {"ok": True}

    def sensors(self) -> dict:
        if not self._reading or time.monotonic() - self._reading_at > SENSOR_MAX_AGE_S:
            return {}
        return dict(self._reading)

    def status(self) -> dict:
        return {
            "connected": self._link is not None,
            "simulated": False,
            "port": self.port,
            "has_arm": self.has_arm,
            "sensors": self.sensors(),
        }

    def close(self):
        self._closed = True
        self._thread.join(timeout=2)
        self._drop_link()
