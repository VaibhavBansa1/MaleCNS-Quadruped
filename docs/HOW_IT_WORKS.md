# How it works

One loop, about 30 times a second:

```
camera frame ─┬─> fly_eye.py ──> ON/OFF motion, left and right ──┐
              └─> nose.py ─────> smell left, smell right ────────┤
microphone ─────> ear.py ──────> song / fast bands, L and R ─────┤
                                                                 v
                              brain_link.py: inject into named sensory neurons,
                              run the MaleCNS connectome for as many 20 ms steps
                              as real time has passed, read behaviour neurons
                                                                 v
                              decide.py: compare each with its resting level,
                              pick one of F B L R S
                                                                 v
                     robot_link.py ──USB──> ESP32 gait      twin.py (virtual fly)
```

## 1. Senses

**Eyes (`fly_eye.py`).** A fly's eye is very wide and very low resolution, and its
escape pathway is colour-blind. Each frame is shrunk to a 16 x 64 grey strip. The
difference from the previous frame is split into an ON map (got brighter) and an OFF
map (got darker). The difference is divided by the time between frames, so a 15 fps
and a 30 fps camera give the same answer. Small changes below a noise floor (0.03)
are ignored, so camera grain does not count as motion.

**Nose (`nose.py`).** A camera cannot smell, so the food is found visually and its
position is turned into a smell strength on each side (0 to 1):

* `color` (default): click the food once and the program learns its hue. Smell is
  the fraction of that hue in the left and right halves of the picture.
* `yolo`: an object detector (YOLOv8n, COCO class such as "apple") finds the food.

**Ears (`ear.py`).** Sound is split into the two bands the fly's Johnston's organ
cares about: "song" (100-350 Hz) and "fast" (350-900 Hz). Levels are measured
relative to the room noise recorded at start, so any microphone works in a noisy hall.

## 2. Into the connectome (`brain_link.py`)

The brain is `flybrain`'s leaky integrate-and-fire model of MaleCNS v1.0:
166,700 neurons, time step 20 ms, run on the GPU with CuPy. It is created with
`sensory_input=False`. With the default background sensory drive switched on, the
olfactory receptor neurons excite each other into a runaway loop and the central
brain saturates, so nothing downstream can respond.

Inputs go into **named cell types**, left and right separately:

| Sense | Neurons driven | Why these |
|---|---|---|
| Eye motion | LC4, LPLC2, LPLC1 | Looming and motion detectors that feed the escape pathway |
| Smell | ORN_DM1, ORN_DM4, ORN_VA2, ORN_DM2 | Receptor neurons for fruit and vinegar odours flies walk toward |
| Food as visual target (`--food-as-target`) | LC10a | "Small object I am chasing" neurons, with a known route to DNa02 |
| Sound | JO-B (song band), JO-A (fast band) | The sound-sensing part of Johnston's organ |

Nothing inside the network is set by hand. Only the entry points are chosen.

## 3. Out of the connectome

`flybrain` labels the behaviour neurons in `brain.groups`. The robot reads four of them:

| Group | Neuron | What it does in a real fly |
|---|---|---|
| escape | DNp01 (giant fibre) | Triggers the escape jump |
| steer | DNa02 | Left one firing turns the fly left |
| forward | DNg100 | Walking forward |
| backward | MDN ("moonwalker") | Walking backward |

Firing rates are smoothed over 0.5 s, because each group is only one neuron per side
and single spikes are noisy.

## 4. The decision (`decide.py`)

The network always fires a little on its own, so a raw rate means nothing. During the
first 8 seconds the real scene is kept still and the robot stands still. That gives a
**live resting baseline** for every group. Every later rate is divided by it.

Rules, checked in order:

| Rule | Command | Setting |
|---|---|---|
| escape above 4x rest | `B` back away | `escape_ratio = 4.0` |
| steer left/right ratio differ by more than 0.5 | `L` or `R` | `steer_gap = 0.5` |
| forward above 1.5x rest | `F` | `forward_ratio = 1.5` |
| otherwise | `S` stop | |

To stop the robot from twitching, a new command must be wanted for 0.3 s before it is
accepted (`confirm_seconds`), and each command is kept for at least 0.4 s
(`hold_seconds`).

These numbers are hand-set. They should be measured from recorded data with a fixed
rule (for example, the escape threshold at the 99th percentile of the resting ratio)
and then left alone.

## 5. The body

The ESP32 firmware (`fly_body/src/main.cpp`) is a fixed pattern generator:

* **Diagonal gait.** Front-left with back-right, front-right with back-left. A slow
  push stroke (65% of the cycle) and a fast return. Step 25 degrees, cycle 1.2 s.
* **Turning.** One side steps backward while the other steps forward.
* **Servo speed limit** (300 degrees/s) softens jerks and current spikes.
* **Watchdog.** If no command arrives for 500 ms, the legs stop. If the PC program
  crashes, the robot does not walk off the table.
* **Head servo** turns smoothly toward where the brain wants to steer (up to 60 degrees).
* **OLED face** (`face.cpp`) draws a fruit-fly face: compound eyes with facets,
  antennae, proboscis. The eyes widen on escape. The eyes close if the PC goes quiet
  for 1.5 s. It runs as its own task on the ESP32's second core so it never slows
  the gait.

The PC sends the current command every 0.2 s.

## Known limitations

* **Left steering bias.** In most runs the left DNa02 fires more than the right even
  at rest. Smell input reaches both brain hemispheres, which washes out the left/right
  difference, and one neuron per side is a noisy readout. Next step: add DNa01 to the
  steering readout and test with food on each side.
* **Open loop.** No efference copy and no leg feedback reach the brain.
* **Speed.** The brain runs in real time on an RTX-class GPU. On a CPU it falls behind
  and steps are capped at 5 per frame.
* **One fly, one seed.** No error bars yet. `flybrain` supports several flies in a
  batch for almost the same GPU cost.
