# live/ - the fly brain with real senses

```
camera -> fly_eye.py  (what the fly sees: 16x64 ON/OFF motion)  --\
camera -> nose.py     (food in the picture -> smell left/right) ----> brain_link.py -> decide.py -> robot_link.py
mic    -> ear.py      (song band + fast band)                   --/      (flybrain)     (F/B/L/R/S)    (ESP32)
```

Run everything from the `fly-vision` folder. Install the two extra packages once:

    uv pip install sounddevice pyserial

Optional, only for the YOLO nose:

    uv pip install ultralytics

## Test each module alone, in this order

| Step | Command | What you should see |
|---|---|---|
| 1 camera | `uv run python live/camera.py --list` then `--camera 1` | the picture and its fps |
| 2 eye | `uv run python live/fly_eye.py --camera 1` | green/red where you wave |
| 3 nose | `uv run python live/nose.py --camera 1` | click the food, smell L/R follows it |
| 4 ear (laptop) | `uv run python live/ear.py` | bars jump when you clap |
| 4 ear (robot) | `uv run python live/ear.py --esp COM5` | left bar for the purple mic, right for the red |
| 5 brain | `uv run python live/brain_link.py` | escape jumps for the looming test |
| 6 decide | `uv run python live/decide.py` | the right letter for each fake case |
| 7 robot | `uv run python live/robot_link.py COM5` | typed letters move the robot |
| all | `uv run python live/run_live.py --port COM5` | the full dashboard |

## Options, and what happens when something does not work

| Part | Option | If it fails |
|---|---|---|
| camera | `--camera auto` (default), `0`, `1`, or a URL | prints the cameras that do work |
| nose | `--nose color` (default) or `--nose yolo --target apple` | yolo falls back to color |
| ears | `--mic auto` (default), `esp`, `laptop`, `none` | auto tries robot mics, then laptop, then silence |
| robot | `--port COM5` | runs without the robot |

The dashboard shows which ear and robot are actually in use.

## Robot mics (one ESP32 does legs and mics)
* Firmware: `fly_body/src/mic.cpp` + `fly_body/include/mic.h`; `main.cpp` calls them. Upload as usual from PlatformIO.
* Wiring: purple MAX4466 OUT -> GPIO 34 (left ear), red KY-037 AO -> GPIO 35 (right ear),
  both powered from 3.3V.
* The ESP32 filters the sound into the two fly bands itself and sends
  `M songL fastL songR fastR` 20 times a second, only after the PC sends `M 1`,
  so the Serial Monitor stays quiet when you test by hand.

## Camera choices
* Laptop camera: usually `--camera 0`. USB webcam: usually `--camera 1`.
* Moto Smart Connect: if Windows sees it as a webcam, it gets a number (check `--list`).
  If it gives a URL instead, pass the URL: `--camera http://192.168.x.x:port/video`.

## Honest notes
* Escape (looming -> LC4/LPLC2 -> DNp01) is the strongest, best-tested pathway.
* Smell and sound reach the brain, but whether DNa02 steering or DNg100 walking
  respond enough to change the command still has to be measured on your machine.
  `--food-as-target` adds the LC10a -> DNa02 route, which is known to get through.
* The connectome is never changed. Only the inputs (which neurons, how strong)
  and the decision thresholds are chosen by us.
