"""
Module 2: Video -> connectome -> descending-neuron trace -> readout.

Wires `visual_spike_encoder` (module 1) to `flybrain`'s frozen MaleCNS
reservoir, then asks a trained linear readout to recover properties of the
stimulus from descending-neuron activity.

Two routes into the brain, because flybrain offers exactly two and they are
not equivalent:

  Route A "retina"  -> brain.step(eye_drive=...)
      6,006 photoreceptors, each with an azimuth in -1..1 drawn from 72 optic
      columns. This is the only genuinely per-neuron, spatially resolved input
      the simulator has. flybrain/eyes.py warns the signal "fades at the
      lamina" in a spiking model, because real lamina neurons are graded.

  Route B "feature" -> brain.step(inject=[(idx, amount), ...])
      Drives identified visual projection types (LC4 / LPLC2 / LPLC1) directly,
      bypassing the lamina. flybrain/eyes.py calls this "the route that works".
      `inject` amounts are scalars (or one per fly), NOT per-neuron vectors, so
      this route carries only left/right granularity -- no retinotopy.

We run both and compare, rather than taking the lamina claim on trust.

Note on timing: flybrain steps at dt = 20 ms, not the 1 ms a typical LIF model
uses. A 30 fps frame therefore spans 2 steps, not 33. Module 1's Poisson stage
saturates at this dt (p = 200 Hz * 0.02 s = 4.0, clipped to 1.0), which is why
this module uses `contrast_maps` / `frames` and feeds graded voltage instead.

Dependencies: flybrain, numpy, opencv-python, scipy
"""

from __future__ import annotations

import numpy as np

from flybrain import FlyBrain, Readout, Trace
from visual_spike_encoder import VisualSpikeEncoder

CAP = 0.8  # most voltage any one channel adds per step, as in flybrain's ENCODER


class RetinaRoute:
    """Route A: a luminance panorama projected onto the photoreceptor array.

    Mirrors `flybrain.eyes.Eyes.drive`: photoreceptors report a mix of standing
    luminance and frame-to-frame change, clipped to 0..1.
    """

    def __init__(self, brain: FlyBrain, lum_gain: float = 0.45, change_gain: float = 1.6):
        self.columns = np.unique(brain.azimuth)
        self.column_of_receptor = np.searchsorted(self.columns, brain.azimuth)
        self.lum_gain = lum_gain
        self.change_gain = change_gain
        self.previous: np.ndarray | None = None

    @property
    def width(self) -> int:
        """Encoder frame width this route expects: one pixel per optic column."""
        return len(self.columns)

    def drive(self, frame: np.ndarray) -> np.ndarray:
        # The photoreceptor map is 1-D in azimuth, so vertical detail is averaged
        # away rather than silently dropped.
        panorama = frame.mean(axis=0)
        change = np.zeros_like(panorama) if self.previous is None else np.abs(panorama - self.previous)
        self.previous = panorama
        level = np.clip(self.lum_gain * panorama + self.change_gain * change, 0.0, 1.0)
        return level[self.column_of_receptor].astype(np.float32)


class FeatureRoute:
    """Route B: motion energy driving LC4 / LPLC2 / LPLC1 by side.

    Scene-left maps to the "L" cell population. LC4 (escape, strongly drives
    DNp01) carries motion energy; LPLC2 (looming) carries the frame-over-frame
    *growth* in that energy, a crude stand-in for expansion; LPLC1 (small
    approaching objects) carries ON-channel growth only.
    """

    def __init__(self, brain: FlyBrain, motion_gain: float = 6.0, loom_gain: float = 25.0):
        self.cells = {t: {s: brain.cells([t], s) for s in "LR"} for t in ("LC4", "LPLC2", "LPLC1")}
        self.motion_gain = motion_gain
        self.loom_gain = loom_gain
        self.previous: dict[str, float] = {}

    def inject(self, contrast: np.ndarray) -> list[tuple[np.ndarray, np.float32]]:
        """contrast: (2, H, W) ON/OFF map from `VisualSpikeEncoder.contrast_maps`."""
        on, off = contrast
        half = on.shape[1] // 2
        pairs = []
        for side, cols in (("L", slice(0, half)), ("R", slice(half, None))):
            on_energy = float(on[:, cols].mean())
            motion = on_energy + float(off[:, cols].mean())
            growth = max(0.0, motion - self.previous.get(f"m{side}", motion))
            on_growth = max(0.0, on_energy - self.previous.get(f"o{side}", on_energy))
            self.previous[f"m{side}"] = motion
            self.previous[f"o{side}"] = on_energy

            amounts = {
                "LC4": motion * self.motion_gain,
                "LPLC2": growth * self.loom_gain,
                "LPLC1": on_growth * self.loom_gain,
            }
            for cell_type, amount in amounts.items():
                value = np.float32(np.clip(amount, 0.0, CAP))
                if value > 0:
                    pairs.append((self.cells[cell_type][side], value))
        return pairs


class EarRoute:
    """Sound into Johnston's organ, the fly's actual ear.

    JO subtypes are named JO-A*, JO-B* ... so they are matched by prefix rather
    than through `brain.cells`, which needs exact cell-type names.

    Only JO-A and JO-B are driven. JO-C/D/E report static antennal deflection --
    gravity and wind -- which a soundtrack never produces.
    """

    def __init__(self, brain: FlyBrain, gain: float = 0.7):
        types = brain.cell_type.astype(str)
        self.cells = {}
        for name, prefixes in (("JO-B", ("JO-B",)), ("JO-A", ("JO-A",))):
            mask = np.zeros(len(types), bool)
            for p in prefixes:
                mask |= np.char.startswith(types, p)
            for s in "LR":
                self.cells[f"{name}-{s}"] = np.flatnonzero(mask & (brain.side == s))
        self.gain = gain

    def inject(self, song: float, fast: float) -> list[tuple[np.ndarray, np.float32]]:
        """song, fast: 0..1 band levels from `AuditoryEncoder.bands`.

        A mono soundtrack carries no direction, so both antennae get the same
        level. Real flies localise sound; this stimulus gives them nothing to
        localise, and faking a difference would invent a cue.
        """
        pairs = []
        for name, level in (("JO-B", song), ("JO-A", fast)):
            amount = np.float32(np.clip(level * self.gain, 0.0, CAP))
            if amount > 0:
                for s in "LR":
                    idx = self.cells[f"{name}-{s}"]
                    if len(idx):
                        pairs.append((idx, amount))
        return pairs


def stimulus_labels(contrast: np.ndarray) -> tuple[float, float]:
    """(total motion energy, left-minus-right asymmetry) for one frame.

    These are read straight off the video, never off the brain, so a readout
    that recovers them has recovered something the reservoir actually carried.
    """
    total = contrast.sum(axis=0)
    half = total.shape[1] // 2
    left, right = float(total[:, :half].mean()), float(total[:, half:].mean())
    return left + right, left - right


def run_route(
    video: str,
    route: str,
    frames: int = 600,
    device: str = "auto",
    height: int = 16,
    seed: int = 64,
):
    """Step the brain over `frames` video frames and collect activity + labels.

    Returns (activity, energy, asymmetry): activity is
    (frames, n_descending_neurons); the labels are one value per frame.
    """
    if route not in ("retina", "feature"):
        raise ValueError("route must be 'retina' or 'feature'")

    brain = FlyBrain(device=device, seed=seed)
    retina = RetinaRoute(brain) if route == "retina" else None
    features = FeatureRoute(brain) if route == "feature" else None
    width = retina.width if retina else 64

    encoder = VisualSpikeEncoder(
        video,
        resolution=(height, width),
        mode="contrast",
        dt_ms=brain.dt * 1000.0,
    )
    trace = Trace(brain, types=["descending_neuron"], tau=0.1)

    activity, energy, asymmetry = [], [], []

    # Both routes need luminance and contrast from the same frame, so the video
    # is walked once and the ON/OFF difference is taken here.
    previous = None
    for count, frame in enumerate(encoder.frames()):
        if count >= frames:
            break
        if previous is None:
            contrast = np.zeros((2,) + frame.shape, np.float32)
        else:
            delta = frame - previous
            contrast = np.stack([np.clip(delta, 0, None), np.clip(-delta, 0, None)])
        previous = frame

        eye_drive = retina.drive(frame) if retina else None
        inject = features.inject(contrast) if features else ()

        # Hold this frame's drive for every simulation step it spans.
        for _ in range(encoder.steps_per_frame):
            fired = brain.step(eye_drive=eye_drive, inject=inject)
            trace.observe(fired)

        activity.append(trace.features())
        total, asym = stimulus_labels(contrast)
        energy.append(total)
        asymmetry.append(asym)

    return np.stack(activity), np.array(energy), np.array(asymmetry)


def score(activity: np.ndarray, energy: np.ndarray, asymmetry: np.ndarray, chunks: int = 10) -> dict:
    """Cross-validated readout scores, plus a shuffled-label control.

    Samples are grouped into contiguous time chunks and cross-validation is
    leave-one-chunk-out. Plain k-fold would put temporally adjacent frames in
    both train and test -- their traces overlap, so the score would be inflated.
    """
    groups = np.arange(len(activity)) * chunks // len(activity)
    median = np.median(asymmetry)
    side = (asymmetry > median).astype(float)

    rng = np.random.default_rng(0)
    shuffled = rng.permutation(side)

    return {
        "energy_r2": _r2(activity, energy, groups),
        "side_auc": Readout.fit(activity, side, kind="logistic", groups=groups).cv_score,
        "side_auc_shuffled": Readout.fit(activity, shuffled, kind="logistic", groups=groups).cv_score,
    }


def _r2(activity: np.ndarray, y: np.ndarray, groups: np.ndarray) -> float:
    """Readout.fit reports negative MSE for ridge; convert to R^2 so the number
    is comparable across targets with different scales."""
    readout = Readout.fit(activity, y, kind="ridge", groups=groups)
    return 1.0 - (-readout.cv_score) / float(np.var(y))


if __name__ == "__main__":
    import argparse
    import time

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", nargs="?", default="bad-apple.mp4")
    parser.add_argument("--frames", type=int, default=600)
    parser.add_argument("--device", default="auto")
    parser.add_argument("--route", default="both", choices=["retina", "feature", "both"])
    args = parser.parse_args()

    routes = ["retina", "feature"] if args.route == "both" else [args.route]
    results = {}
    for route in routes:
        start = time.time()
        activity, energy, asymmetry = run_route(
            args.video, route, frames=args.frames, device=args.device
        )
        elapsed = time.time() - start
        results[route] = score(activity, energy, asymmetry)
        active = int((activity[-1] > 0).sum())
        print(f"[{route}] {args.frames} frames in {elapsed:.0f}s  "
              f"({active}/{activity.shape[1]} descending neurons active at end)")

    print()
    print(f"{'route':10s} {'energy R^2':>12s} {'side AUC':>10s} {'shuffled':>10s}")
    for route, s in results.items():
        print(f"{route:10s} {s['energy_r2']:12.3f} {s['side_auc']:10.3f} {s['side_auc_shuffled']:10.3f}")
    print()
    print("shuffled ~0.5 means the real AUC is not an artefact of the fitting.")
