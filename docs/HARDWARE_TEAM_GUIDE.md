# Hardware Team Guide

How to get the rover moving with the phone app. Follow the steps in order, and keep the wheels off the ground until step 6.

## How it fits together

```
Phone on the rover (the brain)              ESP32 (the body)
camera, YOLO, plant tags, records,  --Wi-Fi-->  motors, wheel encoders,
diagnosis, deciding where to go     <--Wi-Fi--  DHT22
```

- The phone says "move 40 cm" or "turn 15 degrees". The ESP32 does it using the encoders, then replies.
- **The phone connects over Wi-Fi, not USB.** The ESP32 makes its own network called `AgriUGV`. USB is only for loading firmware onto the ESP32 from a laptop.
- The laptop is not needed once the rover is running.

## What you need to change

**Use the firmware in this repo: [`firmware/AgriUGV_ESP32`](../firmware/AgriUGV_ESP32).** Do not flash an older copy from Downloads or a chat. It is the team's firmware with these fixes:

| Fix | Why it matters |
|---|---|
| Motors stop after 1 second with no commands | A frozen app or lost Wi-Fi could leave the rover driving |
| Move timeout corrected | It was 10 times too long: about 115 seconds for 1 metre |
| Move stops as `STALLED` if the encoders go quiet for 1.5 seconds | A loose encoder wire would otherwise keep the motors running |
| Tiny moves reply `TOO_SMALL` | They could hang, or restart a cancelled move |
| A new connection replaces a dead one | The phone could not reconnect after a Wi-Fi drop |
| A failed DHT22 reports no reading | It kept sending old values as if they were current |
| 1 ms filter on encoder pulses | Motor noise could count as extra pulses |

It compiles for the ESP32, but **it has never run on a real board**, so expect to find problems. Please report them.

### Things only you can do
1. **Check the wiring against the pins below.** Older chats used other pins.
2. **Tell us if the rover uses one L298N or two.** This firmware drives one, with two motors in parallel on each side. Its README warns that can exceed the L298N's safe current. If you use two, `MotorController.cpp` needs changing.
3. **Measure and set the values in `config.h`** (step 5). They are examples.
4. **Fit an emergency power cut-off.** There is no obstacle detection.
5. **Check the power.** Four AA batteries may not drive this rover. Use a suitable battery for the motors, and never connect it to the ESP32's 3.3 V pin.
6. **Use a classic ESP32** such as ESP32-WROOM-32.

### Pins

| Part | ESP32 pin |
|---|---|
| L298N ENA, IN1, IN2 (left motors, OUT1/OUT2) | GPIO 25, 26, 27 |
| L298N ENB, IN3, IN4 (right motors, OUT3/OUT4) | GPIO 14, 32, 33 |
| Left encoder OUT | GPIO 34 |
| Right encoder OUT | GPIO 35 |
| DHT22 OUT (+ to 3.3 V, - to GND) | GPIO 4 |

- Remove the ENA and ENB jumpers on the L298N.
- Connect all grounds together.
- GPIO 34 and 35 have no internal pull-ups. If your encoder output needs one, add it to 3.3 V, never 5 V.

## Step 1: Flash the ESP32

1. Install Arduino IDE 2 and the **esp32 by Espressif Systems** board package.
2. Install the libraries **DHT sensor library**, **Adafruit Unified Sensor** and **ArduinoJson** (version 7).
3. Open `firmware/AgriUGV_ESP32/AgriUGV_ESP32.ino`.
4. Select **ESP32 Dev Module** and your COM port, then upload. If it fails, hold BOOT as the upload starts.
5. Open Serial Monitor at 115200. You should see `UGV controller ready`.

`firmware/AgriUGV_ESP32/README_FLASHING.txt` has more detail.

## Step 2: Test the motors from a laptop

**Raise the wheels first.**

1. Connect the laptop to the Wi-Fi network `AgriUGV` (password `agriugv123`).
2. Run:
   ```bash
   python firmware/drive_test.py
   ```
3. Type `f 20`, then `b 20`, `r 90`, `l 90`. Each move should end with `robot: COMPLETE`.

| You see | It means |
|---|---|
| `STALLED` | No encoder pulses. Check encoder wiring and power |
| Wheels spin the wrong way | Set `LEFT_MOTOR_INVERTED` or `RIGHT_MOTOR_INVERTED` in `config.h` |
| `f 20` turns the rover | One side is wired backwards |
| `TIMEOUT` | The move never finished. Check the encoders |
| Cannot connect | The laptop is not on `AgriUGV`, or the ESP32 is off |

Also test the safety stop: start `f 100`, then switch off the laptop's Wi-Fi. The wheels should stop within about a second.

## Step 3: Install the phone app

1. Get `crap-rover-0.1.apk` from Ojas, or from the [Releases page](https://github.com/HelloOjasMutreja/C.R.A.P/releases) if it has been published there, and copy it to the phone.
2. Open it, and allow installing from this source when asked.
3. Open **C.R.A.P Rover** and allow the camera.

It is built for 64-bit Android phones and tested only on a Nothing Phone (2a) Plus.

## Step 4: Connect the phone to the rover

1. Power on the rover.
2. Connect the phone to the `AgriUGV` Wi-Fi. If the phone warns there is no internet, choose to **stay connected**.
3. Open the app. It should show **Robot connected** near the top left. This can take a few seconds.

If it stays "Robot not connected", turn off mobile data and reopen the app. Please tell us if that was needed, because this link has only been tested with a simulator.

## Step 5: Calibrate

With the wheels on the ground, in an open space, use `drive_test.py`:

- **Distance:** run `f 100` and measure how far it went. Set `ENCODER_PULSES_PER_WHEEL_REV` in `config.h` to its current value × (100 ÷ distance moved in cm), after first entering your measured `WHEEL_DIAMETER_CM`.
- **Turning:** run `r 360`. If it turned too little, lower `TRACK_WIDTH_CM`; if too much, raise it. Measure the real track width first, as a starting point.
- Flash again and repeat until it's close. Each pulse is only about 1 cm or 4.7 degrees, so do not expect better.

## Step 6: Plant tags and the phone mount

1. Print tags. Each one identifies a plant: marker 7 is `PLANT_007`.
   ```bash
   python -m live.make_tags --count 12 --out markers
   ```
2. **Print so the black square is exactly 10 cm wide.** The app measures distance from this. A different size gives wrong distances, unless `TAG_SIZE_METRES` in `TagReader.kt` is changed.
3. Put each tag on a stake beside its plant, facing the rover's path, at about camera height.
4. Mount the phone upright (portrait), facing forward, firmly, on the rover's centre line.
5. Check: hold a tag 1 metre from the camera. The app should show a cyan outline, the plant ID and about `100 cm`.
   **Please report this result.** A real printed tag has not been tested through the camera yet.
6. **Hang each tag near the camera's height:** within about 15 cm if the phone is upright, or 10 cm if it is sideways. A tag much higher or lower leaves the picture as the rover closes in.
7. Keep tags within about 1.5 metres and facing the rover. A 10 cm tag is rejected if it looks too small or too angled. The app needs about 2 seconds of steady view to trust a tag.

## Mounting the phone upright or sideways

Either works, and there is nothing to set. The app turns with the phone.

- **Fit the phone in its mount before starting a mission.** The screen locks to its current direction when a mission starts, so that a bump can't swap left and right.
- Check the picture on screen is the right way up before you start.
- Sideways gives the rover a wider view, but a shorter one.

## Step 7: Run a mission

**Stay within reach of the power cut-off.** The rover cannot see obstacles.

**Known problem:** false tag readings are now much rarer, but still possible, and a mission could drive towards one. Use an open space, and be ready with STOP.

1. Place a tagged plant about 1 metre away, and no more than 1.5 metres.
2. In the **Plants to visit** box, type the tag numbers in this field, like `7` or `1-5, 7`. The rover ignores every other tag. The app remembers the list.
3. Tap **Start mission**.
4. The rover turns to find a tag, drives to about 40 cm from it, records a visit, and backs away. It looks for the next listed tag and stops when it finds none.
5. Red **STOP** cancels everything at any time.

What the buttons do:
- **Record visit:** saves one visit from where the rover is, without moving.
- **Run on robot / Approve / Skip:** act on the proposed next step. For "Move on", the button says **Mark done** and the rover does not move.
- **Tests:** speed tests. Only the 480 px option works in this build.

## Control it from a second phone

Once the phone is mounted, you can't reach its screen. Use a second phone or laptop:

1. Join it to the `AgriUGV` Wi-Fi.
2. Read the address and PIN from the rover phone's screen, like `http://192.168.4.2:8080 PIN 123456`. The PIN changes each time the app starts.
3. Open the address in a browser. You get the live view, a big **STOP**, the plant's status, and mission buttons.
4. **STOP needs no PIN.** Starting a mission and approving actions do.
5. A mission started from this page stops by itself if the page closes or the second phone sleeps, so keep its screen on.

This has not been tried over real Wi-Fi yet, so please report whether it works.

Leaving the app on the rover phone, such as for a call, stops the rover.

## Not built yet: arm and spray

The firmware has no arm or spray commands, so "Inspect closer" and "Spray plant" show as **Failed** if run by hand. That is deliberate. A mission gets a closer view by driving instead, and never sprays.

To add them, the firmware needs these commands, replying `COMPLETE` when finished:

```json
{"cmd":"ARM","pose":"home"}
{"cmd":"ARM","pose":"inspect"}
{"cmd":"ARM","pose":"spray"}
{"cmd":"SPRAY","ms":500}
```

The planned design is four servos on a PCA9685, with a servo squeezing a spray bottle trigger. Spraying must always need a person's approval.

## Reporting back

Please tell the software side:
- One L298N or two
- Whether the phone connected on its own, or needed mobile data off
- Your measured wheel diameter, track width and pulses per turn
- Anything that behaved differently from this guide
