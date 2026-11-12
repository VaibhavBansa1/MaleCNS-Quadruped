# Settings reference

Every command-line option and every number you might want to change, where it lives,
its default, and what changing it does.

**Rule for honest results:** change a threshold for a reason you can write down (a
measurement, a fixed percentile of the resting data), not until the robot "looks right".
Keep a note of what you changed.

* [Command-line options](#command-line-options)
* [Environment variables](#environment-variables)
* [Keys in the window](#keys-in-the-window)
* [Python settings, by file](#python-settings-by-file)
* [Firmware settings](#firmware-settings)

## Command-line options

### `live/run_live.py` (the full program)

| Option | Default | Values | What it does |
|---|---|---|---|
| `--camera` | `auto` | `auto`, `0`, `1`, ..., or a URL | Which camera. `auto` takes the first one that works. A URL opens a phone or IP camera stream. |
| `--list-cameras` | | | Print the working camera numbers and their resolution, then exit. |
| `--nose` | `color` | `color`, `yolo` | How food is found. `color`: click the food once to teach its colour. `yolo`: an object detector looks for `--target`. Falls back to `color` if ultralytics is missing. |
| `--target` | `apple` | any COCO class name (`apple`, `banana`, `orange`, `cup`, `bottle`, ...) | What `--nose yolo` looks for. |
| `--mic` | `auto` | `auto`, `esp`, `laptop`, `none` | The fly's ears. `esp`: the two mics on the robot. `laptop`: a PC microphone. `auto` tries the robot, then the laptop, then none. |
| `--mic-device` | system default | a number from `live/ear.py --list` | Which PC microphone to use with `--mic laptop`. |
| `--port` | `auto` | `auto`, `COM4`, `/dev/ttyUSB0`, `none` | The robot's serial port. `auto` finds the ESP32's USB chip. `none` runs on screen only. If opening fails, the program runs without the robot. |
| `--device` | `auto` | `auto`, `cuda`, `cpu` | Where the brain runs. See [SETUP.md](SETUP.md#3-choose-gpu-or-cpu). |
| `--food-as-target` | off | flag | Also feed the food position to LC10a, the "small target I am chasing" visual neurons. LC10a has a known route to the DNa02 steering neurons, so turning toward food becomes more likely. Off by default so smell alone can be tested first. |

### Module test programs

| Command | Options |
|---|---|
| `live/camera.py` | `--camera` (as above), `--list` |
| `live/fly_eye.py` | `--camera` |
| `live/nose.py` | `--camera`, `--nose`, `--target` |
| `live/ear.py` | `--list` (microphones), `--mic <number>`, `--esp <port>` (test the robot mics) |
| `live/robot_link.py` | `<port>`, `auto`, or `--list` |
| `live/brain_link.py`, `live/decide.py`, `live/twin.py` | none |

### Offline experiments

| Command | Options |
|---|---|
| `fly_pipeline.py` | `video` (path), `--frames 600`, `--device auto`, `--route retina / feature / both` |
| `inspect_pipeline.py` | `video`, `--route retina / feature`, `--start 1200` (first frame printed), `--frames 4`, `--device auto`, `--export file.npz` |
| `fly_body.py` | `--video`, `--wav` (optional soundtrack for the ears), `--seconds 12`, `--out file.mp4` |
| `visual_spike_encoder.py`, `audio_spike_encoder.py` | one path: a video or a mono wav |

## Environment variables

| Variable | Default | What it does |
|---|---|---|
| `FLY_DATA` | `~/fly-data` | Folder with `brain.npz` and `weights.npz`. |
| `FLY_DEVICE` | `cpu` | Device for any `FlyBrain` created without an explicit device. The scripts here pass `auto`. |
| `FLYBRAIN_DATA_URL` | flybrain's release | Where `flybrain download` fetches the brain files from. |
| `QT_QPA_PLATFORM=xcb` | | Linux only: makes the OpenCV window open under Wayland. |

## Keys in the window

| Key | Does |
|---|---|
| click the food | Teach the colour nose what the food looks like. |
| space | Pause / resume the robot. The brain keeps running; the robot gets `S`. |
| m | Switch between brain control and manual control. |
| w a s d x | Manual mode: forward, left, back, right, stop. |
| 0 | Put the virtual fly back in the middle of its arena. |
| r | Recalibrate: room noise and the live brain baseline (keep still for 8 s). |
| h | Show / hide the key help. |
| q | Quit. The robot stops. |

## Python settings, by file

### `live/run_live.py`

| Setting | Default | What it does |
|---|---|---|
| `CALIBRATE_SECONDS` | `8.0` | How long the live baseline is measured at start and after `r`. Longer gives a steadier baseline, because each behaviour group is a single neuron per side. |
| `MAX_STEPS_PER_LOOP` | `5` | Most brain steps (20 ms each) run per camera frame. Stops a slow computer from falling ever further behind. |

### `live/fly_eye.py`: `FlyEye(...)`

| Setting | Default | What it does |
|---|---|---|
| `height`, `width` | `16`, `64` | Size of the fly's view. Wide and coarse like a compound eye. |
| `noise_floor` | `0.03` | Changes smaller than this are ignored. Raise it (0.05-0.08) if camera grain flickers as motion; lower it to see slower motion. |
| `reference_fps` | `30` | Change is scaled to this frame rate, so every camera gives the same answer. |

### `live/nose.py`

`ColorNose(...)`:

| Setting | Default | What it does |
|---|---|---|
| `hue_width` | `10` | How far from the clicked colour (on OpenCV's 0-180 hue scale) still counts as food. |
| `min_saturation`, `min_value` | `80`, `60` | Ignore greyish and dark pixels, which have no reliable colour. |
| `gain` | `8.0` | Food covering 1/gain of one half of the picture gives full smell (8 means 12.5%). |
| `smoothing` | `0.3` | How much each new frame changes the smell (lower is steadier, slower). |

`YoloNose(...)` adds:

| Setting | Default | What it does |
|---|---|---|
| `target` | `apple` | COCO class name to look for. |
| `model` | `yolov8n.pt` | Detector weights; downloaded on first use. |
| `confidence` | `0.35` | Minimum detection confidence. |

### `live/ear.py`

| Setting | Default | What it does |
|---|---|---|
| `SONG` | 100-350 Hz | Band sent to JO-B (fly song range). |
| `FAST` | 350-900 Hz | Band sent to JO-A (faster vibration). |
| `LOUD_RATIO` | `20` | A band this many times louder than the measured room noise counts as full level (1.0). Raise it for a noisy hall. |
| `LaptopMic(rate, window_ms)` | 16000 Hz, 64 ms | Sample rate and length of sound analysed each frame. |
| `EspMic(wait_seconds)` | `1.5` | How long to wait for the robot mics to answer before giving up. |

### `live/brain_link.py`

| Setting | Default | What it does |
|---|---|---|
| `FlyBrainLink(device)` | `auto` | Same as `--device`. |
| `FlyBrainLink(seed)` | `64` | Random seed of the network's noise. Change it to check a result is not one lucky run. |
| `FlyBrainLink(rate_tau)` | `0.5` s | Smoothing of the firing rates. Longer is steadier but reacts later. |
| `FOOD_ODOUR_TYPES` | `ORN_DM1, ORN_DM4, ORN_VA2, ORN_DM2` | Which olfactory receptor types count as "food smell". |
| `NoseRoute(gain)` | `0.8` | Input strength into the smell neurons at full smell. |
| `sensory_input=False` | | Removes the built-in background drive onto sensory neurons. With it on, smell neurons excite each other into a runaway loop. Do not change. |

### `fly_pipeline.py` (used by the live eye and ear routes too)

| Setting | Default | What it does |
|---|---|---|
| `CAP` | `0.8` | Most input any one channel adds per step. Keeps one input from saturating its neurons. |
| `FeatureRoute(motion_gain)` | `6.0` | Total motion on one side → LC4 drive. |
| `FeatureRoute(loom_gain)` | `25.0` | Growth of motion (something getting bigger) → LPLC2, and growth of brightening → LPLC1. These are the looming signals that trigger escape. |
| `EarRoute(gain)` | `0.7` | Sound level → JO-A / JO-B drive. |
| `RetinaRoute(lum_gain, change_gain)` | `0.45`, `1.6` | Offline only: luminance and change into the photoreceptors. |

### `live/decide.py`: `Decider(...)`

| Setting | Default | What it does |
|---|---|---|
| `escape_ratio` | `4.0` | Escape (DNp01) above this many times its resting rate → `B`. Lower is jumpier. |
| `steer_gap` | `0.5` | Left and right steering (DNa02), each divided by its own resting rate, must differ by more than this → `L` or `R`. Lower turns more often, and makes the left bias show more. |
| `forward_ratio` | `1.5` | Forward (DNg100) above this many times rest → `F`. |
| `confirm_seconds` | `0.3` | A new command must be wanted this long before it is accepted. Filters single-spike flickers. |
| `hold_seconds` | `0.4` | Each accepted command is kept at least this long, so the robot does not twitch. |

Rule order: escape, then steer, then forward, otherwise stop.

### `live/robot_link.py`: `Robot(...)`

| Setting | Default | What it does |
|---|---|---|
| `baud` | `115200` | Must match `monitor_speed` / `Serial.begin` in the firmware. |
| `watchdog_ms` | `500` | Sent to the robot as `W 500`: it stops if no command arrives within this time. |
| resend interval | `0.2` s | The current command is repeated this often, which keeps the watchdog fed. |

### `live/twin.py` (the virtual fly)

| Setting | Default | What it does |
|---|---|---|
| `ARENA_CM` | `(45, 30)` | Size of the virtual table in cm. |
| `WALK_CM_PER_S` | `0.67` | Measured on the robot: about 1 cm every 1.5 s. Time 10 s of `F` on your robot and divide. |
| `TURN_DEG_PER_S` | `4.5` | Measured on the robot. Time 10 s of `L` and divide the angle. |
| `BODY_CM` | `3` | Drawn size of the fly. |

## Firmware settings

### `fly_body/src/main.cpp`

| Setting | Default | What it does |
|---|---|---|
| `LEG_CH[4]` | `{0,1,2,3}` | PCA9685 channel of front-left, front-right, back-left, back-right. |
| `HEAD_CH` | `4` | Channel of the 180-degree head servo. |
| `HEAD_SIGN` | `-1` | Flip if the head looks right when the brain says left. |
| `HEAD_RANGE` | `60` degrees | Head angle either side at full steering. |
| `SIDE_SIGN[4]` | `{-1,1,-1,1}` | Flip one sign if that leg swings the wrong way. |
| `TRIM_US[4]` | `{0,0,0,0}` | Per-servo centre correction in microseconds (about 11 us per degree). |
| `IS_LEFT[4]` | `{true,false,true,false}` | Which legs are on the left. Swap if `L` and `R` turn the wrong way. |
| `PHASE_OFFSET[4]` | `{0,0.5,0.5,0}` | Diagonal gait: front-left with back-right, front-right with back-left. |
| `ampDeg` | `25` | How far each leg swings from centre. Change live with `A <deg>`. |
| `periodMs` | `1200` | Time of one full step. Change live with `P <ms>`. |
| `duty` | `0.65` | Fraction of the step spent pushing (slow) versus returning (fast). Change live with `D <pct>`. |
| `MAX_DPS` | `300` | Servo speed limit in degrees per second. Softens jerks and current spikes. |
| `TICK_MS` | `20` | Update rate (50 Hz, the servo frame rate). |
| `watchdogMs` | `0` (off) | Set by the PC to 500 with `W 500`. |

### `fly_body/src/face.cpp`

| Setting | Default | What it does |
|---|---|---|
| `OLED_SDA`, `OLED_SCL` | `18`, `19` | Second I2C bus for the OLED. |
| `OLED_POWER` | `23` | GPIO that powers the OLED (set HIGH at start). |
| `OLED_ADDRESS` | `0x3C` | Most of these screens; some are `0x3D`. |
| `NO_SIGNAL_MS` | `1500` | Eyes close if the PC sends nothing for this long. |
| `FACE_MIRROR` | `-1` | Flip if the eyes look the opposite way to the head. |

### `fly_body/src/mic.cpp`

| Setting | Default | What it does |
|---|---|---|
| `MIC_PIN[2]` | `{34, 35}` | Left and right analog microphones. |
| `SAMPLE_HZ` | `4000` | Sampling rate per mic. |
| `WINDOW` | `200` samples | 50 ms per level report. |
