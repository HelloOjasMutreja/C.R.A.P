"""Convert the YOLO weights to ONNX for the Android app, and check the result.

    python android/export_model.py

Writes model_<size>.onnx into the app's assets, then runs each file with ONNX
Runtime on the same image as the original model and compares the detections.
"""

import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "vision" / "weights" / "best.pt"
SAMPLE = ROOT / "vision" / "sample_images" / "tomato_leaf.png"
ASSETS = ROOT / "android" / "app" / "src" / "main" / "assets"
SIZES = (320, 480, 640)
CONF, IOU, NUM_CLASSES = 0.25, 0.45, 29


def letterbox(image, size):
    """Same steps as Detector.kt: fit inside a square, pad with grey, scale to 0..1, RGB, CHW."""
    h, w = image.shape[:2]
    scale = size / max(h, w)
    nh, nw = round(h * scale), round(w * scale)
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    top, left = (size - nh) // 2, (size - nw) // 2
    canvas[top:top + nh, left:left + nw] = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LINEAR)
    rgb = canvas[:, :, ::-1].astype(np.float32) / 255.0
    return np.ascontiguousarray(rgb.transpose(2, 0, 1)[None])


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def decode(output):
    """Same logic as Detector.kt: output is [1, 4 + classes, boxes]; per-class non-maximum suppression."""
    data = output[0]
    candidates = []
    for i in range(data.shape[1]):
        scores = data[4:, i]
        cls = int(scores.argmax())
        score = float(scores[cls])
        if score >= CONF:
            cx, cy, w, h = data[:4, i]
            candidates.append((score, cls, (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)))

    kept = []
    for candidate in sorted(candidates, key=lambda c: -c[0]):
        if all(k[1] != candidate[1] or iou(k[2], candidate[2]) <= IOU for k in kept):
            kept.append(candidate)
    return kept


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    image = cv2.imread(str(SAMPLE))
    shutil.copy(SAMPLE, ASSETS / "sample.png")
    failed = False

    for size in SIZES:
        exported = Path(YOLO(str(WEIGHTS)).export(format="onnx", imgsz=size, simplify=True, verbose=False))
        target = ASSETS / f"model_{size}.onnx"
        shutil.move(str(exported), target)

        original = YOLO(str(WEIGHTS)).predict(str(SAMPLE), imgsz=size, conf=CONF, iou=IOU, verbose=False, device="cpu")[0]
        expected = sorted(float(c) for c in original.boxes.conf)

        session = ort.InferenceSession(str(target), providers=["CPUExecutionProvider"])
        name = session.get_inputs()[0].name
        output = session.run(None, {name: letterbox(image, size)})[0]
        kept = decode(output)
        found = sorted(k[0] for k in kept)
        classes = sorted({k[1] for k in kept})

        gap = abs(found[-1] - expected[-1]) if found and expected else float("nan")
        ok = abs(len(found) - len(expected)) <= 1 and gap < 0.05
        failed |= not ok
        print(
            f"{size}: {target.stat().st_size / 1e6:.1f} MB, output {output.shape}, "
            f"original {len(expected)} boxes, converted {len(found)} boxes, "
            f"top score gap {gap:.4f}, classes {classes}, {'OK' if ok else 'MISMATCH'}",
            flush=True,
        )

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
