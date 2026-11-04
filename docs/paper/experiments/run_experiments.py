"""Experiments for the C.R.A.P conference paper.

Usage (from the repository root):
    python docs/paper/experiments/run_experiments.py --dataset <PlantDoc repo folder>

Reads the PlantDoc object-detection test split, then writes JSON results to
docs/paper/results and figures to docs/paper/figures.

    E1  detector accuracy on the test split at several input sizes
    E2  CPU latency of each stage of the live pipeline
    E3  repeat-sighting rule against single-image diagnosis, using real detections
        passed through the real DiagnosticEngine, with error correlation varied
    E4  plant tag read rate by tag size in the frame
"""

import argparse
import json
import random
import shutil
import statistics
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from legacy_engine import DiagnosticEngine  # noqa: E402  (the rule the paper describes)
from dossier import DossierService  # noqa: E402
from live.markers import PlantTagReader, render_marker  # noqa: E402
from vision import CLASS_METADATA, DEFAULT_WEIGHTS_PATH, PlantDocDetector  # noqa: E402

RESULTS = ROOT / "docs" / "paper" / "results"
FIGURES = ROOT / "docs" / "paper" / "figures"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp"}
NAME_TO_ID = {m["name"].lower(): i for i, m in CLASS_METADATA.items()}


class MemoryStore:
    """Same interface as PlantStore, without the JSON file, so simulations stay fast."""

    def __init__(self):
        self.plants = {}
        self.file_path = Path("memory")

    def load_plants(self):
        return dict(self.plants)

    def save_plants(self, plants):
        self.plants = dict(plants)

    def get_plant(self, plant_id):
        return self.plants.get(plant_id)

    def add_plant(self, plant):
        self.plants[plant.plant_id] = plant


def load_test_split(dataset: Path):
    """Return [(image_path, [(class_id, x1, y1, x2, y2), ...], (w, h))] for the TEST folder."""
    test_dir = dataset / "TEST"
    items, unknown = [], defaultdict(int)

    for xml_path in sorted(test_dir.glob("*.xml")):
        root = ET.parse(xml_path).getroot()
        image = next(
            (xml_path.with_suffix(s) for s in (".jpg", ".JPG", ".jpeg", ".png") if xml_path.with_suffix(s).exists()),
            None,
        )
        if image is None:
            continue

        size = root.find("size")
        w, h = int(size.find("width").text or 0), int(size.find("height").text or 0)
        boxes = []
        for obj in root.findall("object"):
            name = obj.find("name").text.strip().lower()
            if name not in NAME_TO_ID:
                unknown[name] += 1
                continue
            b = obj.find("bndbox")
            boxes.append((
                NAME_TO_ID[name],
                float(b.find("xmin").text),
                float(b.find("ymin").text),
                float(b.find("xmax").text),
                float(b.find("ymax").text),
            ))
        if boxes and w and h:
            items.append((image, boxes, (w, h)))

    return items, dict(unknown)


def e1_accuracy(items, detector):
    """Run Ultralytics validation on a YOLO-format copy of the test split."""
    work = Path(tempfile.mkdtemp(prefix="plantdoc_yolo_"))
    (work / "images" / "test").mkdir(parents=True)
    (work / "labels" / "test").mkdir(parents=True)

    for image, boxes, (w, h) in items:
        shutil.copy(image, work / "images" / "test" / image.name)
        lines = []
        for cls, x1, y1, x2, y2 in boxes:
            cx, cy = (x1 + x2) / 2 / w, (y1 + y2) / 2 / h
            lines.append(f"{cls} {cx:.6f} {cy:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
        (work / "labels" / "test" / f"{image.stem}.txt").write_text("\n".join(lines))

    names = "\n".join(f"  {i}: {m['name']}" for i, m in CLASS_METADATA.items())
    yaml_path = work / "data.yaml"
    yaml_path.write_text(f"path: {work.as_posix()}\ntrain: images/test\nval: images/test\nnames:\n{names}\n")

    rows, per_class = [], {}
    for imgsz in (320, 480, 640, 800):
        metrics = detector.model.val(
            data=str(yaml_path), imgsz=imgsz, batch=4, device="cpu", plots=False, verbose=False, workers=0
        )
        rows.append({
            "imgsz": imgsz,
            "precision": float(metrics.box.mp),
            "recall": float(metrics.box.mr),
            "map50": float(metrics.box.map50),
            "map50_95": float(metrics.box.map),
        })
        print("E1", rows[-1], flush=True)
        if imgsz == 800:
            for i, cls in enumerate(metrics.box.ap_class_index):
                per_class[CLASS_METADATA[int(cls)]["name"]] = float(metrics.box.ap50[i])

    shutil.rmtree(work, ignore_errors=True)
    return {"sizes": rows, "per_class_ap50_at_800": per_class}


def e2_latency(items, detector, runs=60):
    frame = cv2.imread(str(items[0][0]))
    frame = cv2.resize(frame, (512, int(frame.shape[0] * 512 / frame.shape[1])))
    ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    data = jpeg.tobytes()
    tags = PlantTagReader()

    def timed(fn):
        values = []
        for _ in range(runs):
            start = time.perf_counter()
            fn()
            values.append((time.perf_counter() - start) * 1000)
        values.sort()
        return {"mean_ms": statistics.mean(values), "p95_ms": values[int(0.95 * len(values)) - 1]}

    rows = {"jpeg_kb": len(data) / 1024}
    rows["jpeg_decode"] = timed(lambda: cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR))
    rows["tag_read"] = timed(lambda: tags.read(frame))
    for imgsz in (320, 480, 640, 800):
        for _ in range(5):
            detector.model.predict(frame, imgsz=imgsz, conf=0.25, verbose=False, device="cpu")
        rows[f"yolo_{imgsz}"] = timed(
            lambda: detector.model.predict(frame, imgsz=imgsz, conf=0.25, verbose=False, device="cpu")
        )
    print("E2", rows, flush=True)
    return rows


def collect_detections(items, detector, imgsz, conf=0.10):
    """Detections for every test image, as the dictionaries the dossier stores."""
    records = []
    for index, (image, boxes, _) in enumerate(items):
        result = detector.model.predict(str(image), imgsz=imgsz, conf=conf, verbose=False, device="cpu")[0]
        detections = []
        for box in result.boxes:
            cls = int(box.cls[0].item())
            meta = CLASS_METADATA[cls]
            detections.append({
                "class_id": cls,
                "raw_class_name": meta["name"],
                "species": meta["species"],
                "condition": meta["condition"],
                "is_healthy": meta["is_healthy"],
                "confidence": float(box.conf[0].item()),
                "bbox": [int(v) for v in box.xyxy[0].tolist()],
            })
        truth = sorted({b[0] for b in boxes})
        records.append({"image": image.name, "truth": truth, "detections": detections})
        if index % 50 == 0:
            print("detections", index, flush=True)
    return records


def image_pools(records):
    """Group images into diseased pools per (species, condition) and healthy pools per species."""
    diseased, healthy = defaultdict(list), defaultdict(list)
    for r in records:
        metas = [CLASS_METADATA[c] for c in r["truth"]]
        species = {m["species"] for m in metas}
        if len(species) != 1:
            continue
        s = species.pop()
        sick = {m["condition"] for m in metas if not m["is_healthy"]}
        if not sick:
            healthy[s].append(r)
        elif len(sick) == 1:
            diseased[(s, sick.pop())].append(r)
    return diseased, healthy


def visit_sequence(pool, visits, rho, rng):
    """Sample visits; with probability rho a visit repeats the previous view exactly."""
    seq = [rng.choice(pool)]
    while len(seq) < visits:
        seq.append(seq[-1] if rng.random() < rho else rng.choice(pool))
    return seq


def single_image_call(record, species, threshold):
    """Baseline: any disease of the plant's species at or above threshold is a diagnosis."""
    return {
        d["condition"]
        for d in record["detections"]
        if d["species"] == species and not d["is_healthy"] and d["confidence"] >= threshold
    }


def engine_call(sequence, species, confirm):
    """Run the real engine over the visits; return the conditions it confirmed at any visit."""
    service = DossierService(store=MemoryStore())
    engine = DiagnosticEngine(service=service, confirm_confidence=confirm)
    service.register_plant("P", "bed", species=species)
    confirmed = set()
    for record in sequence:
        obs = service.submit_observation("P", detections=record["detections"])
        result = engine.evaluate("P", obs.observation_id)
        for d in result.diagnoses:
            if d.status == "confirmed":
                confirmed.add(d.possible_condition.removeprefix(f"{species} "))
    return confirmed


def proportion_ci(hits, n):
    """Wilson 95% interval."""
    if n == 0:
        return [0.0, 0.0]
    z, p = 1.96, hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
    return [max(0.0, centre - half), min(1.0, centre + half)]


def simulate(diseased, healthy, method, visits, rho, threshold, trials, seed):
    rng = random.Random(seed)
    healthy_keys = [k for k, v in healthy.items() if v]
    disease_keys = [k for k, v in diseased.items() if v]
    false_alarm = wrong = correct = 0

    for _ in range(trials):
        s = rng.choice(healthy_keys)
        seq = visit_sequence(healthy[s], visits, rho, rng)
        if method == "single":
            called = single_image_call(seq[0], s, threshold)
        else:
            called = engine_call(seq, s, threshold)
        false_alarm += bool(called)

    for _ in range(trials):
        s, condition = rng.choice(disease_keys)
        seq = visit_sequence(diseased[(s, condition)], visits, rho, rng)
        if method == "single":
            called = single_image_call(seq[0], s, threshold)
        else:
            called = engine_call(seq, s, threshold)
        correct += condition in called
        wrong += bool(called - {condition})

    return {
        "method": method,
        "visits": visits,
        "rho": rho,
        "threshold": threshold,
        "trials": trials,
        "false_alarm_rate": false_alarm / trials,
        "false_alarm_ci": proportion_ci(false_alarm, trials),
        "true_detection_rate": correct / trials,
        "true_detection_ci": proportion_ci(correct, trials),
        "wrong_condition_rate": wrong / trials,
        "wrong_condition_ci": proportion_ci(wrong, trials),
    }


def e3_repeat_sighting(records, trials=3000):
    diseased, healthy = image_pools(records)
    pools = {
        "healthy_species": {k: len(v) for k, v in healthy.items()},
        "disease_conditions": {f"{k[0]} {k[1]}": len(v) for k, v in diseased.items()},
    }

    main = [
        simulate(diseased, healthy, "single", 1, 0.0, 0.60, trials, 11),
        simulate(diseased, healthy, "single", 1, 0.0, 0.70, trials, 12),
        simulate(diseased, healthy, "repeat", 2, 0.0, 0.60, trials, 13),
        simulate(diseased, healthy, "repeat", 3, 0.0, 0.60, trials, 14),
        simulate(diseased, healthy, "repeat", 4, 0.0, 0.60, trials, 15),
    ]
    correlation = [
        simulate(diseased, healthy, "repeat", 3, rho, 0.60, trials, 20 + i)
        for i, rho in enumerate((0.0, 0.25, 0.5, 0.75, 1.0))
    ]
    sweep = []
    for i, threshold in enumerate((0.35, 0.45, 0.55, 0.60, 0.65, 0.75, 0.85)):
        sweep.append(simulate(diseased, healthy, "single", 1, 0.0, threshold, trials, 40 + i))
        sweep.append(simulate(diseased, healthy, "repeat", 3, 0.0, threshold, trials, 60 + i))
    for row in main + correlation:
        print("E3", row["method"], row["visits"], row["rho"], row["threshold"],
              round(row["false_alarm_rate"], 3), round(row["true_detection_rate"], 3),
              round(row["wrong_condition_rate"], 3), flush=True)
    return {"pools": pools, "main": main, "correlation": correlation, "sweep": sweep}


def e4_tags(items, trials=40):
    """Paste a tag at random spots on real leaf images at several sizes, with blur and noise."""
    reader = PlantTagReader()
    rng = np.random.default_rng(5)
    rows = []
    backgrounds = [cv2.imread(str(i[0])) for i in items[:40]]
    backgrounds = [cv2.resize(b, (512, 384)) for b in backgrounds if b is not None]

    for px in (16, 24, 32, 48, 64, 96, 128):
        for blur in (0, 3):
            hits = 0
            for t in range(trials):
                frame = backgrounds[t % len(backgrounds)].copy()
                marker = cv2.cvtColor(render_marker(int(1 + t % 40), size=200), cv2.COLOR_GRAY2BGR)
                # render_marker adds a border and a label; scale so the code itself spans px.
                scale = px / 200
                tag = cv2.resize(marker, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
                th, tw = tag.shape[:2]
                y = int(rng.integers(0, max(1, frame.shape[0] - th)))
                x = int(rng.integers(0, max(1, frame.shape[1] - tw)))
                frame[y:y + th, x:x + tw] = tag[: frame.shape[0] - y, : frame.shape[1] - x]
                if blur:
                    frame = cv2.GaussianBlur(frame, (blur, blur), 0)
                noisy = np.clip(frame.astype(np.int16) + rng.normal(0, 6, frame.shape), 0, 255).astype(np.uint8)
                found = reader.read(noisy)
                hits += bool(found and found["marker_id"] == 1 + t % 40)
            rows.append({"tag_px": px, "blur": blur, "read_rate": hits / trials, "trials": trials})
    print("E4", rows, flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--stages", default="e1,e2,e3,e4")
    args = parser.parse_args()

    RESULTS.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)

    items, unknown = load_test_split(Path(args.dataset))
    print("test images", len(items), "boxes", sum(len(i[1]) for i in items), "unknown", unknown, flush=True)
    detector = PlantDocDetector(DEFAULT_WEIGHTS_PATH)
    stages = args.stages.split(",")

    def save(name, value):
        (RESULTS / f"{name}.json").write_text(json.dumps(value, indent=2))

    save("dataset", {"images": len(items), "boxes": sum(len(i[1]) for i in items), "unknown_labels": unknown})
    if "e4" in stages:
        save("e4_tags", e4_tags(items))
    if "e2" in stages:
        save("e2_latency", e2_latency(items, detector))
    if "e1" in stages:
        save("e1_accuracy", e1_accuracy(items, detector))
    if "e3" in stages:
        cache = RESULTS / "detections_640.json"
        if cache.exists():
            records = json.loads(cache.read_text())
        else:
            records = collect_detections(items, detector, imgsz=640)
            cache.write_text(json.dumps(records))
        save("e3_repeat_sighting", e3_repeat_sighting(records))


if __name__ == "__main__":
    main()
