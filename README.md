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
├── actions/                     # 🤖 Action Manager (diagnosis → recorded robot action)
│   ├── manager.py               # propose / approve / execute / verify
│   └── tests/test_actions.py
│
├── hardware/                    # 🔌 Robot command interface
│   ├── robot.py                 # SimulatedRobot + BluetoothRobot (one ESP32)
│   └── tests/test_hardware.py
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
python3 -m unittest discover actions/tests
python3 -m unittest discover hardware/tests
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

The bridge only records what the camera saw. `DiagnosticEngine` decides what it means. On real detections the model's confidence barely separates right from wrong (precision stays near 0.73 from a 35% to an 80% cutoff), so the engine relies on agreement between **different views** of a plant:

1. Only detections of the plant's own species at or above `min_confidence` (35%) count. Other species are ignored and noted.
2. The evidence is the last `lookback` + 1 (4) distinct views since the plant was last sprayed. Frames without leaves and repeats of the same view do not count.
3. A view votes for a condition seen at `confirm_confidence` (60%) or higher.
4. A condition is **confirmed** with at least two votes, a strict majority of the views, and more votes than any rival. One image is never enough.
5. Rival diseases tied at two or more votes make the plant **uncertain**, and a person decides.
6. Status comes from the whole window, so one healthy or blurry view does not undo a diagnosis. A disease fades as healthy views outvote it.
7. High humidity is noted as context for humidity-favoured diseases. It never creates or confirms a diagnosis.

Two recordings of the same scene count once. For a demo, move the camera or zoom in between visits; holding it still will not confirm a disease.

| Plant status | Meaning |
|---|---|
| `diseased` | One condition has a clear majority of views |
| `uncertain` | Rival conditions are tied, so a person decides |
| `suspected_disease` | Seen now, or in at least half of recent views |
| `healthy` | Healthy leaves, and no disease in at least half of recent views |
| `needs_reinspection` | No usable leaves, and nothing already at risk |

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

## 🤖 Action Manager (`actions`) and Robot Interface (`hardware`)

After each recorded visit, the action manager proposes **one** next action for the plant and records why. Nothing moves until someone taps **Run on robot** on the phone.

| Plant status | Proposed action | Robot commands | Notes |
|---|---|---|---|
| `suspected_disease` | Inspect closer | arm → `inspect` | The next recorded visit verifies it, and can confirm the disease |
| `diseased` | Spray plant | arm → `spray`, spray 500 ms, arm → `home` | **Needs approval** before it can run |
| `needs_reinspection` | Reposition and retry | drive `back` 300 ms | Verified by the next visit |
| `healthy` | Move on to next plant | arm → `home`, drive `forward` 1000 ms | |
| `uncertain` | Ask a person to review | None | The operator marks it reviewed |

- Each plant keeps one open action; a new status replaces (supersedes) an old open action.
- After 2 inspections or 2 retries in a row, the robot stops and asks a person.
- After a spray, the plant is not sprayed again for 72 hours (a provisional value), and earlier sightings no longer count. If the disease is confirmed again after that, a person decides.
- If any robot command fails, the robot is told to stop and the action is marked `failed` with what had already run.
- The **STOP** button on the phone always sends a stop, even while other work is running.

### Connecting the real robot

The robot is one ESP32 on Bluetooth Classic serial, named `UGV_ESP32`. By default the live server uses a **simulated robot**. To use the real one:

1. Pair the laptop with `UGV_ESP32` in Windows Bluetooth settings.
2. Find its COM port: `python -m serial.tools.list_ports -v`
3. Start the server with that port:

```bash
python -m live --bt-port COM5
```

| Command | Meaning | In firmware? |
|---|---|---|
| `F:1000` `B:1000` `L:500` `R:500` | Timed drive, in ms | Yes |
| `S` | Stop | Yes |
| `V180` | Set speed, 0 to 255 | Yes |
| `A:HOME` `A:INSPECT` `A:SPRAY` | Move the arm to a pose | **Proposed, not yet** |
| `P:500` | Squeeze the spray trigger for 500 ms | **Proposed, not yet** |

The firmware sends no reply and silently ignores unknown commands, so "sent" does not prove the robot moved. Arm and spray steps are refused, and the action fails, until the firmware supports them. Then add `--has-arm`.

Every move sent from here has a time limit. DHT22 readings arrive as `sensor_data` lines; failed or simulated readings are never stored. A valid reading is saved with each visit, and high humidity (70% or more) is added as context for humidity-favoured diseases. It never creates or confirms a diagnosis.

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
python3 -m unittest discover dossier/tests && python3 -m unittest discover diagnostics/tests && python3 -m unittest discover vision/tests && python3 -m unittest discover live/tests && python3 -m unittest discover actions/tests && python3 -m unittest discover hardware/tests
```
