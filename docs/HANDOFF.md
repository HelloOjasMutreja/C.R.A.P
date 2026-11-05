# Project Handoff

Where C.R.A.P stands, for anyone picking this up next, human or AI. Last updated 2026-11-05.

**Hardware team: read [HARDWARE_TEAM_GUIDE.md](HARDWARE_TEAM_GUIDE.md) instead.**

## The project

An agricultural ground robot that visits plants, looks for disease, keeps a health record for each plant, and acts on what it finds.

The target design has **no laptop**. A Nothing Phone (2a) Plus rides on the rover as camera and brain, running a native Android app. One ESP32 is the body: motors, wheel encoders and DHT22, reached over Wi-Fi. The phone sends goals ("move 40 cm"), and the ESP32 carries them out with the encoders and replies.

## Status

| Phase | Status | Proven by |
|---|---|---|
| 1. Speed and heat on the phone | Done | Real phone: about 3 fps, 2.7 fps after 20 minutes |
| 2. Live camera detection | Done | Real phone |
| 3. Plant tags, distance, direction | Built | Self-test image on the phone. **No real printed tag yet** |
| 4. Records and rules on the phone | Done | 3,008 visits match the Python exactly; a real visit on the phone |
| 5. Robot link over Wi-Fi | Built | Tests, and the phone against a simulator over USB. **No real ESP32 or real Wi-Fi yet** |
| 6. Mission loop | Built | 200 simulated fields; on the phone, scan and STOP only. **No real rover, and no full approach on a phone** |
| 7. Arm, spray, field test | Not started | Needs hardware and firmware |

## Where things are

| Path | What it is |
|---|---|
| `android/` | **The real product.** Native Android app |
| `android/app/src/main/java/com/crap/speedtest/` | `LiveActivity` (screen), `Mission` (planner), `WifiRobot` and `RoverNetwork` (ESP32 link), `DiagnosticEngine`, `ActionManager`, `PlantRecords`, `TagReader`, `Detector` |
| `firmware/AgriUGV_ESP32/` | ESP32 firmware, fixed version |
| `firmware/simulate_esp32.py` | Stand-in ESP32 for testing the app |
| `firmware/drive_test.py` | Drive the rover by hand from a laptop |
| `diagnostics/`, `actions/`, `dossier/` | Python versions of the rules. **Source of truth for behaviour** |
| `vision/` | Python detector and YOLO weights |
| `live/` | Older laptop web demo. Superseded, but `live/make_tags.py` and `live/markers.py` are still used |
| `hardware/robot.py` | Older laptop Bluetooth link. **Superseded by Wi-Fi** |
| `docs/paper/` | Conference paper draft and experiments |

## Decisions, and why

- **No laptop.** The team's direction. The ESP32 cannot run YOLO, so the phone does.
- **Wi-Fi, not Bluetooth.** The team's newest firmware uses it, and it already had distance and turn commands with replies. Chats from before 2026-11-05 mention Bluetooth; they are out of date.
- **CPU, not GPU.** ONNX Runtime with XNNPACK, 4 threads, 480 px gives the correct answer. TFLite on the GPU ran 3 times faster but found 6 of 8 leaves with much lower scores, took 2 minutes to start, and full precision never finished in 14 minutes. Do not switch without re-checking accuracy.
- **480 px input.** Matches 800 px accuracy at under half the time.
- **Species comes from the plant's record, not the model.** The model knows 13 species and mislabels others.
- **The mission owns movement near plants.** It never runs the rules' "move on" drive, which is blind and would hit the plant. It never sprays.
- **STOP latches.** A queued move must not run after STOP. Moves are allowed again only when a person asks.
- **Detector confidence is weak evidence.** Agreement across distinct views is what counts. See the rules in `diagnostics/engine.py`.

## Build and test

This Windows laptop needs these settings. Android Studio's bundled Java 25 is too new for Gradle 8.9.

```bash
export JAVA_HOME="/c/Users/Ojas/.jdks/jbr-21.0.11" GRADLE_USER_HOME="D:/GradleHome"
GRADLE=$(ls -d /d/GradleHome/wrapper/dists/gradle-8.9-bin/*/gradle-8.9/bin)/gradle.bat
cd android
"$GRADLE" :app:testDebugUnitTest      # 35 tests
"$GRADLE" :app:assembleDebug -Prover  # slim APK for the team
```

- **Model files are not in git.** Create them with `python android/export_model.py`, and `android/export_tflite.py` for the GPU test (Python 3.12, `android/.export-venv`).
- **Parity fixtures:** after changing the Python rules, run `python android/make_parity_fixtures.py`. The Kotlin must then be changed to match.
- **Firmware compile check:** `PLATFORMIO_CORE_DIR=D:/platformio /d/platformio/venv/Scripts/pio.exe run -d firmware`
- **Test the phone without hardware:**
  ```bash
  python firmware/simulate_esp32.py
  adb reverse tcp:3333 tcp:3333
  adb shell am start -n com.crap.speedtest/.LiveActivity --es robot_host 127.0.0.1
  ```
- **Tag checks without a camera:** `python android/check_tags.py`
- **Tests over USB:** `adb shell am start -n com.crap.speedtest/.MainActivity --es run heat` (also `gpu`, `speed`, `tag`). Results appear in `adb logcat -s CRAP:I`. `uiautomator` hangs while the camera runs, so tap by coordinates from a screenshot.

## Known gaps

0. **False tags are reduced, but not ruled out.** The phone once reported `PLANT_017` at 474 cm with no tag present. `TagReader` now decodes strictly and rejects tiny or misshapen tags, and `TagTracker` needs 3 of the last 4 frames. On simulated clutter (`android/check_tags.py`) false frames fell from 37 to 23 to 0 in 3,000, but those frames are independent: a misread from something stationary could repeat and pass. Accepting only expected plant IDs would close this.
0a. **A real tag has never been read through the camera.** Only the test image and simulated views have. A test on 2026-11-05 logged no tags in 700 live frames, but it is unknown whether a tag was shown. **Check this first:** the mission depends on it.
0b. **Tag range is limited by the strict checks.** In simulation a 10 cm tag reads head-on to about 2 m, at 30 degrees to about 1.6 m, and at 50 degrees to about 1.2 m. Beyond that a larger tag is needed.
1. **`RoverNetwork` has never run.** Holding the phone on a Wi-Fi network with no internet is the most likely thing to need a fix. USB testing bypassed it.
2. **The firmware has never run on a board.** It only compiles.
3. **Real tag distance is unmeasured.** It assumes a 10 cm tag and uses the camera's reported focal length.
4. **Disease has not been seen on the phone.** Only healthy leaves and an ornamental plant.
5. **Motion constants are guesses:** 30 cm/s and 45 degrees/s in `WifiRobot`, and everything in `config.h`.
6. **Live frames take about 475–530 ms,** slower than the 316 ms bench result, with one 1,180 ms frame after a visit. Cause unknown.
7. **"Move on" by hand no longer moves the rover.** It is marked done, and a person moves it. The rules' forward drive remains in `PLANS` for parity with the Python.
8. **Mission settings are unproven:** 40 cm standoff, 6 degree aim, 600 cm travel limit.
9. **No obstacle detection.** The rover needs a person standing by.
10. **The app is locked to portrait,** and the mount is undecided.
11. **The APK is debug-signed.** Fine for the team, not for a store.
12. **The Wi-Fi password `agriugv123` is in a public repo.** Change it for anything beyond the demo.
13. **The paper is out of date.** It describes the older repeat-sighting rule and the laptop design. Its numbers and claims need updating before submission.
14. **The Android package is still called `com.crap.speedtest`** from its first version.

## Next steps, in order

0. Show a printed tag to the phone's camera and confirm the cyan outline and distance (gap 0a).
1. Flash the firmware on the real ESP32 and test with `drive_test.py`.
2. Connect the phone over real Wi-Fi, and fix `RoverNetwork` if needed.
3. Calibrate `config.h`, then the motion constants in `WifiRobot`.
4. Test a printed tag at measured distances, and correct `TAG_SIZE_METRES` or the focal length.
5. Run a supervised one-plant mission on the real rover, and tune `MissionSettings`.
6. Test real diseased leaves through the phone. A real suspected-to-confirmed run is needed.
7. Add arm and spray to the firmware, using the commands in the hardware guide, then set `hasArm` in `WifiRobot` and map them. Keep spraying behind approval.
8. Add a way to approve spraying without touching a phone on a moving rover: a second phone, or approval before the run.
9. Add a remote view for demos, as the screen rides on the rover.
10. Collect real field photos, measure accuracy, and retrain if needed. The detector is the accuracy ceiling.
11. Update the paper to match the final design and results.
