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
python3 -m unittest discover dossier/tests && python3 -m unittest discover diagnostics/tests && python3 -m unittest discover vision/tests
```
