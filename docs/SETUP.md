# Setup guide

From a fresh computer to a walking robot. Every command runs from the `fly-vision`
folder unless it says otherwise.

* [1. What you need](#1-what-you-need)
* [2. Install the Python side](#2-install-the-python-side)
* [3. Choose GPU or CPU](#3-choose-gpu-or-cpu)
* [4. Get the connectome data](#4-get-the-connectome-data)
* [5. Flash the robot firmware](#5-flash-the-robot-firmware)
* [6. Test each part alone](#6-test-each-part-alone)
* [7. Run everything](#7-run-everything)
* [8. Ways to run it](#8-ways-to-run-it)
* [9. Run the simulations](#9-run-the-simulations)
* [10. Troubleshooting](#10-troubleshooting)

## 1. What you need

| | Minimum | Used here |
|---|---|---|
| OS | Windows 10/11 or Linux (Ubuntu 24.04 tested for setup) | Windows 11 |
| Python | 3.11 or newer (3.12 recommended) | 3.12 |
| Package manager | [uv](https://docs.astral.sh/uv/) | uv |
| GPU | optional; NVIDIA with CUDA 12 for real-time speed | RTX 5060 Ti 16 GB (an RTX 2050 4 GB laptop was also set up) |
| RAM | 8 GB | 32 GB |
| Disk | about 3 GB (packages + 260 MB brain data) | |
| Camera | any webcam, laptop camera, or a phone/IP camera stream | USB webcam |
| Microphone | optional; any laptop or USB mic | laptop mic |
| Robot | optional; see [HARDWARE.md](HARDWARE.md) | ESP32 + PCA9685 quadruped |

Without a robot the program still runs completely: the virtual fly on screen
receives the same commands.

## 2. Install the Python side

Install uv once:

```powershell
# Windows (PowerShell)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
```bash
# Linux / macOS
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then:

```bash
git clone https://github.com/VaibhavBansa1/MaleCNS-Quadruped.git
cd MaleCNS-Quadruped/fly-vision
uv venv --python 3.12
uv pip install flybrain numpy opencv-python scipy sounddevice pyserial
uv pip install ultralytics          # optional: the YOLO food detector (--nose yolo)
```

Linux only:

```bash
sudo apt install -y libportaudio2         # needed by sounddevice (the microphone)
sudo usermod -aG dialout $USER            # permission to open /dev/ttyUSB0; log out and back in
```

If the window does not open on Linux (Wayland), put `QT_QPA_PLATFORM=xcb` in front of
the command.

## 3. Choose GPU or CPU

The brain is 166,700 neurons and 25.6 million synapses, stepped every 20 ms.
`flybrain` runs the same model on either device. Only the random noise streams differ,
so single spikes differ but the statistics match.

| Device | How it runs | Install | Speed |
|---|---|---|---|
| `cuda` | CuPy sparse matrices on an NVIDIA GPU | `uv pip install ".[cuda]"` | real time on an RTX card |
| `cpu` | numba on the processor | nothing extra | slower than real time; the robot reacts late |
| `auto` (default) | `cuda` if a usable GPU is found, else `cpu` | | |

Install the GPU extra (from `fly-vision`):

```bash
uv pip install ".[cuda]"
```

It installs CuPy plus NVIDIA's runtime wheels. On Windows CuPy alone is not enough:
without the `nvidia-*` wheels it reports a GPU but then fails to find `nvJitLink`.
A `CUDA_PATH could not be detected` warning is harmless; the wheels bring their own
runtime. You only need a recent NVIDIA driver (check with `nvidia-smi`).

Check what flybrain sees:

```bash
uv run python -m flybrain info      # data folder, files present, "cuda: available"?
uv run python live/brain_link.py    # prints "brain ready on cuda" (or cpu) and ms per step
```

The speed line matters: one brain step must take less than 20 ms to keep up with real
time. If it takes longer, `run_live.py` runs at most 5 steps per camera frame
(`MAX_STEPS_PER_LOOP`) instead of falling further and further behind.

Choose the device:

```bash
uv run python live/run_live.py --device cuda     # force the GPU
uv run python live/run_live.py --device cpu      # force the CPU
uv run python live/run_live.py                   # auto
```

You can also set `FLY_DEVICE=cuda` (or `cpu`) for any script that does not pass a device.

## 4. Get the connectome data

`flybrain` needs two files, `brain.npz` and `weights.npz` (about 260 MB together).
They live in the folder named by `FLY_DATA`, or `~/fly-data` if it is not set.

Three ways to get them:

1. **Automatic.** The first time a `FlyBrain` is created, the files are downloaded.
   Just run `uv run python live/brain_link.py`.
2. **Explicit download:** `uv run python -m flybrain download`
3. **Build from the original MaleCNS v1.0 release** (about 1.1 GB download):
   `uv pip install "flybrain[build]"` then `uv run python -m flybrain build`

To keep the data somewhere else:

```powershell
setx FLY_DATA D:\fly-data            # Windows, permanent (open a new terminal after)
$env:FLY_DATA = "D:\fly-data"        # Windows, this terminal only
```
```bash
export FLY_DATA=~/fly-data           # Linux / macOS (add to ~/.bashrc to keep it)
```

Copying the folder from another computer works too; no download is needed then.

## 5. Flash the robot firmware

Build the robot first: [HARDWARE.md](HARDWARE.md) has the top-view layout, the wiring
diagram and the gait diagram.

1. Install [VS Code](https://code.visualstudio.com/) and the **PlatformIO IDE** extension.
2. **File → Open Folder → `fly_body`**. PlatformIO reads `platformio.ini` and fetches the
   three libraries (Adafruit PWM Servo Driver, SSD1306, GFX) by itself.
3. Plug in the ESP32. If no port appears, install the **CP210x USB driver** from Silicon
   Labs (some boards use CH340 instead).
4. Click **Upload** (the arrow in the bottom bar). If the upload hangs on
   "Connecting...", hold the board's **BOOT** button until it starts.
5. Open the **Serial Monitor** (115200 baud) and type `T 0`, `T 1`, `T 2`, `T 3`: each
   leg swings forward in turn. Fix `LEG_CH`, `SIDE_SIGN` and `IS_LEFT` at the top of
   `main.cpp` until each leg matches (see [HARDWARE.md](HARDWARE.md)).
6. **Close the Serial Monitor** before running the Python side; only one program can
   hold the port.

The firmware was compiled for this repository with PlatformIO (espressif32, Arduino):
about 7% of RAM and 27% of flash. From a terminal instead of VS Code:

```bash
cd fly_body
pio run                  # compile
pio run -t upload        # compile and flash
pio device monitor       # serial monitor, 115200 baud
```

### Control the robot (four ways)

| Way | How |
|---|---|
| By hand, no PC program | Serial Monitor: type `F`, `L`, `R`, `B`, `S` and press Enter. The watchdog is off until something sends `W`, so the robot keeps walking until `S`. |
| From Python, by hand | `uv run python live/robot_link.py COM4` (Linux `/dev/ttyUSB0`), then type letters |
| Keyboard in the brain window | `uv run python live/run_live.py`, press `m` for manual, drive with w a s d x |
| The fly brain | `uv run python live/run_live.py`: the connectome decides |

## 6. Test each part alone

Each file in `live/` is a small program of its own. Test in this order; the first
step that fails is where the problem is.

| Step | Command | You should see |
|---|---|---|
| 1. camera | `uv run python live/camera.py --list` then `... --camera 1` | the picture and its fps |
| 2. eye | `uv run python live/fly_eye.py --camera 1` | green where it got brighter, red where darker |
| 3. nose | `uv run python live/nose.py --camera 1` | click the food; smell L/R follows it |
| 3b. YOLO nose | `uv run python live/nose.py --camera 1 --nose yolo --target apple` | a box around the apple |
| 4. ear | `uv run python live/ear.py` (`--list`, `--mic 2`) | bars jump when you clap |
| 4b. robot ears | `uv run python live/ear.py --esp COM4` | left bar = GPIO34 mic, right = GPIO35 |
| 5. brain | `uv run python live/brain_link.py` | "brain ready on ...", then escape jumps in the looming test |
| 6. decision | `uv run python live/decide.py` | the right letter for each fake case |
| 7. robot | `uv run python live/robot_link.py --list` then `... COM4` | typed F / L / S move the robot |
| 8. virtual fly | `uv run python live/twin.py` | drive it with w a s d x |

## 7. Run everything

```bash
uv run python live/run_live.py
```

What happens at start:

1. The camera, nose, robot, microphone and brain start. Any part that fails is replaced
   by a fallback (no robot, no mic, colour nose) and the window says which one is in use.
2. **Stay quiet and keep the scene still for 8 seconds.** The microphone measures the
   room noise and the brain measures its resting rates on the real scene. The robot is
   held at `S` meanwhile.
3. Click the food in the camera picture (colour nose), then show it, wave at the camera,
   or loom a hand toward it.

The window: camera with the food box (top left), what the fly sees (bottom left),
virtual fly (top right), brain bars and the current command (bottom right).

## 8. Ways to run it

```bash
# screen only, no robot
uv run python live/run_live.py --port none

# robot on a named port, laptop mic
uv run python live/run_live.py --port COM4 --mic laptop            # Windows
uv run python live/run_live.py --port /dev/ttyUSB0 --mic laptop    # Linux

# a specific camera, or a phone / IP camera stream
uv run python live/run_live.py --camera 1
uv run python live/run_live.py --camera http://192.168.1.20:8080/video

# YOLO nose looking for an apple, also shown to the steering (LC10a) neurons
uv run python live/run_live.py --nose yolo --target apple --food-as-target

# silent room, no ears
uv run python live/run_live.py --mic none

# CPU only (no NVIDIA GPU)
uv run python live/run_live.py --device cpu
```

Every option and tunable number is explained in [SETTINGS.md](SETTINGS.md).

## 9. Run the simulations

There are two simulated bodies. Neither needs the robot.

### 9a. The virtual fly (built in)

A top-down 2D fly that gets exactly the same commands as the robot. It is always
on the right side of the `run_live.py` window, so `--port none` gives you the whole
brain-to-body loop on screen:

```bash
uv run python live/run_live.py --port none
uv run python live/twin.py          # the virtual fly alone, drive it with w a s d x
```

### 9b. The 3D fly body in MuJoCo (`fly_body.py`)

The brain drives a physical NeuroMechFly body (MuJoCo + FlyGym) from the separate
open-source [fly-arena](https://github.com/artem-x-meta/fly-arena) project. This is how
`docs/media/sim_fly_escapes.gif` was made. Only fly-arena's body and physics are used;
its own brain and its 1.1 GB graph download are **not** needed.

fly-arena needs Python **3.12 exactly** and an OpenGL-capable graphics driver. Clone it
next to this repository:

```
some-folder/
  MaleCNS-Quadruped/
  fly-arena/
```

Windows:

```powershell
cd some-folder
git clone https://github.com/artem-x-meta/fly-arena.git
cd fly-arena
uv venv --python 3.12
uv pip install -e .
uv pip install flybrain opencv-python      # this project's brain side, into the same environment
.\.venv\Scripts\python.exe -m fly_arena run --mode body-demo --seconds 3   # checks the body and viewer
```

Linux: the same, with `.venv/bin/python` (fly-arena also ships `setup_linux.sh`).

**One environment for everything (saves about 3.7 GB).** Instead of a second
environment, install fly-arena into this project's own environment. `pyproject.toml`
already keeps numba and pillow at versions fly-arena accepts, so `uv run` will not undo it:

```powershell
cd some-folder\MaleCNS-Quadruped\fly-vision
uv pip install -e ..\..\fly-arena
cd ..\..\fly-arena
..\MaleCNS-Quadruped\fly-vision\.venv\Scripts\python.exe ..\MaleCNS-Quadruped\fly-vision\fly_body.py --video my_video.mp4 --seconds 15 --out fly.mp4
```
Without a desktop, add `--headless --gl egl` to fly-arena's own commands.

Run the brain in the body. Any video works as the fly's view; fast motion and
looming shapes make it flee:

```powershell
cd some-folder\fly-arena
.\.venv\Scripts\python.exe ..\MaleCNS-Quadruped\fly-vision\fly_body.py --video my_video.mp4 --seconds 15 --out fly.mp4
```

| Option | Default | What it does |
|---|---|---|
| `--video` | `bad-apple.mp4` | What the fly sees |
| `--wav` | none | Optional mono 16 kHz wav that drives the ears |
| `--seconds` | `12` | Simulated time |
| `--out` | none | Write an mp4 of the fly |

It prints the gait command, heading, position and escape level every second, then a
summary: distance walked, time spent fleeing, and whether the fly stayed upright.
How it works: the connectome picks walk / turn (DNa02, DNp09, MDN, decoded the same way
as fly-arena's own decoder) and whether to flee (DNp01); fly-arena's engineered motor
programs move the legs.

### 9c. Offline experiments

These reproduce the tables in [RESEARCH_NOTES.md](RESEARCH_NOTES.md). They need a
video file (and optionally a mono wav) of your own; none is included.

```bash
# video -> brain -> trained readout; compares the retina and feature routes
uv run python fly_pipeline.py my_video.mp4 --frames 600 --route both

# print every stage for a few frames, or export per-frame series
uv run python inspect_pipeline.py my_video.mp4 --start 100 --frames 4
uv run python inspect_pipeline.py my_video.mp4 --export series.npz

# check the encoders alone
uv run python visual_spike_encoder.py my_video.mp4
ffmpeg -i my_video.mp4 -ac 1 -ar 16000 sound.wav
uv run python audio_spike_encoder.py sound.wav
```

## 10. Troubleshooting

| Problem | Cause and fix |
|---|---|
| `No module named ...` | Wrong folder or wrong environment. `cd fly-vision`, and `deactivate` any other venv first. Always run with `uv run`. |
| "Could not open camera" | Wrong number, or another app (Zoom, browser, NVIDIA Broadcast) holds it. Run `--list-cameras`. A virtual camera may show a static logo. |
| Escape fires all the time at rest | The baseline was taken with nothing in view or while moving. Keep the real scene still and press `r`. |
| Commands flicker | Raise `confirm_seconds` or `hold_seconds` in `decide.py`, or `rate_tau` in `brain_link.py`. |
| Smell is always 0 | Food not clicked, or its colour is dull, white or black. Use a strongly coloured object. |
| Smell everywhere | The background has the same colour. Change the object or the background. |
| Microphone bars flat | `sounddevice` missing (the status line says why), or the wrong mic: `live/ear.py --list`. On Linux install `libportaudio2`. |
| Microphone bars always full | Noise during calibration. Press `r` in silence. |
| Robot does not move | Port busy (close the PlatformIO Serial Monitor), wrong port (`robot_link.py --list`), or servo power not connected to the PCA9685 V+ terminal. |
| `Permission denied: /dev/ttyUSB0` | `sudo usermod -aG dialout $USER`, then log out and in. |
| Robot turns the wrong way | Swap `IS_LEFT` in `main.cpp`. A single leg backwards: flip its `SIDE_SIGN`. |
| Head or face eyes look the wrong way | Flip `HEAD_SIGN` in `main.cpp` or `FACE_MIRROR` in `face.cpp`. |
| Robot stops by itself | The 500 ms watchdog: the PC stopped sending. Check that `run_live.py` is still running. |
| Brain very slow | Running on CPU. Install `".[cuda]"` and check `python -m flybrain info`. |
| PlatformIO "Could not find package" | A typo in `platformio.ini` `lib_deps`. Compare with the version in this repo. |
