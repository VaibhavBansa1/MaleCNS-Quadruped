"""
Live module 5: connect the senses to the fly brain.

Takes the three senses for one moment in time and feeds them to flybrain:
    eyes  -> FeatureRoute (from fly_pipeline.py): LC4 / LPLC2 / LPLC1, left and right
    nose  -> NoseRoute (new, below): food-odour receptor neurons, left and right
    ears  -> StereoEarRoute (below): Johnston's organ JO-A / JO-B, left and right
Then it steps the brain and reports how fast each behaviour group is firing
(brain.groups: escape = DNp01, forward = DNg100, steer = DNa02, backward = MDN, ...).

Nothing in the connectome is changed or trained. We only choose which sensory
neurons get the input.

The brain is created with sensory_input=False (see docs/RESEARCH_NOTES.md): with it on, the
smell neurons excite each other into a runaway loop and smells add nothing.

Test it on its own, no camera or mic needed (fake inputs, prints firing rates):
    uv run python live/brain_link.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # so fly_pipeline.py is found

from flybrain import FlyBrain                       # noqa: E402
from fly_pipeline import CAP, EarRoute, FeatureRoute  # noqa: E402

# Olfactory receptor neurons for fruit / vinegar smells that flies walk towards.
# Each glomerulus (DM1, DM4, VA2, DM2) collects one receptor type.
FOOD_ODOUR_TYPES = ("ORN_DM1", "ORN_DM4", "ORN_VA2", "ORN_DM2")


class NoseRoute:
    """Smell strength (0..1, per side) -> voltage into the food-odour receptor neurons."""

    def __init__(self, brain: FlyBrain, gain: float = 0.8, types=FOOD_ODOUR_TYPES):
        all_types = brain.cell_type.astype(str)
        chosen = np.isin(all_types, types)
        if not chosen.any():
            print("NoseRoute: food-odour receptor types not found, using every ORN instead.")
            chosen = np.char.startswith(all_types, "ORN_")
        self.cells = {s: np.flatnonzero(chosen & (brain.side == s)) for s in "LR"}
        self.gain = gain
        print(f"NoseRoute: {len(self.cells['L'])} left + {len(self.cells['R'])} right smell neurons")

    def inject(self, left: float, right: float):
        pairs = []
        for side, level in (("L", left), ("R", right)):
            amount = np.float32(np.clip(level * self.gain, 0.0, CAP))
            if amount > 0 and len(self.cells[side]):
                pairs.append((self.cells[side], amount))
        return pairs


class StereoEarRoute:
    """Like EarRoute in fly_pipeline.py, but each antenna gets its own level.
    With two robot mics the fly can tell which side a sound came from.
    (EarRoute gives both sides the same level, right for a mono soundtrack.)"""

    def __init__(self, brain: FlyBrain):
        self.ear = EarRoute(brain)          # reuse its JO-A / JO-B neuron lists and gain

    def inject(self, song_left: float, fast_left: float, song_right: float, fast_right: float):
        levels = {"JO-B-L": song_left, "JO-A-L": fast_left, "JO-B-R": song_right, "JO-A-R": fast_right}
        pairs = []
        for key, level in levels.items():
            amount = np.float32(np.clip(level * self.ear.gain, 0.0, CAP))
            idx = self.ear.cells[key]
            if amount > 0 and len(idx):
                pairs.append((idx, amount))
        return pairs


class FlyBrainLink:
    def __init__(self, device: str = "auto", seed: int = 64, food_as_target: bool = False, rate_tau: float = 0.5):
        """
        food_as_target: also show the food to LC10a (the "target I am chasing" visual
            neurons). LC10a -> DNa02 is the steering route known to get through in this
            model, so this makes turning towards food more likely. Off by default so
            smell alone is tested first.
        rate_tau: seconds of smoothing on the firing rates.
        """
        self.brain = FlyBrain(device=device, seed=seed, sensory_input=False)
        self.eyes = FeatureRoute(self.brain)
        self.ears = StereoEarRoute(self.brain)
        self.nose = NoseRoute(self.brain)
        self.target = {s: self.brain.cells(["LC10a"], s) for s in "LR"} if food_as_target else None
        self.groups = dict(self.brain.groups)          # e.g. "escape_L" -> neuron indices
        self.rates = {name: 0.0 for name in self.groups}
        self.alpha = float(-np.expm1(-self.brain.dt / rate_tau))
        print(f"brain ready on {self.brain.device}, {self.brain.n:,} neurons, dt {self.brain.dt * 1000:.0f} ms")
        print("groups:", ", ".join(sorted(self.groups)))

    @property
    def dt(self) -> float:
        return self.brain.dt

    def step(self, contrast: np.ndarray, smell=(0.0, 0.0), sound=(0.0, 0.0, 0.0, 0.0), steps: int = 2) -> dict:
        """Feed one moment of input and run `steps` brain steps (20 ms each).
        contrast: (2, 16, 64) from FlyEye.look; smell: (left, right);
        sound: (song_left, fast_left, song_right, fast_right) from ear.py.
        Returns firing rate in Hz for every behaviour group."""
        if len(sound) == 2:                  # (song, fast): same for both ears
            sound = (sound[0], sound[1], sound[0], sound[1])
        inject = self.eyes.inject(contrast) + self.nose.inject(*smell) + self.ears.inject(*sound)
        if self.target is not None:
            for side, level in (("L", smell[0]), ("R", smell[1])):
                amount = np.float32(np.clip(level, 0.0, CAP))
                if amount > 0:
                    inject.append((self.target[side], amount))

        for _ in range(steps):
            fired = self.brain.step(inject=inject)
            self._update_rates(fired)
        return dict(self.rates)

    def rest(self, seconds: float = 1.0) -> dict:
        """Run with no input at all. Used to measure the resting baseline."""
        blank = np.zeros((2, 16, 64), np.float32)
        return self.step(blank, steps=max(1, int(seconds / self.dt)))

    def _update_rates(self, fired: np.ndarray) -> None:
        for name, idx in self.groups.items():
            if len(idx) == 0:
                continue
            hz = np.isin(idx, fired).sum() / len(idx) / self.dt
            self.rates[name] += self.alpha * (hz - self.rates[name])


def looming_frames(side: str, frames: int = 50):
    """Fake camera: a dark disc that grows on one side, like something approaching."""
    import cv2
    for i in range(frames):
        img = np.full((240, 320, 3), 200, np.uint8)
        x = 80 if side == "L" else 240
        cv2.circle(img, (x, 120), 5 + i * 3, (20, 20, 20), -1)
        yield img


if __name__ == "__main__":
    from fly_eye import FlyEye

    link = FlyBrainLink()
    keys = [k for k in ("escape_L", "escape_R", "steer_L", "steer_R", "forward_L", "forward_R",
                        "backward_L", "backward_R") if k in link.groups]

    def show(title, rates):
        print(f"{title:22s}" + "".join(f"{k:>11s} {rates[k]:5.2f}" for k in keys))

    import time
    link.rest(0.2)                      # first steps compile the CPU code; don't time them
    start = time.time()
    rest = link.rest(2.0)
    ms_per_step = (time.time() - start) / max(1, int(2.0 / link.dt)) * 1000
    print(f"speed: {ms_per_step:.1f} ms per 20 ms brain step  ->  "
          + ("real time OK" if ms_per_step < 20 else f"{ms_per_step / 20:.1f}x slower than real time"))
    show("resting", rest)

    eye = FlyEye()
    rates = rest
    for n, img in enumerate(looming_frames("L")):
        _, contrast = eye.look(img, n / 30.0)
        rates = link.step(contrast)
    show("looming on LEFT", rates)

    link.rest(2.0)
    blank = np.zeros((2, 16, 64), np.float32)
    for _ in range(50):
        rates = link.step(blank, smell=(1.0, 0.0))
    show("food smell on LEFT", rates)

    link.rest(2.0)
    for _ in range(50):
        rates = link.step(blank, sound=(1.0, 1.0, 0.0, 0.0))
    show("loud sound on LEFT", rates)

    print("\nCompare each line with 'resting'. Escape should jump for looming.")
