"""
Stage-by-stage inspector for the video -> connectome -> readout pipeline.

Prints what every stage actually holds for a given frame, so the pipeline can
be watched rather than just scored. Run it when a number looks wrong and you
need to find which stage produced it.

    python inspect_pipeline.py --frames 6 --route feature
    python inspect_pipeline.py --start 1500 --frames 3 --route retina
    python inspect_pipeline.py --export run.npz --frames 900   # for plotting

Stages, in the order they run:
    1 luminance   16x72 grayscale, 0..1
    2 contrast    ON/OFF split from the frame difference
    3 drive       what actually enters the brain (differs per route)
    4 brain       which of the 166,700 neurons fired this step
    5 trace       decaying activity of the 1,314 descending neurons
"""

from __future__ import annotations

import argparse
import numpy as np

from flybrain import FlyBrain, Trace
from fly_pipeline import FeatureRoute, RetinaRoute, stimulus_labels
from visual_spike_encoder import VisualSpikeEncoder

RAMP = " .:-=+*#%@"


def shade(matrix: np.ndarray, vmax: float | None = None) -> str:
    """Render a 2-D array as shaded text. vmax=None scales to the frame's own max."""
    top = float(matrix.max()) if vmax is None else vmax
    if top <= 0:
        top = 1.0
    levels = np.clip(matrix / top * (len(RAMP) - 1), 0, len(RAMP) - 1).astype(int)
    return "\n".join("".join(RAMP[v] for v in row) for row in levels)


def bar(values: np.ndarray, width: int = 72) -> str:
    """One-line bar chart of a 1-D array."""
    top = float(values.max())
    if top <= 0:
        return " " * width
    levels = np.clip(values / top * (len(RAMP) - 1), 0, len(RAMP) - 1).astype(int)
    return "".join(RAMP[v] for v in levels)


def inspect(video: str, route: str, start: int, count: int, device: str, export: str | None):
    brain = FlyBrain(device=device)
    retina = RetinaRoute(brain) if route == "retina" else None
    features = FeatureRoute(brain) if route == "feature" else None
    width = retina.width if retina else 64

    encoder = VisualSpikeEncoder(video, resolution=(16, width), mode="contrast", dt_ms=brain.dt * 1000.0)
    trace = Trace(brain, types=["descending_neuron"], tau=0.1)
    descending = brain.cells(["descending_neuron"])

    print(f"video      : {video}  @ {encoder.video_fps:.0f} fps")
    print(f"route      : {route}")
    print(f"device     : {brain.device}   dt = {brain.dt * 1000:.0f} ms")
    print(f"frame span : {encoder.steps_per_frame} simulation steps")
    print(f"neurons    : {brain.n:,} total, {len(descending):,} descending")
    if retina:
        print(f"drive      : {len(brain.visual):,} photoreceptors over {retina.width} optic columns")
    else:
        types = ", ".join(f"{t}({len(features.cells[t]['L'])}L+{len(features.cells[t]['R'])}R)"
                          for t in features.cells)
        print(f"drive      : {types}")

    log = {"energy": [], "asymmetry": [], "fired": [], "dn_fired": [], "drive_mean": [], "trace": []}
    previous = None

    for index, frame in enumerate(encoder.frames()):
        if index >= start + count:
            break

        if previous is None:
            contrast = np.zeros((2,) + frame.shape, np.float32)
        else:
            delta = frame - previous
            contrast = np.stack([np.clip(delta, 0, None), np.clip(-delta, 0, None)])
        previous = frame

        eye_drive = retina.drive(frame) if retina else None
        inject = features.inject(contrast) if features else ()

        dn_fired = 0
        total_fired = 0
        for _ in range(encoder.steps_per_frame):
            fired = brain.step(eye_drive=eye_drive, inject=inject)
            trace.observe(fired)
            total_fired += len(fired)
            dn_fired += int(np.isin(fired, descending).sum())

        energy, asymmetry = stimulus_labels(contrast)
        drive_mean = float(eye_drive.mean()) if retina else float(np.mean([a for _, a in inject]) if inject else 0.0)
        log["energy"].append(energy)
        log["asymmetry"].append(asymmetry)
        log["fired"].append(total_fired / encoder.steps_per_frame)
        log["dn_fired"].append(dn_fired / encoder.steps_per_frame)
        log["drive_mean"].append(drive_mean)
        log["trace"].append(trace.features())

        if index < start or export:
            continue

        on, off = contrast
        print()
        print("=" * 78)
        print(f"FRAME {index}   t = {index / encoder.video_fps:6.2f}s")
        print("=" * 78)

        print(f"\n-- 1 luminance ------------------------------- mean {frame.mean():.3f}")
        print(shade(frame, vmax=1.0))

        print(f"\n-- 2 contrast -------------------------------- ON mean {on.mean():.4f}  "
              f"OFF mean {off.mean():.4f}")
        print("ON  (brightening)")
        print(shade(on))
        print("OFF (darkening)")
        print(shade(off))

        print("\n-- 3 drive -----------------------------------")
        if retina:
            panorama = eye_drive[np.argsort(retina.column_of_receptor, kind="stable")]
            columns = np.array([eye_drive[retina.column_of_receptor == c].mean()
                                for c in range(retina.width)])
            print(f"{len(eye_drive):,} photoreceptors   mean {eye_drive.mean():.3f}  max {eye_drive.max():.3f}")
            print("per optic column (left -> right):")
            print(bar(columns, retina.width))
            del panorama
        else:
            if not inject:
                print("(silent — no channel above zero)")
            for idx, amount in inject:
                name = next(f"{t}-{s}" for t in features.cells for s in "LR"
                            if features.cells[t][s] is idx)
                filled = int(float(amount) / 0.8 * 40)
                print(f"  {name:9s} {float(amount):.3f}  {'#' * filled}")

        print("\n-- 4 brain -----------------------------------")
        print(f"fired {total_fired / encoder.steps_per_frame:8.0f} / {brain.n:,} neurons per step "
              f"({total_fired / encoder.steps_per_frame / brain.n * 100:.2f}%)")
        print(f"      {dn_fired / encoder.steps_per_frame:8.0f} / {len(descending):,} descending "
              f"({dn_fired / encoder.steps_per_frame / len(descending) * 100:.2f}%)")

        activity = trace.features()
        print(f"\n-- 5 trace (1,314 descending neurons) -------- mean {activity.mean():.3f}  "
              f"max {activity.max():.3f}")
        print("strongest 72 neurons:")
        print(bar(np.sort(activity)[::-1][:72]))

        print(f"\n-- labels (read off the video, not the brain) -")
        print(f"energy {energy:.4f}   asymmetry (L-R) {asymmetry:+.4f}")

    if export:
        np.savez_compressed(export, **{k: np.array(v) for k, v in log.items()})
        print(f"\nwrote {export}: {len(log['energy'])} frames, "
              f"trace {np.array(log['trace']).shape}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", nargs="?", default="bad-apple.mp4")
    parser.add_argument("--route", default="feature", choices=["retina", "feature"])
    parser.add_argument("--start", type=int, default=1200, help="first frame to print")
    parser.add_argument("--frames", type=int, default=4, help="how many frames to print")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--export", help="run silently and save per-frame series to this .npz")
    args = parser.parse_args()

    inspect(args.video, args.route, args.start, args.frames, args.device, args.export)
