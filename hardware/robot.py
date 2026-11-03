"""Command interface between the software and the robot's two ESP32 controllers.

The contract (agree it with the hardware teams; see esp32_reference/):

    GET /drive?cmd=forward|back|left|right|stop&ms=500   -> {"ok": true}
    GET /arm?pose=home|inspect|flag                       -> {"ok": true, "pose": "inspect"}
    GET /status                                           -> {"ok": true, ...}

Every move is time-limited, and ``stop`` always wins. ``SimulatedRobot`` follows
the same contract, so the software can be tested before the robot exists.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

DRIVE_COMMANDS = ("forward", "back", "left", "right", "stop")
ARM_POSES = ("home", "inspect", "flag")
MAX_MOVE_MS = 3000


class RobotError(Exception):
    """A command was invalid, or the robot did not carry it out."""


def check_drive(cmd: str, ms: int):
    if cmd not in DRIVE_COMMANDS:
        raise RobotError(f"Unknown drive command: {cmd}")
    if not 0 <= ms <= MAX_MOVE_MS:
        raise RobotError(f"Move time must be between 0 and {MAX_MOVE_MS} ms, got {ms}")


def check_pose(pose: str):
    if pose not in ARM_POSES:
        raise RobotError(f"Unknown arm pose: {pose}")


class SimulatedRobot:
    """Records commands instead of moving anything. ``fail_on`` makes chosen commands fail."""

    def __init__(self, fail_on: Optional[set] = None):
        self.log: list[tuple] = []
        self.arm_pose = "home"
        self.fail_on = set(fail_on or ())

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

    def stop(self) -> dict:
        self.log.append(("drive", "stop", 0))
        return {"ok": True}

    def status(self) -> dict:
        return {"connected": True, "simulated": True, "arm_pose": self.arm_pose}


class HttpRobot:
    """Talks to the drive and arm ESP32s over Wi-Fi using the HTTP contract above."""

    def __init__(self, drive_url: Optional[str] = None, arm_url: Optional[str] = None, timeout: float = 3.0):
        self.drive_url = drive_url.rstrip("/") if drive_url else None
        self.arm_url = arm_url.rstrip("/") if arm_url else None
        self.timeout = timeout

    def _get(self, base: Optional[str], path: str, params: Optional[dict] = None) -> dict:
        if not base:
            raise RobotError(f"No controller configured for {path}")

        url = f"{base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8") or "{}")
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            raise RobotError(f"Could not reach {url}: {err}") from err
        except json.JSONDecodeError as err:
            raise RobotError(f"Controller at {url} did not reply with JSON") from err

        if not body.get("ok", False):
            raise RobotError(f"Controller refused {url}: {body.get('error', body)}")
        return body

    def drive(self, cmd: str, ms: int = 500) -> dict:
        check_drive(cmd, ms)
        return self._get(self.drive_url, "/drive", {"cmd": cmd, "ms": ms})

    def arm(self, pose: str) -> dict:
        check_pose(pose)
        return self._get(self.arm_url, "/arm", {"pose": pose})

    def stop(self) -> dict:
        return self._get(self.drive_url, "/drive", {"cmd": "stop", "ms": 0})

    def status(self) -> dict:
        result = {"simulated": False}
        for name, base in (("drive", self.drive_url), ("arm", self.arm_url)):
            if not base:
                result[name] = {"connected": False, "error": "not configured"}
                continue
            try:
                result[name] = {"connected": True, **self._get(base, "/status")}
            except RobotError as err:
                result[name] = {"connected": False, "error": str(err)}
        result["connected"] = all(result[n]["connected"] for n in ("drive", "arm"))
        return result
