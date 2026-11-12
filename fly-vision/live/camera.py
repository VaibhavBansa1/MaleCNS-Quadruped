"""
Live module 1: the camera.

Opens any camera and always hands you the NEWEST frame. A background thread
keeps reading, so a slow brain step never makes the picture lag behind.

A camera source can be:
    "auto"               the first camera that works
    0, 1, 2 ...          a webcam or a phone camera that shows up as a webcam
                         (laptop camera is usually 0, a USB webcam 1)
    "http://..."         a phone camera app that streams over WiFi

Test it on its own:
    uv run python live/camera.py --list          # which cameras exist?
    uv run python live/camera.py --camera 1      # show camera 1, press q to quit
"""

from __future__ import annotations

import os
import threading
import time

import cv2

# DirectShow opens webcams much faster on Windows than the default backend.
BACKEND = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY


def parse_source(text):
    """'1' -> 1 (a camera number). Anything else (a URL) stays as text."""
    text = str(text)
    return int(text) if text.isdigit() else text


def list_cameras(max_index: int = 6) -> list[tuple[int, int, int]]:
    """Try camera numbers 0..max_index-1. Returns (number, width, height) for each that works."""
    found = []
    for index in range(max_index):
        cap = cv2.VideoCapture(index, BACKEND)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok:
                found.append((index, frame.shape[1], frame.shape[0]))
        cap.release()
    return found


class Camera:
    """Reads frames in the background. Call read() to get the newest one."""

    def __init__(self, source="auto"):
        if str(source) == "auto":
            found = list_cameras()
            if not found:
                raise IOError("No camera found. Plug one in, or pass a stream URL with --camera.")
            source = found[0][0]
            print(f"camera: using camera {source}")
        source = parse_source(source)
        if isinstance(source, int):
            self.cap = cv2.VideoCapture(source, BACKEND)
        else:
            self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            raise IOError(f"Could not open camera {source!r}. Try --list to see which numbers work.")

        self.frame = None
        self.frame_time = 0.0
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._keep_reading, daemon=True)
        self.thread.start()

        # Wait up to 5 seconds for the first picture.
        start = time.time()
        while self.frame is None and time.time() - start < 5.0:
            time.sleep(0.05)
        if self.frame is None:
            self.close()
            raise IOError(f"Camera {source!r} opened but sent no picture.")

    def _keep_reading(self):
        while self.running:
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.frame = frame
                    self.frame_time = time.time()
            else:
                time.sleep(0.01)

    def read(self):
        """Returns (frame, time_it_was_taken). The frame is a BGR image (OpenCV's colour order)."""
        with self.lock:
            return self.frame.copy(), self.frame_time

    def close(self):
        self.running = False
        self.thread.join(timeout=1.0)
        self.cap.release()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test the camera on its own.")
    parser.add_argument("--camera", default="auto", help="auto, a camera number, or a stream URL")
    parser.add_argument("--list", action="store_true", help="list working camera numbers and exit")
    args = parser.parse_args()

    if args.list:
        cameras = list_cameras()
        if not cameras:
            print("No cameras found.")
        for index, width, height in cameras:
            print(f"camera {index}: {width}x{height}")
        raise SystemExit

    cam = Camera(args.camera)
    print("Showing camera. Press q in the window to quit.")
    last_time, fps = 0.0, 0.0
    while True:
        frame, taken = cam.read()
        if taken != last_time:
            if last_time:
                fps = 0.9 * fps + 0.1 / max(taken - last_time, 1e-3)
            last_time = taken
        h, w = frame.shape[:2]
        cv2.putText(frame, f"{w}x{h}  {fps:.0f} fps", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.imshow("camera", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cam.close()
    cv2.destroyAllWindows()
