"""A virtual field: a simulated ESP32 plus the view from a camera on the rover.

    python firmware/simulate_field.py [--slip 0.05]
    adb reverse tcp:3333 tcp:3333
    adb reverse tcp:3334 tcp:3334
    adb shell am start -n com.crap.speedtest/.LiveActivity --es robot_host 127.0.0.1 --es frame_host 127.0.0.1

The phone runs its real tag reader, detector, records and mission on these frames, so a whole
mission can be tested, or shown, with no rover and no plants. Type 1-3 in the app's plant box:
PLANT_017 is deliberately not on that list and should be ignored.
"""

import argparse
import math
import random
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "firmware"))

import simulate_esp32 as esp  # noqa: E402
from live.markers import render_marker  # noqa: E402

FRAME_PORT = 3334
WIDTH, HEIGHT = 480, 640
FOCAL_PIXELS = 436  # The phone's camera on 640 px frames.
TAG_CM = 12.5  # The sticker: a 10 cm black square and its white border, as TagReader.kt assumes.
LEAF_CM = 40.0
LEAF_DROP_CM = 0.0
TAG_DROP_CM = 20.0  # Tags hang below the middle of the plant, so the leaf stays visible.
FRAMES_PER_SECOND = 12

# Name, marker number, x and y in cm. The rover starts at the origin facing +y.
PLANTS = [("PLANT_001", 1, 0.0, 130.0), ("PLANT_002", 2, 105.0, 95.0), ("PLANT_017", 17, -95.0, 90.0)]


class World:
    def __init__(self, slip):
        self.slip = slip
        self.lock = threading.Lock()
        self.x, self.y, self.heading = 0.0, 0.0, 0.0
        self.motion = None
        self.leaf = cv2.imread(str(ROOT / "vision" / "sample_images" / "tomato_leaf.png"))
        # 240 px of marker plus a 30 px border on each side. The caption below it is cut off.
        self.tags = {marker: cv2.cvtColor(render_marker(marker, size=240)[:300, :300], cv2.COLOR_GRAY2BGR)
                     for _, marker, _, _ in PLANTS}

    def begin(self, kind, amount, duration):
        with self.lock:
            amount *= 1 + random.uniform(-self.slip, self.slip)
            self.motion = (kind, amount, time.monotonic(), max(duration, 0.01))

    def _pose(self, now):
        if self.motion is None:
            return self.x, self.y, self.heading
        kind, amount, started, duration = self.motion
        done = amount * min(1.0, (now - started) / duration)
        if kind == "turn":
            return self.x, self.y, self.heading + done
        angle = math.radians(self.heading)
        return self.x + done * math.sin(angle), self.y + done * math.cos(angle), self.heading

    def finish(self):
        with self.lock:
            self.x, self.y, self.heading = self._pose(time.monotonic())
            self.motion = None
            print(f"  rover at ({self.x:.0f}, {self.y:.0f}) cm, heading {self.heading % 360:.0f}", end="", flush=True)
            for name, _, px, py in PLANTS:
                print(f", {name} {math.hypot(px - self.x, py - self.y):.0f} cm", end="", flush=True)
            print(flush=True)

    def _place(self, image, picture, corners):
        h, w = picture.shape[:2]
        source = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        warp = cv2.getPerspectiveTransform(source, np.float32(corners))
        flat = cv2.warpPerspective(picture, warp, (WIDTH, HEIGHT), flags=cv2.INTER_AREA)
        mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), warp, (WIDTH, HEIGHT))
        image[mask > 0] = flat[mask > 0]

    def _board(self, view, centre, across, width, drop):
        """Project an upright square ``width`` cm wide, ``drop`` cm below the camera's height."""
        cam_x, cam_y, right, forward = view
        corners = []
        for side, up in ((-1, 1), (1, 1), (1, -1), (-1, -1)):
            wx = centre[0] + across[0] * side * width / 2 - cam_x
            wy = centre[1] + across[1] * side * width / 2 - cam_y
            depth = wx * forward[0] + wy * forward[1]
            if depth < 8:
                return None
            sideways = wx * right[0] + wy * right[1]
            height = -drop + up * width / 2
            corners.append([WIDTH / 2 + FOCAL_PIXELS * sideways / depth, HEIGHT / 2 - FOCAL_PIXELS * height / depth])
        return corners

    def render(self):
        with self.lock:
            x, y, heading = self._pose(time.monotonic())
        angle = math.radians(heading)
        view = (x, y, (math.cos(angle), -math.sin(angle)), (math.sin(angle), math.cos(angle)))

        image = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
        image[: HEIGHT // 2] = (215, 190, 160)
        image[HEIGHT // 2:] = (70, 105, 125)
        for name, marker, px, py in sorted(PLANTS, key=lambda p: -math.hypot(p[2] - x, p[3] - y)):
            # Each plant faces the rover's start, so tags are seen at a slight angle.
            length = math.hypot(px, py)
            across = (py / length, -px / length)
            leaf = self._board(view, (px, py), across, LEAF_CM, LEAF_DROP_CM)
            tag = self._board(view, (px - 2 * px / length, py - 2 * py / length), across, TAG_CM, TAG_DROP_CM)
            if leaf:
                self._place(image, self.leaf, leaf)
            if tag:
                self._place(image, self.tags[marker], tag)
        noisy = image.astype(np.int16) + np.random.normal(0, 4, image.shape)
        return np.clip(noisy, 0, 255).astype(np.uint8)


class FieldRover(esp.Rover):
    world = None

    def command(self, message):
        super().command(message)
        cmd = message.get("cmd")
        with self.lock:
            if self.running and cmd in ("MOVE_CM", "TURN_DEG"):
                kind, amount = ("move", message["distance"]) if cmd == "MOVE_CM" else ("turn", message["angle"])
                self.world.begin(kind, amount, self.ends_at - time.monotonic())
            elif cmd == "STOP":
                self.world.finish()

    def tick(self):
        was_running = self.running
        super().tick()
        if was_running and not self.running:
            self.world.finish()


def serve_frames(world):
    server = socket.create_server(("127.0.0.1", FRAME_PORT))
    while True:
        link, _ = server.accept()
        print("camera feed connected", flush=True)
        try:
            while True:
                ok, data = cv2.imencode(".jpg", world.render(), [cv2.IMWRITE_JPEG_QUALITY, 85])
                link.sendall(struct.pack(">I", len(data)) + data.tobytes())
                time.sleep(1 / FRAMES_PER_SECOND)
        except OSError:
            print("camera feed disconnected", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--slip", type=float, default=0.05, help="wheel slip, as a share of each move")
    parser.add_argument("--save-frame", help="save the starting view to this file and exit")
    args = parser.parse_args()

    world = World(args.slip)
    if args.save_frame:
        cv2.imwrite(args.save_frame, world.render())
        return
    FieldRover.world = world
    threading.Thread(target=serve_frames, args=(world,), daemon=True).start()

    server = socket.create_server(("127.0.0.1", esp.PORT))
    print("Virtual field ready on ports", esp.PORT, "and", FRAME_PORT, flush=True)
    while True:
        link, _ = server.accept()
        print("phone connected", flush=True)
        try:
            esp.serve(link, False, FieldRover)
        except OSError:
            pass
        print("phone disconnected", flush=True)


if __name__ == "__main__":
    main()
