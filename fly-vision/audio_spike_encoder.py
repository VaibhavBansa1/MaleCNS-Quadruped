"""
Module 1b: Audio -> Johnston's organ drive.

The visual sibling of this module is `visual_spike_encoder`. Same contract:
turn a media file into per-frame drive values, at whatever rate the simulator
steps, and let the route modules decide which neurons receive them.

What a fly actually hears
-------------------------
A fly does not hear pressure waves the way we do. Its antenna is a feathery
arista that is physically pushed by the *particle velocity* of nearby air, and
Johnston's organ (JO) at its base reports that deflection. Consequences that
shape this encoder:

1. It is a near-field sense. Sensitivity runs roughly 100-900 Hz and falls off
   hard outside that. Anything above ~1 kHz in the soundtrack is inaudible to
   the fly and is discarded here rather than folded into a broadband level.

2. JO splits by what the deflection is doing, and only part of it is "hearing":
     JO-A  fast, higher-frequency vibration and transients   (~350-900 Hz)
     JO-B  the courtship-song band                            (~100-350 Hz)
     JO-C/D/E  static deflection -- gravity and wind, not sound
   So only JO-A and JO-B are driven. A loudspeaker does not tilt the fly, and
   pretending otherwise would put drive into a pathway the stimulus never
   touches.

3. The band that matters most is the fly's own song: sine song sits near
   150 Hz, pulse song carries at ~220-270 Hz in trains ~35 ms apart. That is
   squarely inside JO-B, which is why `song` is reported separately below --
   it is the channel the courtship pathway (pC1 -> pIP10 -> TN1) listens on.

Dependencies: numpy, scipy
"""

from __future__ import annotations

import numpy as np
from scipy.io import wavfile

# Hz. Outside FLY_RANGE the fly is effectively deaf, so it never enters the drive.
FLY_RANGE = (100.0, 900.0)
BAND_SONG = (100.0, 350.0)   # JO-B: sine ~150 Hz, pulse carrier ~220-270 Hz
BAND_FAST = (350.0, 900.0)   # JO-A: faster vibration, transients


class AuditoryEncoder:
    """Encode a wav file as per-frame Johnston's organ drive."""

    def __init__(
        self,
        wav_path: str,
        fps: float = 30.0,
        window_ms: float = 64.0,
        percentile: float = 99.0,
    ) -> None:
        """
        Parameters
        ----------
        wav_path : mono wav. Use ffmpeg to extract: `-ac 1 -ar 16000`.
        fps : frames per second to emit, matched to the video encoder so the
            two streams stay in step.
        window_ms : analysis window. 64 ms gives ~16 Hz resolution, enough to
            separate the song band from the faster band. Windows overlap.
        percentile : loudness percentile mapped to full drive. The max would
            let one transient flatten the whole track.
        """
        rate, data = wavfile.read(wav_path)
        if data.ndim > 1:
            data = data.mean(axis=1)
        data = data.astype(np.float32)
        peak = np.abs(data).max()
        if peak > 0:
            data /= peak

        self.rate = int(rate)
        self.samples = data
        self.fps = float(fps)
        self.hop = self.rate / self.fps
        self.window = int(round(window_ms / 1000.0 * self.rate))
        self.n_frames = max(0, int(len(data) / self.hop))

        freqs = np.fft.rfftfreq(self.window, 1.0 / self.rate)
        self.audible = (freqs >= FLY_RANGE[0]) & (freqs <= FLY_RANGE[1])
        self.song_bins = (freqs >= BAND_SONG[0]) & (freqs < BAND_SONG[1])
        self.fast_bins = (freqs >= BAND_FAST[0]) & (freqs <= BAND_FAST[1])
        self.taper = np.hanning(self.window).astype(np.float32)

        self._scale = None

    def _spectrum(self, index: int) -> np.ndarray:
        start = int(index * self.hop) - self.window // 2
        chunk = np.zeros(self.window, np.float32)
        lo, hi = max(0, start), min(len(self.samples), start + self.window)
        if hi > lo:
            chunk[lo - start:hi - start] = self.samples[lo:hi]
        return np.abs(np.fft.rfft(chunk * self.taper))

    def _calibrate(self) -> None:
        """One pass to find the loudness that should map to full drive."""
        probe = range(0, self.n_frames, max(1, self.n_frames // 400))
        song, fast = [], []
        for i in probe:
            s = self._spectrum(i)
            song.append(s[self.song_bins].mean())
            fast.append(s[self.fast_bins].mean())
        self._scale = (
            max(float(np.percentile(song, self.percentile_used)), 1e-9),
            max(float(np.percentile(fast, self.percentile_used)), 1e-9),
        )

    percentile_used = 99.0

    def bands(self):
        """Yield (song, fast) drive in 0..1 for each frame.

        `song` is JO-B's band and is what the courtship pathway reads;
        `fast` is JO-A's.
        """
        if self._scale is None:
            self._calibrate()
        song_scale, fast_scale = self._scale
        for i in range(self.n_frames):
            s = self._spectrum(i)
            yield (
                float(np.clip(s[self.song_bins].mean() / song_scale, 0.0, 1.0)),
                float(np.clip(s[self.fast_bins].mean() / fast_scale, 0.0, 1.0)),
            )

    def loudness(self) -> np.ndarray:
        """Per-frame level inside the fly's audible range only, 0..1.

        Useful as a label: it is read off the audio, never off the brain.
        """
        if self._scale is None:
            self._calibrate()
        out = np.array([self._spectrum(i)[self.audible].mean() for i in range(self.n_frames)])
        top = np.percentile(out, self.percentile_used)
        return np.clip(out / max(top, 1e-9), 0.0, 1.0)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: python audio_spike_encoder.py <audio.wav>")
        raise SystemExit(1)

    enc = AuditoryEncoder(sys.argv[1])
    print(f"sample rate : {enc.rate} Hz")
    print(f"frames      : {enc.n_frames} at {enc.fps:g} fps")
    print(f"window      : {enc.window} samples")
    print(f"fly hears   : {FLY_RANGE[0]:.0f}-{FLY_RANGE[1]:.0f} Hz")
    print(f"  JO-B song : {BAND_SONG[0]:.0f}-{BAND_SONG[1]:.0f} Hz")
    print(f"  JO-A fast : {BAND_FAST[0]:.0f}-{BAND_FAST[1]:.0f} Hz")
    print()

    bands = list(enc.bands())
    song = np.array([b[0] for b in bands])
    fast = np.array([b[1] for b in bands])
    print(f"song band : mean {song.mean():.3f}  max {song.max():.3f}")
    print(f"fast band : mean {fast.mean():.3f}  max {fast.max():.3f}")
    print()

    ramp = " .:-=+*#%@"
    width = 100
    step = max(1, len(song) // width)
    for name, series in (("JO-B song", song), ("JO-A fast", fast)):
        line = "".join(ramp[min(9, int(v * 9.99))] for v in series[::step][:width])
        print(f"{name}  {line}")
