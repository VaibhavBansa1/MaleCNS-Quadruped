"""
Module 1: Video -> Spike Encoder

Turns a video file into Poisson spike trains suitable for injection into a
spiking network (e.g. a connectome-based SNN).

Design notes
------------
1. Video frames and simulation timesteps run at different rates.
   A 30 fps video gives one frame every ~33 ms; an LIF simulation typically
   steps every ~1 ms. So each frame's firing RATE is held constant for
   `steps_per_frame` timesteps, with an independent Poisson draw each step.
   The encoder therefore yields one spike matrix per TIMESTEP, not per frame.

2. Fly motion-vision neurons respond to CHANGE in luminance, not absolute
   brightness. Default mode is "contrast": the frame difference is split into
   an ON channel (brightening) and an OFF channel (darkening), mirroring the
   L1/L2 split in the real circuit. Mode "luminance" is available for
   comparison but will fire continuously on a static bright scene.

3. Resolution is configurable and should be chosen to match the number of
   target neurons in your network, not picked arbitrarily.

Dependencies: opencv-python, numpy
"""

from __future__ import annotations

import numpy as np
import cv2


class VisualSpikeEncoder:
    """Encode a video file as Poisson spike trains."""

    def __init__(
        self,
        video_path: str,
        resolution: tuple[int, int] = (32, 32),
        mode: str = "contrast",
        max_rate_hz: float = 200.0,
        dt_ms: float = 1.0,
        video_fps: float | None = None,
        rng_seed: int | None = None,
    ) -> None:
        """
        Parameters
        ----------
        video_path : path to the input video.
        resolution : (height, width) of the downscaled frame. Should be chosen
            so height*width matches (or maps cleanly onto) your neuron count.
        mode : "contrast" (ON/OFF channels from frame difference) or
            "luminance" (raw brightness).
        max_rate_hz : firing rate corresponding to a normalized value of 1.0.
            Biological photoreceptor rates are on the order of 100-300 Hz.
        dt_ms : simulation timestep in milliseconds. Must match your SNN's dt.
        video_fps : override the video's own fps. Leave None to read it from
            the file.
        rng_seed : seed for reproducible spike draws.
        """
        if mode not in ("contrast", "luminance"):
            raise ValueError("mode must be 'contrast' or 'luminance'")

        self.video_path = video_path
        self.resolution = resolution
        self.mode = mode
        self.max_rate_hz = float(max_rate_hz)
        self.dt_s = dt_ms / 1000.0
        self.rng = np.random.default_rng(rng_seed)

        # Probe the file once for fps, then release. Each iteration reopens it.
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise IOError(f"Could not open video: {video_path}")
        detected_fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()

        self.video_fps = float(video_fps or detected_fps or 30.0)

        # How many simulation steps each frame is held for.
        frame_duration_s = 1.0 / self.video_fps
        self.steps_per_frame = max(1, int(round(frame_duration_s / self.dt_s)))

    # ------------------------------------------------------------------
    # Stage 1: frames -> normalized grayscale
    # ------------------------------------------------------------------
    def frames(self):
        """Yield normalized (0.0-1.0) grayscale frames at the target resolution."""
        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            raise IOError(f"Could not open video: {self.video_path}")

        height, width = self.resolution
        try:
            while True:
                ok, frame = cap.read()
                if not ok:
                    break

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                # INTER_AREA is the correct choice for downscaling: it averages
                # over the source region rather than point-sampling, which is
                # closer to what an ommatidium actually does.
                small = cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA)
                yield small.astype(np.float32) / 255.0
        finally:
            cap.release()

    # ------------------------------------------------------------------
    # Stage 2: frames -> firing rate maps (Hz)
    # ------------------------------------------------------------------
    def rate_maps(self):
        """
        Yield a firing-rate map (in Hz) per frame.

        In "contrast" mode the returned array has shape (2, H, W):
        channel 0 = ON  (regions that got brighter)
        channel 1 = OFF (regions that got darker)

        In "luminance" mode the shape is (H, W).
        """
        previous = None

        for frame in self.frames():
            if self.mode == "luminance":
                yield frame * self.max_rate_hz
                continue

            if previous is None:
                # No previous frame yet, so no change to report. Emit silence
                # rather than a spurious full-field transient.
                previous = frame
                yield np.zeros((2,) + frame.shape, dtype=np.float32)
                continue

            delta = frame - previous
            on_channel = np.clip(delta, 0.0, None)    # brightening
            off_channel = np.clip(-delta, 0.0, None)  # darkening
            previous = frame

            rates = np.stack([on_channel, off_channel]) * self.max_rate_hz
            yield rates.astype(np.float32)

    def contrast_maps(self):
        """Yield the same maps as `rate_maps` but normalized to 0.0-1.0.

        Voltage-driven simulators (flybrain's `eye_drive` / `inject`) want a
        graded 0-1 level, not binary spikes -- they do their own thresholding.
        Use this instead of `spikes()` for those.
        """
        for rates in self.rate_maps():
            yield np.clip(rates / self.max_rate_hz, 0.0, 1.0)

    # ------------------------------------------------------------------
    # Stage 3: rate maps -> Poisson spikes, one draw per simulation timestep
    # ------------------------------------------------------------------
    def spikes(self):
        """
        Yield one binary spike array per SIMULATION TIMESTEP.

        Each frame's rate map is held for `steps_per_frame` steps, with an
        independent Bernoulli draw each step. This is the standard discrete
        approximation to a Poisson process: for small dt, the probability of
        a spike in one step is rate * dt.
        """
        for rates in self.rate_maps():
            # p = rate * dt, clipped to 1.0. If rates routinely exceed
            # 1/dt (1000 Hz at dt=1ms) the approximation breaks down and you
            # should lower max_rate_hz instead.
            probabilities = np.clip(rates * self.dt_s, 0.0, 1.0)

            for _ in range(self.steps_per_frame):
                draw = self.rng.random(probabilities.shape)
                yield (draw < probabilities).astype(np.uint8)

    # ------------------------------------------------------------------
    # Convenience: flatten to a 1-D vector for injection into a neuron list
    # ------------------------------------------------------------------
    def spike_vectors(self):
        """Yield each timestep's spikes flattened to 1-D.

        The flattened length is H*W (luminance) or 2*H*W (contrast). Match
        this against the number of target neurons before wiring it up.
        """
        for spikes in self.spikes():
            yield spikes.reshape(-1)

    @property
    def output_size(self) -> int:
        """Number of values emitted per timestep."""
        height, width = self.resolution
        return height * width * (2 if self.mode == "contrast" else 1)


def _render(matrix: np.ndarray) -> str:
    """Render a binary matrix as text so spikes are visible at a glance."""
    return "\n".join("".join("#" if v else "." for v in row) for row in matrix)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python visual_spike_encoder.py <video.mp4>")
        raise SystemExit(1)

    encoder = VisualSpikeEncoder(
        sys.argv[1],
        resolution=(32, 32),
        mode="contrast",
        max_rate_hz=200.0,
        dt_ms=1.0,
        rng_seed=0,
    )

    print(f"video fps          : {encoder.video_fps:.2f}")
    print(f"steps per frame    : {encoder.steps_per_frame}")
    print(f"values per timestep: {encoder.output_size}")
    print()

    # Skip the first frame (always silent, no previous frame to compare) and
    # the rest of that frame's timesteps, so we land on real contrast data.
    stream = encoder.spikes()
    for _ in range(encoder.steps_per_frame):
        next(stream)

    sample = next(stream)
    on_channel, off_channel = sample[0], sample[1]

    print(f"ON channel  ({int(on_channel.sum())} spikes)")
    print(_render(on_channel))
    print()
    print(f"OFF channel ({int(off_channel.sum())} spikes)")
    print(_render(off_channel))
    print()

    # Sanity check: measured spike probability should land near rate*dt.
    total = 0
    steps = 0
    for spikes in encoder.spikes():
        total += int(spikes.sum())
        steps += 1
        if steps >= 500:
            break
    print(f"mean spikes/timestep over {steps} steps: {total / steps:.2f}")
