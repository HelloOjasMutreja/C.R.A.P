# C.R.A.P — Whole-Project Brainstorm (2026-11-03)

Collected ideas for the whole robot. **Only the phone live-vision part is being built now**; everything else here is parked for after the 4 November demo.

Labels: `[known]` from the code or the team, `[assumption]` our guess, `[estimate]` rough number, `[unverified]` a claim not yet checked against outside sources.

---

## 1. What the project really is

A ground robot that **visits the same plants again and again**, looks at them, keeps a medical-style chart per plant, and acts on what it finds.

Split today `[known]`:
- 2 people on the 4-wheel chassis (ESP32 motor control)
- 2 people on the robotic arm
- 1 person on all software: YOLO (PlantDoc, 29 classes), plant dossier, diagnostic engine

Missing in software `[known]`: action manager, hardware command link, camera workflow, a screen to show results.

## 2. Hidden insights

1. **The dossier is the product, not the detector.** Leaf-disease YOLO models are common `[unverified]`. A robot that *remembers each plant* and only confirms a disease after repeat sightings is the part that's different: a doctor's chart instead of a single photo. Every design choice should feed that memory.

2. **Plant identity is the real bottleneck.** The memory only works if the robot knows "this is PLANT_001 again". GPS is too coarse between neighbouring plants `[assumption]`, and visual re-identification of leaves is hard. The cheap, robust answer is **a printed ArUco tag on a stake at each plant**. The camera reads the tag, and the plant is identified with no extra hardware. OpenCV already reads ArUco tags.

3. **The arm's best first job is moving the camera, not spraying.** If the phone or camera sits on the arm, "take a closer look" becomes a physical action. The arm moves to an inspection pose, and the engine gets a second, closer observation. That is exactly what the engine needs to go from *suspected* to *confirmed*. This ties the arm team, the camera and the engine into one loop.

4. **The phone has more sensors than the robot.** It has a camera, IMU, compass, GPS, Wi-Fi, Bluetooth LE, a battery and a screen. Chrome on Android can talk Bluetooth LE to an ESP32 straight from a web page (Web Bluetooth) `[assumption: needs testing on your phone]`. So the phone can grow from "eye" into "eye plus remote control" with no app install.

5. **PlantDoc models are trained on internet photos.** Field accuracy will be lower than the training numbers suggest `[assumption]`. The repeat-sighting rule in the engine is our defence, and so is the close-look action from insight 3. **For the demo, have printed or on-screen photos of diseased leaves ready**, since the sample image and most real plants nearby will be healthy.

## 3. The robot's loop, broken into parts

| Part | Input → Output | Status | Weak point |
|---|---|---|---|
| Drive | command → wheels move | hardware team | drift; no position feedback |
| Find next plant | route → stops at plant | not started | knowing *which* plant |
| Identify plant | image → plant ID | **ArUco idea (this doc)** | tag missing or dirty |
| Look | camera → frames | **phone page (building now)** | Wi-Fi, lighting |
| Detect | frame → leaf boxes | done (YOLO) | field accuracy |
| Remember | detections → observation | done (dossier) | — |
| Judge | history → diagnosis + status | done (engine) | thresholds untuned |
| Decide | diagnosis → action | **not started** | unsafe actions |
| Act | action → arm/drive command | **not started** | no agreed command interface |
| Verify | new observation → action result | partly (field exists) | — |

**The highest-leverage gap is "Decide + Act".** It turns a camera app into a robot.

## 4. Candidate architectures (different core ideas)

**A. Laptop hub** (core idea: central compute)
The phone is the camera and screen. The laptop runs YOLO, the dossier, the engine and the action manager. ESP32s are simple actuators on the same Wi-Fi, each exposing a few HTTP commands.
✔ fastest to build, easy to debug, reuses everything. ✘ needs a laptop and Wi-Fi in the field.

**B. Phone-native edge** (core idea: on-device AI)
YOLO is exported to TFLite or NCNN and runs inside an Android app. The phone talks to the ESP32 over Bluetooth LE, with no laptop.
✔ field-ready, cheap, one device. ✘ app development, model export, slower model; days of work, not hours.

**C. Fiducial route** (core idea: change the field, not the robot)
Plants get ArUco stakes, and the robot follows a line or tape along the row, stopping at each tag. Navigation and identity become trivial.
✔ very reliable for demos and greenhouses. ✘ needs field preparation; not "true" autonomy.

**D. Farmer-driven scout** (core idea: human in the loop)
The farmer drives the robot from the phone like a game controller, while the software watches, records and suggests. The robot is a smart scouting cart.
✔ realistic for adoption; no autonomy risk. ✘ less impressive as robotics.

**E. Field-trained model** (core idea: data network effect)
Every visit saves frames. Low-confidence frames are queued for a person to label, and the model is retrained on *your* field. It gets better the more it drives.
✔ long-term advantage, fixes the accuracy gap from insight 5. ✘ needs a labeling routine and training time.

## 5. Comparison (hackathon/demo weighting)

Weights: demo wow 25%, feasibility by Nov 4 25%, reliability 20%, novelty 15%, path to real use 15%. Scores 1–5 `[estimate]`.

| | Wow | Feasible | Reliable | Novel | Real use | **Total** |
|---|---|---|---|---|---|---|
| A Laptop hub | 4 | 5 | 4 | 3 | 3 | **3.95** |
| B Phone-native | 4 | 1 | 3 | 3 | 5 | **3.05** |
| C Fiducial route | 3 | 3 | 5 | 3 | 3 | **3.40** |
| D Farmer-driven | 3 | 4 | 4 | 2 | 4 | **3.50** |
| E Field-trained | 2 | 1 | 3 | 4 | 5 | **2.75** |

A wins on feasibility. B and E win on the long term. C and D are combinable with A.

## 6. Recommended direction (portfolio)

- **Tomorrow (Nov 4): A + D.** The phone shows a live detection feed. You drive the robot manually or by teammate control, tap to record a visit, and the dossier and engine update live on the phone. Use the printed diseased-leaf photos to show disease detection and the suspected → confirmed flow on a second visit.
- **Next 2–4 weeks: A + C + insight 3.** Add ArUco stakes, the arm as camera positioner, the action manager and the ESP32 HTTP commands. The robot visits a tagged row, looks closer at suspicious leaves, and records what it did.
- **Moonshot: B + E.** On-phone model, no laptop, retrained on the team's own field data.

## 7. Blueprint for the parked parts

### Action manager (next software piece)
Reads the engine result and proposes one action. It records the action through `DossierService.record_action` with a reason, then records the outcome and the observation that verified it.

| Engine says | Proposed action | Executes |
|---|---|---|
| `suspected_disease` | `inspect_closer` | arm → inspection pose, capture again |
| `diseased` (confirmed) | `flag_plant` (later: `spot_treat`) | arm marker / alert on phone |
| `needs_reinspection` | `reposition_and_retry` | small drive move, capture again |
| `healthy` | `move_on` | drive to next plant |

Safety rule: anything that sprays or touches a plant stays `proposed` until a human taps "approve" on the phone.

### ESP32 command contract (to agree with the hardware teams)
Both ESP32s join the same Wi-Fi as the laptop and expose plain HTTP. You can test from any browser:

```
GET /drive?cmd=forward|back|left|right|stop&ms=500   → {"ok":true}
GET /arm?pose=home|inspect|flag                       → {"ok":true,"pose":"inspect"}
GET /status                                           → {"battery":7.4,"busy":false}
```

Rules: every move has a time limit (`ms`), `stop` always wins, and the ESP32 stops on its own if it hears nothing for 2 s (a dead-man switch). The laptop side gets a small `hardware/` module with a **simulated** version first, so the software can be tested before the robot exists.

### Phone → ESP32 later
Path 1 (simplest): phone → laptop → ESP32 over Wi-Fi HTTP, as above.
Path 2 (no laptop): phone page → ESP32 over Web Bluetooth. Worth a spike once the ESP32 firmware is stable.

## 8. Risks

| Risk | Mitigation |
|---|---|
| Venue Wi-Fi blocks phone-to-laptop traffic | Laptop joins the **phone's hotspot**; the page still works |
| Phone refuses camera on plain `http://` | Serve HTTPS with a self-signed certificate; accept the warning once |
| Windows firewall blocks the server | Allow Python on private networks when prompted |
| CPU inference too slow | Smaller frames (480 px), only send the next frame after the last result; video stays smooth because boxes are drawn over live video |
| No diseased plants on demo day | Printed or on-screen diseased leaf photos |
| Hardware not ready | Demo the vision → dossier → engine loop on its own; it doesn't depend on the robot |
| Engine thresholds wrong | Tune on real field images after the demo |

## 9. Open questions (to answer with data, not opinion)
- What is the model's real accuracy on your plants? Collect about 100 field photos and measure.
- How many frames per second does the laptop manage? The phone page shows it live.
- Does Web Bluetooth work between your phone and the ESP32? This needs a one-hour spike.
- Is the arm strong and steady enough to carry a phone? Ask the arm team for its payload limit.

*Prior-art and novelty claims above are unverified; no outside research was done for this pass.*
