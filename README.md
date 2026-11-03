# 🌿 C.R.A.P (Crop Robotic Autonomous Platform)

An autonomous robotic platform for real-time crop disease detection, diagnosis tracking, and action lifecycle management.

---

## 🏗️ Architecture

```text
C.R.A.P/
├── dossier/                     # 📋 Plant Health Record System
│   ├── models.py                # Plant, Observation, Diagnosis, Action dataclasses
│   ├── service.py               # DossierService API (register, observe, diagnose, act)
│   ├── store.py                 # JSON persistent store with package-relative data path
│   └── tests/test_dossier.py    # Unit tests for Dossier lifecycle
│
├── vision/                      # 👁️ Computer Vision & Disease Perception
│   ├── detector.py              # PlantDocDetector (YOLOv11s inference & bounding boxes)
│   ├── bridge.py                # DossierPerceptionBridge (records detections as observations)
│   ├── weights/best.pt          # Fine-tuned YOLOv11s weights (29 PlantDoc classes)
│   ├── sample_images/           # Verification samples
│   └── tests/test_vision.py     # Unit tests for vision and bridge
│
├── diagnostics/                 # 🩺 Rule-based Diagnostic Engine
│   ├── engine.py                # DiagnosticEngine (observations → diagnoses + plant status)
│   └── tests/test_diagnostics.py
│
├── live/                        # 📱 Live phone camera feed (laptop runs YOLO)
│   ├── server.py                # FastAPI app: live detection WebSocket + record-visit API
│   ├── markers.py               # ArUco plant tags (marker 7 → PLANT_007)
│   ├── make_tags.py             # Printable plant tags
│   ├── certs.py                 # Self-signed HTTPS so the phone camera works
│   ├── static/                  # Phone page (HTML/CSS/JS)
│   └── tests/test_live.py
│
├── docs/brainstorm/             # 💡 Whole-project ideas (parked for after the demo)
├── demo_pipeline.py             # 🚀 End-to-end perception-to-dossier demonstration
├── requirements.txt             # Python dependencies
└── .gitignore
```

---

## ⚡ Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Automated Demo
Runs YOLO inference on a sample plant leaf, logs the detections as an observation in the Dossier, evaluates it with the diagnostic engine, and saves an image with labeled bounding boxes:
```bash
python3 demo_pipeline.py
```

### 3. Run Test Suite
```bash
python3 -m unittest discover dossier/tests
python3 -m unittest discover diagnostics/tests
python3 -m unittest discover vision/tests
python3 -m unittest discover live/tests
```

---

## 🔍 Vision Module (`vision`)

The vision system utilizes a fine-tuned **YOLOv11s** model trained on the **PlantDoc** object detection dataset across **29 classes** spanning healthy plant foliage and leaf diseases (Apple Scab, Corn Leaf Blight, Potato Blight, Tomato Early Blight, Yellow Leaf Curl, and more).

### Python Usage

```python
from vision import PlantDocDetector, DossierPerceptionBridge
from dossier import DossierService

# 1. Direct Object Detection
detector = PlantDocDetector()
detections = detector.predict("path/to/leaf.jpg", conf=0.30)

for d in detections:
    print(f"Species: {d.species} | Condition: {d.condition} | Conf: {d.confidence*100:.1f}%")

# 2. Record the detections as an observation in the Dossier
service = DossierService()
bridge = DossierPerceptionBridge(service=service, detector=detector)

result = bridge.process_image(
    plant_id="PLANT_001",
    image_source="path/to/leaf.jpg",
    location="Sector_A",
    conf_threshold=0.30,
)

print("Logged Observation:", result["observation"].observation_id)

# 3. Evaluate the observation against the plant's history
from diagnostics import DiagnosticEngine

engine = DiagnosticEngine(service=service)
evaluation = engine.evaluate("PLANT_001")

print("Plant Status:", evaluation.plant_status)
print("Diagnoses:", [(d.possible_condition, d.status) for d in evaluation.diagnoses])
```

---

## 🩺 Diagnostic Engine (`diagnostics`)

The bridge only records what the camera saw. `DiagnosticEngine` decides what it means, using rules that are written into every diagnosis's evidence:

1. Only detections of the plant's own species at or above `min_confidence` (default 35%) count. Other species are ignored and noted.
2. A condition seen in one observation is only **suspected**. One image is never enough to confirm a disease.
3. It becomes **confirmed** when it is seen at `confirm_confidence` (default 60%) or higher both now and in at least one of the last `lookback` (default 3) earlier observations.
4. Healthy leaves in the same image, and earlier observations that did not show the condition, are recorded as contradicting evidence.

| Plant status | Meaning |
|---|---|
| `diseased` | At least one confirmed condition |
| `suspected_disease` | At least one suspected condition |
| `healthy` | Only healthy leaves of the plant's species |
| `needs_reinspection` | No usable leaves in the image |


---

## 📱 Live Phone Feed (`live`)

Your phone becomes the robot's eye. The phone streams its camera to the laptop, the laptop runs YOLO, and the phone draws the boxes over its own live video, so the video stays smooth even when detection runs at a few frames per second.

```bash
python -m live
```

1. Connect the phone and laptop to the **same Wi-Fi**. If the venue Wi-Fi blocks devices from talking to each other, connect the laptop to the **phone's hotspot** instead.
2. Open the `https://…:8443` address the laptop prints, in Chrome on the phone.
3. The phone warns about the certificate (it's self-signed): tap **Advanced → Proceed**. You only do this once per network address.
4. Tap **Start camera** and allow camera access. If Windows asks about the firewall, allow Python on private networks.

On screen:
- **Live boxes**: green for healthy leaves, red for disease, with confidence.
- **Verdict banner**: a disease is shown only if it appears in 3 of the last 8 frames, so one-frame flickers don't count.
- **Plant record panel**: pull it up to see status, visits, and the engine's evidence for and against.
- **Record button**: saves a full-resolution photo as a visit, then runs the diagnostic engine. A first sighting gives *suspected*; recording again on a later visit can give *confirmed*.
- **Plant tags**: print tags with `python -m live.make_tags --count 12` and put one on a stake by each plant. When a tag is in view, the page selects that plant automatically (marker 7 → `PLANT_007`). You can also pick or add plants by hand from the top-right chip.

Live frames are never saved; only tapped visits go into the dossier (photos are stored in `dossier/data/images/`). Use `--conf 0.3` to change the detection threshold, or `--no-https` to test on the laptop itself at `http://localhost:8443`.

---

## 🏷️ Supported Plant & Disease Classes (29 Classes)

- **Apple**: Apple Scab, Apple Rust, Healthy Leaf
- **Bell Pepper**: Bacterial Spot, Healthy Leaf
- **Blueberry**: Healthy Leaf
- **Cherry**: Healthy Leaf
- **Corn**: Gray Leaf Spot, Leaf Blight, Common Rust
- **Peach**: Healthy Leaf
- **Potato**: Early Blight, Late Blight, Healthy Leaf
- **Raspberry**: Healthy Leaf
- **Soybean**: Healthy Leaf
- **Squash**: Powdery Mildew
- **Strawberry**: Healthy Leaf
- **Tomato**: Early Blight, Late Blight, Septoria Leaf Spot, Bacterial Spot, Mosaic Virus, Yellow Leaf Curl Virus, Leaf Mold, Two-Spotted Spider Mite, Healthy Leaf
- **Grape**: Black Rot, Healthy Leaf

---

## 🧪 Testing

Both test suites run independently and verify full data persistence across sessions:
```bash
python3 -m unittest discover dossier/tests && python3 -m unittest discover diagnostics/tests && python3 -m unittest discover vision/tests && python3 -m unittest discover live/tests
```
