"""Convert the YOLO weights to TensorFlow Lite for the phone's GPU, and check the result.

Needs Python 3.12 with ultralytics, tensorflow-cpu and ai-edge-litert (see android/README.md):

    android/.export-venv/Scripts/python.exe android/export_tflite.py

The result stores weights in half precision, which suits the phone's GPU and halves the file.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from ai_edge_litert.interpreter import Interpreter
from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parent))

from export_model import ASSETS, CONF, IOU, SAMPLE, WEIGHTS, decode, letterbox  # noqa: E402

SIZE = 480


def main():
    # Ultralytics only does this on Linux and macOS, so convert the checked ONNX file directly.
    work = Path(tempfile.mkdtemp(prefix="crap_tflite_", dir=Path(__file__).parent / ".export-work"))
    # onnx2tf rewrites its input file, so it gets a copy. Its sample-data download link is
    # broken, but it prefers a local file, so give it one made from our own leaf image.
    shutil.copy(ASSETS / f"model_{SIZE}.onnx", work / "model.onnx")
    leaf = cv2.resize(cv2.imread(str(SAMPLE)), (128, 128))[:, :, ::-1].astype(np.float32) / 255.0
    np.save(work / "calibration_image_sample_data_20x128x128x3_float32.npy", np.stack([leaf] * 20))

    subprocess.run(
        [str(Path(sys.executable).parent / "onnx2tf"), "-i", "model.onnx", "-o", "out"],
        check=True,
        cwd=work,
        stdout=subprocess.DEVNULL,
    )
    target = ASSETS / f"model_{SIZE}.tflite"
    shutil.copy(work / "out" / "model_float16.tflite", target)

    interpreter = Interpreter(model_path=str(target))
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]
    print("input", inp["shape"], inp["dtype"], "output", out["shape"], out["dtype"], flush=True)

    image = letterbox(cv2.imread(str(SAMPLE)), SIZE)
    if inp["shape"][-1] == 3:
        image = image.transpose(0, 2, 3, 1)
    interpreter.set_tensor(inp["index"], np.ascontiguousarray(image))
    interpreter.invoke()
    output = interpreter.get_tensor(out["index"])

    # Some exports give box coordinates from 0 to 1 instead of pixels.
    print("largest box value", float(output[0, :4].max()), flush=True)
    if output[0, :4].max() <= 2.0:
        output = output.copy()
        output[0, :4] *= SIZE

    kept = decode(output)
    original = YOLO(str(WEIGHTS)).predict(str(SAMPLE), imgsz=SIZE, conf=CONF, iou=IOU, verbose=False, device="cpu")[0]
    expected = sorted(float(c) for c in original.boxes.conf)
    found = sorted(k[0] for k in kept)
    gap = abs(found[-1] - expected[-1]) if found and expected else float("nan")
    ok = abs(len(found) - len(expected)) <= 1 and gap < 0.05
    print(
        f"{target.stat().st_size / 1e6:.1f} MB, original {len(expected)} boxes, converted {len(found)} boxes, "
        f"top score gap {gap:.4f}, classes {sorted({k[1] for k in kept})}, {'OK' if ok else 'MISMATCH'}",
        flush=True,
    )
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
