"""
Live module 7: the USB link to the robot's ESP32.

One serial connection does two jobs:
  * sends commands to the gait firmware (F, B, L, R, S), repeated every 0.2 s so
    the firmware's watchdog (W 500) stops the robot if the laptop freezes;
  * receives microphone levels from the same ESP32. The firmware sends lines like
        M 12.3 4.5 10.1 3.9      (song left, fast left, song right, fast right)
    after the PC sends "M 1". A background thread keeps the newest values.

Needs:  uv pip install pyserial

Test it on its own (type letters, Enter to send; "M 1" shows mic lines):
    uv run python live/robot_link.py COM5
"""

from __future__ import annotations

import threading
import time


class Robot:
    def __init__(self, port: str, baud: int = 115200, watchdog_ms: int = 500, echo: bool = False):
        import serial

        self.serial = serial.Serial(port, baud, timeout=0.1)
        time.sleep(2.0)                    # the ESP32 restarts when the port opens
        self.serial.reset_input_buffer()
        self.echo = echo                   # print every line the ESP32 sends (for testing)
        self.mic = None                    # newest (songL, fastL, songR, fastR), raw units
        self.mic_time = 0.0
        self.lock = threading.Lock()
        self.running = True
        self.reader = threading.Thread(target=self._read_lines, daemon=True)
        self.reader.start()

        self.send(f"W {watchdog_ms}")
        self.last_command = None
        self.last_sent = 0.0
        self.last_status = 0.0

    def _read_lines(self):
        while self.running:
            try:
                line = self.serial.readline().decode(errors="ignore").strip()
            except Exception:
                break
            if not line:
                continue
            if self.echo:
                print(f"\n< {line}")
            if line.startswith("M "):
                try:
                    values = tuple(float(v) for v in line.split()[1:5])
                except ValueError:
                    continue
                if len(values) == 4:
                    with self.lock:
                        self.mic = values
                        self.mic_time = time.time()

    def send(self, text: str) -> None:
        self.serial.write((text + "\n").encode())

    def command(self, letter: str) -> None:
        """Send a new command at once, or repeat the same one every 0.2 s."""
        now = time.time()
        if letter != self.last_command or now - self.last_sent > 0.2:
            self.send(letter)
            self.last_command = letter
            self.last_sent = now

    def status(self, brain_mode: bool, steer: float, escape: bool) -> None:
        """For the robot's OLED face and head: mode, steering (-1 left .. +1 right), escape.
        Sent at most every 0.15 s."""
        now = time.time()
        if now - self.last_status > 0.15:
            steer = max(-1.0, min(1.0, steer))
            self.send(f"E {1 if brain_mode else 0} {steer:.2f} {1 if escape else 0}")
            self.last_status = now

    def start_mic(self) -> None:
        self.send("M 1")

    def latest_mic(self):
        """(values, age_in_seconds). values is None if nothing has arrived yet."""
        with self.lock:
            return self.mic, time.time() - self.mic_time

    def close(self) -> None:
        try:
            self.send("M 0")
            self.send("S")
            time.sleep(0.05)
        finally:
            self.running = False
            self.serial.close()


class NoRobot:
    """Stand-in when no robot is plugged in: commands go nowhere, no mic."""

    def command(self, letter: str) -> None:
        pass

    def status(self, brain_mode: bool, steer: float, escape: bool) -> None:
        pass

    def start_mic(self) -> None:
        pass

    def latest_mic(self):
        return None, 1e9

    def close(self) -> None:
        pass


def find_esp32_port():
    """The first USB-serial port that looks like an ESP32 board (CP210x / CH340 chips)."""
    from serial.tools import list_ports

    for info in list_ports.comports():
        text = f"{info.description} {info.manufacturer} {info.hwid}".lower()
        if any(chip in text for chip in ("cp210", "ch340", "ch910", "silicon labs", "usb-serial", "10c4:ea60", "1a86")):
            return info.device
    return None


def list_serial_ports():
    from serial.tools import list_ports
    return [(info.device, info.description) for info in list_ports.comports()]


def make_robot(port: str | None):
    """Open the robot, or carry on without it if the port does not work.
    port "auto" finds the ESP32 by itself."""
    if not port:
        print("robot: no --port given, running without the robot")
        return NoRobot()
    if port == "auto":
        try:
            port = find_esp32_port()
        except ImportError:
            print("robot: pyserial missing (uv pip install pyserial)")
            return NoRobot()
        if port is None:
            print("robot: no ESP32 found. Plugged in? Ports seen:", list_serial_ports() or "none")
            return NoRobot()
        print(f"robot: found ESP32 on {port}")
    try:
        robot = Robot(port)
        print(f"robot: connected on {port}")
        return robot
    except Exception as error:
        print(f"robot: could not open {port} ({error}). Running without the robot.")
        return NoRobot()


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2 or sys.argv[1] == "--list":
        print("serial ports:")
        for device, description in list_serial_ports():
            print(f"  {device}   {description}")
        print("usage: python live/robot_link.py COM5   (or: auto)")
        raise SystemExit
    port = find_esp32_port() if sys.argv[1] == "auto" else sys.argv[1]
    if port is None:
        raise SystemExit("no ESP32 found")
    print(f"opening {port}")
    robot = Robot(port, watchdog_ms=0, echo=True)   # watchdog off while typing by hand
    print("Type F, B, L, R, S, H 90, or M 1 / M 0 for mic lines. Empty line quits.")
    while True:
        text = input("> ").strip()
        if not text:
            break
        robot.send(text.upper())
    robot.close()
