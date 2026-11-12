"""
Live module 4: the ears.

Three ways to hear, all giving the same output, so you can use whichever works:
    EspMic     the robot's own mics (purple MAX4466 = left, red KY-037 = right),
               measured on the ESP32 and sent over the same USB cable as commands
    LaptopMic  the laptop's or a USB microphone (one channel, both ears hear the same)
    NoMic      silence, when nothing works

Every ear returns four numbers, 0..1:
    (song_left, fast_left, song_right, fast_right)
    song = 100-350 Hz -> Johnston's organ JO-B (courtship-song band)
    fast = 350-900 Hz -> JO-A (claps, taps, faster vibration)
The fly cannot hear outside 100-900 Hz, so nothing else is used.

Loudness is measured against the quiet room: calibrate() listens to one second
of silence, and "loud_ratio" times louder than that counts as full drive.
This also evens out the two different robot mics automatically.

make_mic("auto", robot) tries the robot mics, then the laptop mic, then silence.

Test on its own (clap, talk, tap the table):
    uv run python live/ear.py                 # laptop mic
    uv run python live/ear.py --list          # microphone numbers
    uv run python live/ear.py --mic 2         # a specific microphone
    uv run python live/ear.py --esp COM5      # the robot's mics
"""

from __future__ import annotations

import threading
import time

import numpy as np

SONG = (100.0, 350.0)
FAST = (350.0, 900.0)
LOUD_RATIO = 20.0


def to_levels(power: np.ndarray, noise: np.ndarray, loud_ratio: float = LOUD_RATIO) -> tuple:
    """Raw band power -> 0..1. 0 = as quiet as the room, 1 = loud_ratio times louder."""
    ratio = power / np.maximum(noise, 1e-6)
    return tuple(float(v) for v in np.clip((ratio - 1.0) / (loud_ratio - 1.0), 0.0, 1.0))


class LaptopMic:
    name = "laptop mic"

    def __init__(self, device=None, rate: int = 16000, window_ms: float = 64.0):
        import sounddevice as sd

        self.size = int(rate * window_ms / 1000.0)
        self.buffer = np.zeros(self.size, np.float32)   # always the newest 64 ms of sound
        self.lock = threading.Lock()
        self.noise = np.full(2, 1e-6)

        freqs = np.fft.rfftfreq(self.size, 1.0 / rate)
        self.song_bins = (freqs >= SONG[0]) & (freqs < SONG[1])
        self.fast_bins = (freqs >= FAST[0]) & (freqs <= FAST[1])
        self.taper = np.hanning(self.size).astype(np.float32)

        self.stream = sd.InputStream(device=device, channels=1, samplerate=rate, callback=self._on_sound)
        self.stream.start()

    def _on_sound(self, indata, frames, time_info, status):
        new = indata[:, 0]
        with self.lock:
            if len(new) >= self.size:
                self.buffer[:] = new[-self.size:]
            else:
                self.buffer = np.roll(self.buffer, -len(new))
                self.buffer[-len(new):] = new

    def _power(self) -> np.ndarray:
        with self.lock:
            chunk = self.buffer.copy()
        spectrum = np.abs(np.fft.rfft(chunk * self.taper))
        return np.array([spectrum[self.song_bins].mean(), spectrum[self.fast_bins].mean()])

    def calibrate(self, seconds: float = 1.0) -> None:
        samples = []
        end = time.time() + seconds
        while time.time() < end:
            samples.append(self._power())
            time.sleep(0.03)
        self.noise = np.mean(samples, axis=0)

    def levels(self) -> tuple:
        song, fast = to_levels(self._power(), self.noise)
        return song, fast, song, fast          # one mic: both ears hear the same

    def close(self) -> None:
        self.stream.stop()
        self.stream.close()


class EspMic:
    """The robot's two mics. The ESP32 does the band filtering and sends M lines."""

    name = "robot mics"

    def __init__(self, robot, wait_seconds: float = 1.5):
        self.robot = robot
        self.noise = np.full(4, 1e-6)
        robot.start_mic()
        end = time.time() + wait_seconds
        while time.time() < end:
            values, age = robot.latest_mic()
            if values is not None and age < 0.5:
                return
            time.sleep(0.05)
        raise IOError("no mic data from the ESP32 (is the mic firmware uploaded?)")

    def _power(self):
        values, age = self.robot.latest_mic()
        if values is None or age > 1.0:        # mic stopped talking
            return None
        return np.array(values)

    def calibrate(self, seconds: float = 1.0) -> None:
        samples = []
        end = time.time() + seconds
        while time.time() < end:
            power = self._power()
            if power is not None:
                samples.append(power)
            time.sleep(0.05)
        if samples:
            self.noise = np.mean(samples, axis=0)

    def levels(self) -> tuple:
        power = self._power()
        if power is None:
            return 0.0, 0.0, 0.0, 0.0
        return to_levels(power, self.noise)

    def close(self) -> None:
        pass                                   # the robot link closes the port


class NoMic:
    name = "no mic"

    def __init__(self, reason: str = ""):
        if reason:
            self.name = f"no mic ({reason})"

    def calibrate(self, seconds: float = 1.0):
        pass

    def levels(self):
        return 0.0, 0.0, 0.0, 0.0

    def close(self):
        pass


def make_mic(kind: str = "auto", robot=None, device=None):
    """kind: "auto", "esp", "laptop" or "none". Falls back instead of crashing."""
    order = {"auto": ["esp", "laptop"], "esp": ["esp"], "laptop": ["laptop"], "none": []}[kind]
    reason = "turned off" if kind == "none" else ""
    for choice in order:
        try:
            if choice == "esp":
                if robot is None or type(robot).__name__ == "NoRobot":
                    raise IOError("no robot connected")
                mic = EspMic(robot)
            else:
                mic = LaptopMic(device=device)
            print(f"ear: using {mic.name}")
            return mic
        except Exception as error:
            print(f"ear: {choice} mic not available ({error})")
            if "sounddevice" in str(error):
                reason = "run: uv pip install sounddevice"
            elif choice == "laptop":
                reason = "mic did not open, see terminal"
    print(f"ear: using no mic {reason}")
    return NoMic(reason)


def list_mics() -> list[tuple[int, str]]:
    """Microphones only, each one once.
    Windows lists every device several times (MME, DirectSound, WASAPI, WDM-KS);
    only the first family (MME, the normal one) is kept."""
    import sounddevice as sd

    first_api = 0
    mics = []
    for number, device in enumerate(sd.query_devices()):
        if device["max_input_channels"] > 0 and device["hostapi"] == first_api:
            mics.append((number, device["name"]))
    return mics


def default_mic_name() -> str:
    import sounddevice as sd
    try:
        return sd.query_devices(kind="input")["name"]
    except Exception:
        return "none"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test the fly's ears.")
    parser.add_argument("--mic", default=None, help="microphone number from --list (default: the Windows default mic)")
    parser.add_argument("--esp", default=None, help="robot serial port, e.g. COM5, to test the robot mics")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        print(f"Windows default mic: {default_mic_name()}")
        print("Microphones (use the number with --mic-device):")
        for number, name in list_mics():
            hint = "   <- virtual, not a real mic" if any(w in name.lower() for w in ("virtual", "voicemeeter", "cable", "stereo mix")) else ""
            print(f"  {number:3d}  {name}{hint}")
        raise SystemExit

    robot = None
    if args.esp:
        from robot_link import Robot
        robot = Robot(args.esp, watchdog_ms=0)
        mic = make_mic("esp", robot)
    else:
        mic = make_mic("laptop", device=int(args.mic) if args.mic is not None else None)
        if args.mic is None:
            print(f"listening on: {default_mic_name()}")

    print("Stay quiet for 1 second...")
    mic.calibrate()
    print("Now make noise. Ctrl+C to stop.")
    try:
        while True:
            sl, fl, sr, fr = mic.levels()
            print(f"\rLEFT song {'#' * int(sl * 15):15s} fast {'#' * int(fl * 15):15s} | "
                  f"RIGHT song {'#' * int(sr * 15):15s} fast {'#' * int(fr * 15):15s}", end="")
            time.sleep(0.05)
    except KeyboardInterrupt:
        print()
    mic.close()
    if robot:
        robot.close()
