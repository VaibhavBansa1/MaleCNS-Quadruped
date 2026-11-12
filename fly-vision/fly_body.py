"""
Module 4: give the brain a body.

Video and audio -> my flybrain -> descending neurons -> gait -> fly-arena's
MuJoCo body. The fly physically walks in response to what it sees and hears.

Why the bridge looks like this
------------------------------
fly-arena does NOT use flybrain. It ships its own LIF simulator over its own
copy of the connectome (`fly-arena/data/graph/`), so there is no way to hand it
my brain: `Brain` is constructed internally (`fly_arena/ethology.py`,
`fly_arena/__main__.py`) with no injection parameter, and `NeuralAdapter`
validates the dataset manifest.

What it *does* expose is the body on its own: `Arena.step(command)` takes two
floats in 0..1.2 -- left and right stride magnitude -- and runs FlyGym's
hybrid CPG controller and the physics. So this module skips fly-arena's brain
entirely and drives the body directly.

`GaitDecoder` below mirrors fly-arena's own `MotorDecoder`
(`fly_arena/brain.py:71-87`) so the mapping is theirs, not invented here:
    speed = speed_gain * (mean DNp09 rate - mean MDN rate)
    turn  = turn_gain  * (DNa02 left rate - DNa02 right rate)
    command = clip([speed - turn, speed + turn], 0, 1.2)
All three cell types exist in flybrain's connectome (DNa02 1L/1R, DNp09 1L/1R,
MDN 2L/2R), so the same decode runs on my brain unchanged.

Escape is handled separately, because it has to be. Under a looming stimulus
the connectome's walking channel is nearly silent (DNp09 ~0.1 Hz) while DNp01,
the escape giant fibre, runs at ~8 Hz -- the fly is not trying to walk, it is
trying to flee. `MotorDecoder` never reads DNp01, so on that path alone the fly
just stands there.

So DNp01 selects fly-arena's own ESCAPE primitive (`fly_arena/motor.py:190-205`),
a scripted turn-and-run, and the left/right DNp01 imbalance sets which way it
turns. The split is deliberate: the connectome decides *whether and which way*
to flee, fly-arena's engineered primitive decides *how legs move*. No
motor-neuron-to-muscle mapping is invented here -- nobody has a validated one.

Run from the fly-arena venv, which has MuJoCo and FlyGym:
    cd fly-arena
    ./.venv/Scripts/python.exe ../fly-vision/fly_body.py --seconds 20
"""

from __future__ import annotations

import numpy as np

CELL_TYPES = ("DNa02", "DNp09", "MDN")


class GaitDecoder:
    """Descending-neuron spikes -> a two-element stride command for the body."""

    def __init__(self, brain, speed_gain: float = 0.022, turn_gain: float = 0.016, tau: float = 0.1):
        types = brain.cell_type.astype(str)
        self.ports = {
            kind: [np.flatnonzero((types == kind) & (brain.side == s)) for s in ("L", "R")]
            for kind in CELL_TYPES
        }
        self.rates = {kind: np.zeros(2) for kind in CELL_TYPES}
        self.speed_gain = speed_gain
        self.turn_gain = turn_gain
        self.tau = tau
        self.last = np.zeros(2)

    def update(self, fired: np.ndarray, seconds: float) -> np.ndarray:
        alpha = -np.expm1(-seconds / self.tau)
        for kind, sides in self.ports.items():
            for i, idx in enumerate(sides):
                rate = float(np.isin(idx, fired).sum() / len(idx) / seconds) if len(idx) else 0.0
                self.rates[kind][i] += alpha * (rate - self.rates[kind][i])
        speed = np.clip(self.speed_gain * (self.rates["DNp09"].mean() - self.rates["MDN"].mean()), 0, 1)
        turn = np.clip(self.turn_gain * (self.rates["DNa02"][0] - self.rates["DNa02"][1]), -0.65, 0.65)
        # A leftward command reduces left-side stride magnitude.
        self.last = np.clip([speed - turn, speed + turn], 0, 1.2)
        return self.last


class Decision:
    """What fly-arena's motor arbiter expects: an action and an escape direction."""

    def __init__(self, action: str, escape_turn: float = 0.0):
        self.action = action
        self.escape_turn = escape_turn


def run(video: str, wav: str | None, seconds: float, out: str | None,
        steps_per_frame: int = 3, seed: int = 0, quiet: bool = False,
        escape_threshold: float = 1.5):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))

    from flybrain import FlyBrain, Trace
    from fly_arena.ethology_arena import EthologyArena
    from fly_pipeline import EarRoute, FeatureRoute
    from visual_spike_encoder import VisualSpikeEncoder

    fps = 30.0
    ms = 1000.0 / fps / steps_per_frame          # 11.1 ms of world per brain step
    brain = FlyBrain(device="auto", seed=64, sensory_input=False, dt=ms / 1000.0)
    eyes = FeatureRoute(brain)
    ears = EarRoute(brain) if wav else None
    decoder = GaitDecoder(brain)
    escape = Trace(brain, idx=np.concatenate([brain.groups["escape_L"], brain.groups["escape_R"]]), tau=0.25)
    escape_sides = [brain.groups["escape_L"], brain.groups["escape_R"]]
    side_rate = np.zeros(2)

    enc = VisualSpikeEncoder(video, resolution=(16, 64), mode="contrast", dt_ms=ms)
    audio = None
    if wav:
        from audio_spike_encoder import AuditoryEncoder
        audio = list(AuditoryEncoder(wav, fps=fps).bands())

    arena = EthologyArena(seed=seed)
    writer = None
    if out:
        import imageio.v2 as imageio
        writer = imageio.get_writer(out, fps=fps, macro_block_size=None)

    n_frames = int(seconds * fps)
    track, log = [], []
    previous = None

    for i, frame in enumerate(enc.frames()):
        if i >= n_frames:
            break
        if previous is None:
            contrast = np.zeros((2,) + frame.shape, np.float32)
        else:
            d = frame - previous
            contrast = np.stack([np.clip(d, 0, None), np.clip(-d, 0, None)])
        previous = frame

        inject = eyes.inject(contrast)
        if audio and i < len(audio):
            inject += ears.inject(*audio[i])

        for _ in range(steps_per_frame):
            fired = brain.step(inject=inject)
            escape.observe(fired)
            command = decoder.update(fired, ms / 1000.0)

            alpha = -np.expm1(-(ms / 1000.0) / 0.1)
            for s, idx in enumerate(escape_sides):
                side_rate[s] += alpha * (float(np.isin(idx, fired).sum()) / len(idx) / (ms / 1000.0) - side_rate[s])

            alarm = float(escape.features().mean())
            if alarm >= escape_threshold:
                # Flee away from the side that fired harder.
                bias = side_rate[0] - side_rate[1]
                turn = float(np.clip(bias / max(side_rate.sum(), 1e-6), -1.0, 1.0))
                decision = Decision("ESCAPE", escape_turn=-turn)
            else:
                decision = Decision("WALK")
            arena.step_behavior(decision, command, milliseconds=ms)

        track.append(arena.position[:2].copy())
        log.append((float(command[0]), float(command[1]), alarm, float(arena.heading),
                    1.0 if decision.action == "ESCAPE" else 0.0))
        if writer:
            writer.append_data(arena.render())
        if not quiet and i % 30 == 0:
            print(f"  {i/fps:5.1f}s  {decision.action:6s} gait [{command[0]:.2f} {command[1]:.2f}]  "
                  f"heading {arena.heading:+.2f}  pos {np.round(arena.position[:2], 1)}  "
                  f"escape {alarm:.2f}")

    if writer:
        writer.close()
    upright = float(arena.upright)
    arena.close()

    track = np.array(track)
    distance = float(np.linalg.norm(np.diff(track, axis=0), axis=1).sum()) if len(track) > 1 else 0.0
    return {"track": track, "log": np.array(log), "distance": distance, "upright": upright}


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--video", default="bad-apple.mp4")
    p.add_argument("--wav", default=None, help="optional soundtrack, drives Johnston's organ")
    p.add_argument("--seconds", type=float, default=12.0)
    p.add_argument("--out", default=None, help="write an mp4 of the walking fly")
    args = p.parse_args()

    r = run(args.video, args.wav, args.seconds, args.out)
    g = r["log"]
    print(f"\ndistance walked : {r['distance']:.1f} body units")
    print(f"net displacement: {np.linalg.norm(r['track'][-1] - r['track'][0]):.1f}")
    print(f"heading change  : {g[-1, 3] - g[0, 3]:+.2f} rad")
    print(f"gait L/R        : mean {g[:, 0].mean():.3f} / {g[:, 1].mean():.3f}")
    print(f"escape trace    : mean {g[:, 2].mean():.2f}  max {g[:, 2].max():.2f}")
    print(f"time fleeing    : {g[:, 4].mean()*100:.0f}% of frames")
    print(f"still upright   : {r['upright']:.3f}")
    if args.out:
        print(f"wrote {args.out}")
