"""Compare the loose and strict tag checks on simulated camera views.

    python android/check_tags.py

Uses the same settings as TagReader.kt. Real tags are drawn into leaf scenes at different
sizes, angles and blur. False tags are counted on random cluttered scenes. A real camera can
still behave differently, so this does not replace a test with a printed tag.
"""

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from live.markers import render_marker  # noqa: E402

WIDTH, HEIGHT = 480, 640
MIN_SIDE, MAX_RATIO = 20, 1.6
FOCAL_PIXELS = 436  # Worked out from the phone's camera details in the tag self-test.
TAG_METRES = 0.10


def reader(strict):
    parameters = cv2.aruco.DetectorParameters()
    if strict:
        parameters.errorCorrectionRate = 0.0
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    return cv2.aruco.ArucoDetector(dictionary, parameters), strict


def read(detector, image):
    tool, strict = detector
    corners, ids, _ = tool.detectMarkers(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY))
    found = []
    if ids is None:
        return found
    for box, marker in zip(corners, np.asarray(ids).reshape(-1)):
        p = box.reshape(-1, 2)
        sides = [np.linalg.norm(p[i] - p[(i + 1) % 4]) for i in range(4)]
        if strict and (min(sides) < MIN_SIDE or max(sides) / min(sides) > MAX_RATIO):
            continue
        found.append(int(marker))
    return found


def scene(rng, leaf):
    y = int(rng.integers(0, leaf.shape[0] - 64))
    base = cv2.resize(leaf[y:], (WIDTH, HEIGHT))
    return np.clip(base * rng.uniform(0.6, 1.2), 0, 255).astype(np.uint8)


def draw_tag(image, rng, marker, side, angle):
    """Put a tag on a stake, turned away from the camera by ``angle`` degrees."""
    tag = cv2.cvtColor(render_marker(marker, size=240), cv2.COLOR_GRAY2BGR)
    h, w = tag.shape[:2]
    scale = side / 240
    width = w * scale * np.cos(np.radians(angle))
    height = h * scale
    squeeze = height * 0.5 * (1 - np.cos(np.radians(angle))) * 0.35
    x = rng.uniform(5, max(6, WIDTH - width - 5))
    y = rng.uniform(5, max(6, HEIGHT - height - 5))
    target = np.float32([
        [x, y], [x + width, y + squeeze], [x + width, y + height - squeeze], [x, y + height],
    ])
    source = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    warp = cv2.getPerspectiveTransform(source, target)
    flat = cv2.warpPerspective(tag, warp, (WIDTH, HEIGHT), flags=cv2.INTER_AREA)
    mask = cv2.warpPerspective(np.full((h, w), 255, np.uint8), warp, (WIDTH, HEIGHT))
    image[mask > 0] = flat[mask > 0]


def camera(image, rng, blur):
    if blur:
        image = cv2.GaussianBlur(image, (blur, blur), 0)
    noisy = np.clip(image.astype(np.int16) + rng.normal(0, 5, image.shape), 0, 255).astype(np.uint8)
    ok, data = cv2.imencode(".jpg", noisy, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def clutter(rng):
    """Blocks, lines and grids, the shapes most likely to look like a marker."""
    image = np.full((HEIGHT, WIDTH, 3), rng.integers(40, 220), np.uint8)
    for _ in range(int(rng.integers(30, 90))):
        x, y = int(rng.integers(0, WIDTH)), int(rng.integers(0, HEIGHT))
        size = int(rng.integers(4, 60))
        shade = int(rng.choice([0, 20, 235, 255]))
        if rng.random() < 0.6:
            cv2.rectangle(image, (x, y), (x + size, y + size), (shade,) * 3, -1)
        else:
            cv2.line(image, (x, y), (x + size, y + int(rng.integers(-40, 40))), (shade,) * 3, 2)
    for _ in range(int(rng.integers(2, 8))):
        x, y = int(rng.integers(0, WIDTH - 40)), int(rng.integers(0, HEIGHT - 40))
        cell = int(rng.integers(2, 9))
        for row in range(6):
            for col in range(6):
                edge = row in (0, 5) or col in (0, 5)
                shade = 0 if edge or rng.random() < 0.5 else 255
                cv2.rectangle(image, (x + col * cell, y + row * cell),
                              (x + (col + 1) * cell, y + (row + 1) * cell), (shade,) * 3, -1)
    return image


def main():
    rng = np.random.default_rng(12)
    leaf = cv2.imread(str(ROOT / "vision" / "sample_images" / "tomato_leaf.png"))
    loose, strict = reader(False), reader(True)
    trials = 60

    print("REAL TAGS: share read correctly, loose / strict")
    print("distance  side   angle 0     angle 30    angle 50")
    for metres in (0.4, 0.8, 1.2, 1.6, 2.0, 2.5):
        side = FOCAL_PIXELS * TAG_METRES / metres
        cells = []
        for angle in (0, 30, 50):
            hits = [0, 0]
            for t in range(trials):
                marker = int(rng.integers(1, 40))
                image = scene(rng, leaf)
                draw_tag(image, rng, marker, side, angle)
                image = camera(image, rng, 3 if t % 2 else 0)
                hits[0] += marker in read(loose, image)
                hits[1] += marker in read(strict, image)
            cells.append(f"{100 * hits[0] / trials:3.0f}/{100 * hits[1] / trials:3.0f}%")
        print(f"{metres:5.1f} m  {side:4.0f}px  {'    '.join(cells)}")

    frames = 3000
    loose_hits = strict_hits = 0
    steady = 0
    history = []
    seen = []
    for _ in range(frames):
        image = camera(clutter(rng), rng, 0)
        a = read(loose, image)
        b = read(strict, image)
        loose_hits += bool(a)
        strict_hits += bool(b)
        seen.extend(a)
        history = (history + [set(b)])[-4:]
        steady += any(sum(m in h for h in history) >= 3 for m in b)
    print(f"\nFALSE TAGS in {frames} cluttered frames")
    print(f"loose check: {loose_hits} frames, strict check: {strict_hits}, after the 3-of-4 rule: {steady}")


if __name__ == "__main__":
    main()
