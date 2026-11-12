# Fly brain robot - plain guide

Put this file in `fly-vision/live/`. Run every command from the `fly-vision` folder.

## The big picture

```
camera -> fly_eye.py -\
camera -> nose.py    ---> brain_link.py -> decide.py -> robot_link.py -> ESP32 (main.cpp) -> legs
mic    -> ear.py     -/      (flybrain)      (F/B/L/R/S)        \-> twin.py (virtual fly on screen)
                                    run_live.py runs all of it in one window
```

Each file can be run on its own to test just that part.

---

## live/camera.py - opens a camera
- What: opens a webcam, laptop camera, phone camera, or a stream URL.
- Why the background thread: it always gives the newest picture, so the brain never sees old frames.
- `auto` picks the first camera that works.
- Test: `uv run python live/camera.py --list`, then `uv run python live/camera.py --camera 0`
- Can fail: "Could not open camera" -> wrong number, or another app (Zoom, browser) is using it. Close it and try `--list`.
- Linux: camera numbers are /dev/video0, /dev/video2... (odd numbers are often not real cameras).

## live/fly_eye.py - what the fly sees
- What: turns any picture into a tiny 16 x 64 grayscale strip, then into ON (got brighter) and OFF (got darker) maps.
- Why tiny: a fly's eye is very low resolution and very wide.
- Why grayscale: the fly's motion/escape pathway is colour-blind.
- Why it divides by time between frames: so a 15 fps and a 30 fps camera give the same answer.
- Test: `uv run python live/fly_eye.py` and wave: green = brighter, red = darker.
- Can fail: everything flickers -> camera grain. Raise `noise_floor` (0.03 -> 0.06) in `FlyEye`.

## live/nose.py - camera as a nose
- What: finds the "food" in the picture and gives smell left and smell right (0..1).
- ColorNose (default): click the food once; it learns the colour. Fast and reliable.
- YoloNose (optional): finds a named object like "apple". Needs `uv pip install ultralytics`. Falls back to colour if missing.
- Test: `uv run python live/nose.py`, click a bright red/green object, move it left and right.
- Can fail: smell is 0 -> you didn't click, or the object is dull/white/black. Use a strongly coloured object.
  Smell everywhere -> the background has the same colour. Change object or background.

## live/ear.py - microphone as ears
- What: splits sound into the fly's two hearing bands: song 100-350 Hz and fast 350-900 Hz.
- Why "x times louder than the room": works with any mic and in a noisy hall. The room level is measured at start (and with r).
- Options: laptop mic, robot mics (ESP32), or none. `auto` tries robot, then laptop, then none.
- Test: `uv run python live/ear.py` and clap. `--list` shows mic numbers, `--mic 2` picks one.
- Can fail: "No module named sounddevice" -> `uv pip install sounddevice`.
  Linux: also `sudo pacman -S portaudio`. Bars always full -> you made noise during calibration; press r in quiet.

## live/brain_link.py - plugs the senses into the fly brain
- What: creates the flybrain (166,700 neurons, never trained) and injects:
  - eye -> LC4, LPLC2, LPLC1 (looming / motion), left and right
  - nose -> food-odour receptor neurons (ORN DM1, DM4, VA2, DM2), left and right
  - ear -> Johnston's organ JO-B (song) and JO-A (fast), left and right
- Then it runs the brain and reports how fast the behaviour neurons fire:
  escape (DNp01), steer (DNa02), forward (DNg100), backward (MDN).
- Uses `sensory_input=False` on purpose (see docs/RESEARCH_NOTES.md: otherwise smell neurons run away).
- Test: `uv run python live/brain_link.py` (no camera needed). Read the "speed" line first.
- Can fail: very slow -> no GPU, running on CPU. Still works, just slower reactions.
  "brain files not found" -> set `FLY_DATA` to the folder with brain.npz / weights.npz.

## live/decide.py - turns brain activity into one command
- What: compares each behaviour with its resting level and picks:
  escape high -> B, steer left/right differs -> L/R, forward high -> F, else S.
- Why "x resting": the network always fires a bit on its own.
- Holds each command at least 0.4 s so the robot doesn't twitch.
- Test: `uv run python live/decide.py`
- Tuning: in `Decider(...)`, `escape_ratio` (lower = jumpier), `steer_gap`, `forward_ratio`.

## live/robot_link.py - USB to the ESP32
- What: sends F/B/L/R/S, repeated every 0.2 s. Turns on the firmware watchdog (robot stops if commands stop).
- Also reads mic lines from the ESP32 if you use the robot mics.
- Test: `uv run python live/robot_link.py COM5` (Linux: `/dev/ttyUSB0`) and type F, S...
- Can fail: port busy -> close PlatformIO Serial Monitor. Linux permission denied -> `sudo usermod -aG uucp $USER`, log out/in.
  If it can't open, run_live keeps going without the robot.

## live/twin.py - the virtual fly (simulation on screen)
- What: a top-down arena with a fly that gets the same commands as the robot.
- Hits a wall -> stops there. Press 0 to put it back in the middle.
- Speeds are guesses: time your robot for 10 s of F and set `WALK_CM_PER_S`; same for L and `TURN_DEG_PER_S`.
- Test: `uv run python live/twin.py` and drive with w a s d x.

## live/run_live.py - everything in one window
- Left: camera (with food box) and what the fly sees. Right: virtual fly and brain bars, current command.
- Test: see commands below.

## fly_body/src/main.cpp - the robot firmware (ESP32)
- What: walking gait. Gets F/B/L/R/S over USB and moves 4 leg servos through the PCA9685. Head servo on channel 4.
- Edit at the top: `LEG_CH` (which pin each leg is on), `SIDE_SIGN` (flip a leg that swings the wrong way), `TRIM_US` (straighten a leg).
- Watchdog: stops the legs if no command for 500 ms.
- `mic.cpp` / `mic.h`: the robot mics (optional). Not needed if you use the laptop mic.

## Older files (your earlier work, unchanged)
- `visual_spike_encoder.py`, `audio_spike_encoder.py`: video/audio file encoders.
- `fly_pipeline.py`: video -> brain -> readout scores. live/ reuses its `FeatureRoute`, `EarRoute`.
- `fly_body.py`: brain driving the MuJoCo fly in fly-arena (offline video, not live).
- `inspect_pipeline.py`: prints each stage for debugging.

---

## Commands

Setup (once per laptop):
```
uv venv --python 3.12
uv pip install flybrain numpy opencv-python scipy sounddevice pyserial
```
Brain data: copy the fly-data folder over, then
- Windows: `set FLY_DATA=C:\Users\you\fly-data`
- Linux: `export FLY_DATA=~/fly-data`

Run:
```
uv run python live/run_live.py --mic laptop                        # screen only, no robot
uv run python live/run_live.py --mic laptop --port COM5            # Windows + robot
uv run python live/run_live.py --mic laptop --port /dev/ttyUSB0    # Linux + robot
uv run python live/run_live.py --list-cameras
uv run python live/run_live.py --camera 1 --mic laptop --port COM5 --food-as-target
```
Linux window does not open: put `QT_QPA_PLATFORM=xcb` in front of the command.

## Keys in the window
| Key | Does |
|---|---|
| click the food | teach the nose the food colour |
| space | pause / resume the robot (brain keeps running) |
| m | switch brain control <-> manual control |
| w a s d x | manual: forward, left, back, right, stop |
| 0 | reset the virtual fly to the middle |
| r | recalibrate room noise + resting brain (keep scene still) |
| h | show / hide the key help |
| q | quit (robot stops) |

## When something breaks: check in this order
1. camera.py works? 2. fly_eye.py shows motion? 3. nose.py follows the food? 4. ear.py moves on a clap?
5. brain_link.py: escape jumps for "looming on LEFT"? 6. decide.py prints the right letters?
7. robot_link.py: typed F moves the robot?
The first step that fails is where the problem is.

## What is not in the repository
- `.venv/`, `.pio/`, `__pycache__/`: rebuilt automatically on each machine
- the connectome files (`brain.npz`, `weights.npz`): download them for flybrain and set `FLY_DATA`
- `yolov8n.pt`: downloaded by ultralytics on first use
- the fly-arena repo (MuJoCo body): a separate project
