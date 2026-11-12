# Research notes

Working notes from the offline experiments that came before the robot. Written while the
work was happening, so some parts read like a lab notebook.

## Original goal

Use the MaleCNS v1.0 fruit fly connectome as a **fixed reservoir** in a
reservoir-computing setup. Feed it encoded sensory input, read out spike
activity from descending neurons, and fit a small trained readout on top.

The connectome's internal weights are **never trained or modified**. Only the
encoder (input side) and the readout (output side) are tuned.

Phase 1: video input (current).
Phase 2: WiFi CSI input from an ESP32-S3, for human motion detection.
The pipeline is identical; only the encoder changes.

## Environment
- Windows, PowerShell
- Python 3.12 (confirmed working — do not downgrade to 3.11)
- `uv` for all package management. Never plain `pip`.
- RTX 5060 Ti 16GB. CuPy loads and reports `cuda: available`.
  A `CUDA_PATH could not be detected` warning appears and is harmless —
  CuPy ships its own runtime.

Commands: `uv venv --python 3.12`, `uv pip install X`, `uv run python x.py`

## Layout
```
fly-arena/     separate cloned repo (package `male-cns-arena`), not included here. For watching only.
fly-vision/    this project: flybrain + my code.
```
Connectome data lives outside both:
- the folder in `FLY_DATA` — flybrain's prebuilt `brain.npz` + `weights.npz` (~260MB)
- `fly-arena\data\graph\` — fly-arena's own build from raw MaleCNS (~1.11GB)

Same connectome, different packaging, **different simulation parameters**.
Identical stimuli can give different activity between them. Not a bug.

## The stack — what does what
| Job | Tool |
|---|---|
| Authoritative neuron/cell-type lookup | neuPrint (`neuprint-python`, official Janelia) |
| Run LIF dynamics, inject, get spikes | `flybrain` (pip package) |
| Watch a 3D fly walk | fly-arena (MuJoCo + FlyGym) |
| Encode input → spike rates | **my code** |

`flybrain` is brain only: no body, no physics, no motor output.
`brain.step(inject=...)` returns the IDs of neurons that fired. That's the
entire data interface.

## Pipeline
```
video → grayscale frames → encoder (mine) → flybrain → spikes → Trace → Readout
```
The endpoint is a **measurable number** (how separable the activity is between
conditions), not a moving fly.

## Decisions already made
- Video before CSI. Vision is the best-characterized fly pathway.
- Grayscale is correct, not a compromise. R1–R6 are broadband and feed the
  motion/escape pathway; color (R7/R8) goes to a branch we don't use.
- No depth needed. Flies get depth from motion, not stereo. Consecutive
  frames carry it; LC4/LPLC2 extract it.
- Encode **temporal contrast** (ON/OFF channels from frame difference), not
  absolute luminance. The target circuit responds to change.
- Monitor a **population** of descending neurons, not DNp01 alone.
- Keep encoder / brain / readout as three separate modules with clean
  interfaces, so the brain simulator is swappable later.

## Known traps
- **Frame rate ≠ simulation timestep.** ~30fps video = 33ms/frame. But
  flybrain's `dt` is **20 ms, not 1 ms** — so a frame spans **2 steps, not 33**.
  Module 1's Poisson stage was written for dt=1ms and *saturates* at 20ms
  (p = 200Hz × 0.02s = 4.0 → clipped to 1.0, every pixel fires every step).
  Use `contrast_maps()`, not `spikes()`, when driving flybrain.
- **flybrain takes graded voltage, not spikes.** Both input interfaces want
  0..1 levels and do their own thresholding.
- **`inject=` amounts are scalars, not per-neuron vectors.** `_amount()`
  broadcasts a number, or one value per *fly* (batch) — passing a per-neuron
  array raises a shape error. `inject` is a *list* of `(idx, amount)` pairs,
  so granularity comes from how you split the index sets, not from a vector.
- **Azimuth exists only for the 6,006 photoreceptors**, not for LC4/LPLC2.
  There is no retinotopy on the VPN route — only side (L/R).
- **Encoder output size must match neuron count.** Query
  `brain.cells([...])` first, then pick resolution. Not the reverse.
  Measured: LC4 126, LPLC2 185, LPLC1 134, LC10a 275,
  visual_projection 9,201, descending_neuron 1,314, photoreceptors 6,006.
- **fly-arena's `--mode body-demo` has the connectome switched OFF.** The
  walking there is recorded kinematics + live physics. Seeing it move proves
  the install works, nothing more.
- **fly-arena does NOT use flybrain at all.** Verified: its source never imports
  it. It ships its own LIF simulator over its own connectome copy
  (`data/graph/`), builds `Brain` internally with no injection parameter, and
  `NeuralAdapter` validates the dataset manifest. You cannot hand it my brain.
  **But you don't need to** — use the body alone (see Module 4 below).
- **fly-arena's gait decode reads only DNa02, DNp09, MDN** (`fly_arena/brain.py:71-87`,
  gains 0.015/0.015). Not LC4/LPLC2, not DNp01. All three exist in flybrain, so
  the identical decode runs on my brain.
- Even in fly-arena, leg motion comes from FlyGym's hand-written controller.
  The connectome only picks the gait command. Nobody has a validated
  motor-neuron-to-muscle mapping yet.
- fly-arena bundles ~20 folders of unrelated research side-projects
  (`fly_bio`, `fly_semantic`, `fly_duel`, etc). None are needed.
- `flybrain` is v0.1.0, single maintainer, days old. Read code before trusting.

## Things to avoid
- Use Brian2 or BindsNET. Built for hundreds-to-thousands of neurons;
  166,700 neurons / 25.6M synapses will not run well. flybrain already does
  this as sparse GPU ops.
- Claim the fly "learned" anything. The connectome is frozen. What gets
  tuned is the encoder and the readout — finding a projection where the
  reservoir's fixed dynamics happen to separate the classes.

## Results so far
`fly_pipeline.py` wires encoder → flybrain → Trace(descending_neuron) → Readout.
Stimulus: `bad-apple.mp4`, 6,572 frames (219s), full run ≈24s/route on GPU.

Labels are read off the *video*, never off the brain, so a readout that
recovers them has recovered something the reservoir actually carried.

| route | how it enters | energy R² | side AUC | shuffled |
|---|---|---|---|---|
| retina (`eye_drive`, 6,006 photoreceptors) | full azimuth detail | -0.007 | 0.521 | 0.508 |
| feature (`inject`, LC4/LPLC2/LPLC1 × L/R) | 6 scalars | **0.608** | **0.896** | 0.501 |

**The retina route is dead — at chance.** This independently confirms
flybrain/eyes.py's warning that photoreceptor drive "fades at the lamina"
(real lamina neurons are graded; a spiking model can't relay them). Spatial
detail is not the bottleneck: 6 well-placed scalars beat 6,006 photoreceptors.

Caveat: `Readout.fit` reports the **max** CV score over its 12-point
hyperparameter grid, which is optimistically biased on small samples — the
shuffled control read 0.67 at 120 frames and only fell to ~0.50 by ~900.
Always run the shuffled control, and don't trust a score from a short clip.

## The result that's actually legible
Measured against a **resting baseline** (identical network, no input, same seed) —
without that control none of these numbers mean anything, since the net idles at 5–8%:

| | watching | resting | ratio |
|---|---|---|---|
| **Escape — DNp01 (giant fibre)** | 3.77 | 0.069 | **54.5×** |
| Visual detectors (LC/LPLC) | 203 | 101 | 2.0× |
| Descending neurons | 41.8 | 29.7 | 1.4× |
| Back up (MDN) | 0.103 | 0.073 | 1.4× |
| Walk forward (DNg100) | 0.074 | 0.045 | 1.7× |
| Turn (DNa02) | 0.110 | 0.133 | 0.8× |
| Optic lobes | 1053 | 988 | 1.07× |
| Central brain | 6359 | 6102 | 1.04× |

**The fly tries to flee.** Bad Apple's dancing silhouettes read as looming objects,
and DNp01 — the neuron that fires when a hand swings at a fly — runs 55× over rest.
Turn is *below* rest (0.8×), which fits: the stimulus looms but has no consistent side.

**Use `sensory_input=False`.** With the default `True`, olfactory receptor neurons
excite each other into a runaway loop and the central brain sits pinned near max
(10,310 spikes/step, almost zero variance) — nothing downstream can respond. With it
off, the central brain drops to 6,359 and the network becomes responsive.

`brain.groups` maps behaviours to named neurons and is the most interpretable readout
available: escape=DNp01, forward=DNg100, steer=DNa02, backward=MDN, punch=DNg11, kick=pIP10.

`brain.positions` holds real 3D coordinates for 140,638 of 166,700 neurons —
x = left/right (higher = fly's left), z = body axis (brain ≈30k → nerve cord ≈101k
→ leg motor ≈134k). Enough to render the whole CNS and watch it light up.

## Sound (Module 1b — `audio_spike_encoder.py` + `EarRoute`)
The connectome has a complete auditory pathway: **672 JO** (Johnston's organ =
the ear; JO-A/B = sound 138, JO-C/D/E = gravity/wind), 547 WED, 156 pC1,
pIP10 (song command), 35 TN1 (song motor). Only JO-A/JO-B are driven — a
speaker doesn't tilt the antenna.

Four conditions, same seed, vs resting:

| | vision | sound | both |
|---|---|---|---|
| JO-A / JO-B (the ear) | 1.0× | **60× / 56×** | 60× / 56× |
| ear's real targets (1 hop) | 1.26× | **4.15×** | 4.38× |
| two hops from ear | 1.40× | **9.71×** | 10.13× |
| pC1 / pIP10 / TN1 (song) | 0.9/0.8/0.6× | 1.03/1.18/1.01× | 0.9/0.4/0.6× |
| escape | **38×** | 2.0× | 38× |
| steer | 1.35× | 1.16× | **1.66×** |
| backward | 1.38× | 0.91× | **1.53×** |

**Sound gets in and propagates, but never engages the courtship circuit** —
correct, since pC1 is tuned to conspecific pulse song (~35 ms IPI, 220–270 Hz
carrier) and pop music isn't that. The fly hears it as noise, not a mating call.

**steer and backward are superadditive** (1.66× and 1.53× vs either alone).
That's genuine cross-modal mixing — the first evidence the reservoir does more
than smooth its input.

⚠️ **Probe pathways by connectivity, not by cell-type name.** Measuring neurons
*named* "WED" showed 1.04× and looked like total failure. The ear's real targets
(computed from the weight matrix) showed 4.15×. Most JO targets are plain
`cb_intrinsic` and are named neither AMMC nor WED.

## Body (Module 4 — `fly_body.py`)
Skips fly-arena's brain entirely; drives the body directly.
`EthologyArena.step_behavior(decision, gait)` takes a 2-vector (L/R stride, 0–1.2).
`GaitDecoder` mirrors fly-arena's own `MotorDecoder` so the mapping isn't invented.

Firing under Bad Apple (dt=11.1 ms): **DNp01 escape 8.0 Hz** vs DNa02 0.5,
MDN 0.2, **DNp09 walk 0.1 Hz**. So `MotorDecoder` alone produces gait ≈ 0.00 —
the fly just stands there. It isn't broken; **the fly isn't trying to walk, it's
trying to flee**, and the gait decode never reads DNp01.

Fix: DNp01 selects fly-arena's own ESCAPE primitive (`fly_arena/motor.py:190-205`),
with the L/R DNp01 imbalance choosing the turn direction. Connectome decides
*whether/which way*; the engineered primitive decides *how legs move*. Result:
**65% of frames fleeing, ran 21.8 units from the origin, stayed upright.**
`fly-vision/fly_escapes.mp4` (15 s, 450 frames).

Run it: `cd fly-arena && ./.venv/Scripts/python.exe ../fly-vision/fly_body.py --seconds 15 --out out.mp4`
(needs the arena venv for MuJoCo/FlyGym; `flybrain` + `opencv` now installed there too.)

## Next steps (at the time)
1. The readout currently recovers properties of the *stimulus*. Next real
   question: does a DN population encode anything the encoder didn't already
   hand it (i.e. genuine reservoir mixing, not a smoothed copy of the input)?
   Test by predicting a label the encoder never sees.
2. Compare descending-neuron trace against `brain.groups` (escape_L/R,
   steer_L/R, …) — those are the behaviourally meaningful readouts.
3. Try `batch > 1` (several flies, ~same GPU cost) to get error bars.
4. Then Phase 2: swap the encoder for WiFi CSI, keep everything downstream.