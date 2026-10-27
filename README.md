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
│   ├── bridge.py                # DossierPerceptionBridge (auto-submits to Dossier)
│   ├── weights/best.pt          # Fine-tuned YOLOv11s weights (29 PlantDoc classes)
│   ├── sample_images/           # Verification samples
│   └── tests/test_vision.py     # Unit tests for vision and bridge
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
Runs YOLO inference on a sample plant leaf, overlays labeled bounding boxes, and logs structured observations and diagnoses into the Dossier:
```bash
python3 demo_pipeline.py
```

### 3. Run Test Suite
```bash
python3 -m unittest discover dossier/tests
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

# 2. Automated Bridge to Dossier
service = DossierService()
bridge = DossierPerceptionBridge(service=service, detector=detector)

result = bridge.process_image(
    plant_id="PLANT_001",
    image_source="path/to/leaf.jpg",
    location="Sector_A",
    conf_threshold=0.30,
)

print("Logged Observation:", result["observation"].observation_id)
print("Logged Diagnoses:", [d.possible_condition for d in result["diagnoses"]])
```

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
python3 -m unittest discover dossier/tests && python3 -m unittest discover vision/tests
```
