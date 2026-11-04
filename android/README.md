# C.R.A.P Rover (Android)

The app that runs on the phone riding on the rover: live camera detection, plant tags, plant records, decisions, the link to the ESP32, and missions. To install it without building, see [the hardware guide](../docs/HARDWARE_TEAM_GUIDE.md). Build details are in [the handoff](../docs/HANDOFF.md).

The steps below build it yourself. Its **Tests** screen measures model speed and heat.

## Run it

1. Install [Android Studio](https://developer.android.com/studio).
2. If `app/src/main/assets` has no model files, create them from the repository root. The TensorFlow Lite step needs a Python 3.12 environment with `ultralytics`, `tensorflow-cpu`, `tf_keras`, `onnx2tf`, `onnxruntime`, `sng4onnx`, `onnx_graphsurgeon` and `ai-edge-litert`, kept in `android/.export-venv`:
   ```bash
   python android/export_model.py
   android/.export-venv/Scripts/python.exe android/export_tflite.py
   ```
3. In Android Studio, choose **Open** and select this `android` folder. Wait for the Gradle sync to finish.
4. On the phone, turn on developer options: open **Settings**, search for **Build number**, and tap it seven times.
5. In **Developer options**, turn on **USB debugging**, then connect the phone by USB and allow the laptop.
6. Choose the phone in Android Studio's device list and press **Run**.

## Use it

1. Unplug the phone, stop any screen recording and close other apps.
2. Tap **Run speed test**. It should take a few minutes.
3. Tap **Run GPU test**. If the app closes, the GPU driver cannot run this model.
4. Tap **Run 20-minute heat test**. It uses the fastest option found.
5. Tap **Share results** to send the text.

Every row of the speed test should find 7 or 8 boxes. A row that runs fast with a different count is not trustworthy, because that provider is giving wrong answers.
