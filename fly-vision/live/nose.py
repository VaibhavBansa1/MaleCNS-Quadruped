"""
Live module 3: the nose (camera -> smell).

A real fly finds food by SMELL, not by recognising it. Our robot has no gas
sensor, so the camera stands in for the nose: we find the food in the picture
and turn "how much food is on my left / right" into two smell strengths.
Those go to the fly's own olfactory receptor neurons (see brain_link.py).

Two noses, same output, pick one:
  ColorNose  (default) - click the food once to learn its colour. Fast, works on
             any laptop, very reliable in a demo. Use a brightly coloured object.
  YoloNose   (optional) - a YOLO model finds a named object ("apple", "banana",
             "orange" ...). Needs:  uv pip install ultralytics

Both return (left, right, mask_or_None, box_or_None), left/right in 0..1.

Test it on its own:
    uv run python live/nose.py --camera 0                 # then click the food
    uv run python live/nose.py --camera 0 --nose yolo --target apple
"""

from __future__ import annotations

import cv2
import numpy as np


def split_left_right(mask: np.ndarray) -> tuple[float, float]:
    """Fraction of each half of the picture that is food (0..1)."""
    half = mask.shape[1] // 2
    return float(mask[:, :half].mean()) / 255.0, float(mask[:, half:].mean()) / 255.0


class ColorNose:
    def __init__(self, hue_width: int = 10, min_saturation: int = 80, min_value: int = 60,
                 gain: float = 8.0, smoothing: float = 0.3):
        """
        hue_width:  how far from the clicked colour still counts as food.
        gain:       food covering 1/gain of one half = full smell (8 -> 12.5%).
        smoothing:  0..1, how much each new frame changes the smell (lower = steadier).
        """
        self.hue = None             # not taught yet
        self.hue_width = hue_width
        self.min_saturation = min_saturation
        self.min_value = min_value
        self.gain = gain
        self.smoothing = smoothing
        self.left = 0.0
        self.right = 0.0

    def pick(self, frame_bgr: np.ndarray, x: int, y: int) -> None:
        """Learn the food colour from a small patch around the clicked point."""
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        patch = hsv[max(0, y - 4):y + 5, max(0, x - 4):x + 5].reshape(-1, 3)
        self.hue = int(np.median(patch[:, 0]))
        print(f"food colour learned: hue {self.hue}")

    def smell(self, frame_bgr: np.ndarray):
        if self.hue is None:
            return 0.0, 0.0, None, None

        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        low, high = self.hue - self.hue_width, self.hue + self.hue_width
        # OpenCV hue runs 0..179 and red sits at both ends, so wrap around.
        mask = cv2.inRange(hsv, (max(low, 0), self.min_saturation, self.min_value), (min(high, 179), 255, 255))
        if low < 0:
            mask |= cv2.inRange(hsv, (180 + low, self.min_saturation, self.min_value), (179, 255, 255))
        if high > 179:
            mask |= cv2.inRange(hsv, (0, self.min_saturation, self.min_value), (high - 180, 255, 255))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))  # remove speckles

        left, right = split_left_right(mask)
        self._update(left, right)
        return self.left, self.right, mask, biggest_box(mask)

    def _update(self, left: float, right: float) -> None:
        a = self.smoothing
        self.left += a * (min(1.0, left * self.gain) - self.left)
        self.right += a * (min(1.0, right * self.gain) - self.right)


class YoloNose(ColorNose):
    def __init__(self, target: str = "apple", model: str = "yolov8n.pt", confidence: float = 0.35, **kwargs):
        super().__init__(**kwargs)
        try:
            from ultralytics import YOLO
        except ImportError:
            raise ImportError("YoloNose needs ultralytics:  uv pip install ultralytics")
        self.model = YOLO(model)          # downloads the small model the first time
        self.target = target
        self.confidence = confidence
        self.hue = 0                      # nothing to teach

    def pick(self, frame_bgr, x, y):
        pass                              # YOLO does not need a click

    def smell(self, frame_bgr: np.ndarray):
        result = self.model(frame_bgr, verbose=False)[0]
        mask = np.zeros(frame_bgr.shape[:2], np.uint8)
        best = None
        for box in result.boxes:
            name = result.names[int(box.cls)]
            if name != self.target or float(box.conf) < self.confidence:
                continue
            x1, y1, x2, y2 = (int(v) for v in box.xyxy[0])
            mask[y1:y2, x1:x2] = 255
            best = (x1, y1, x2 - x1, y2 - y1)
        left, right = split_left_right(mask)
        self._update(left, right)
        return self.left, self.right, mask, best


def biggest_box(mask: np.ndarray):
    """(x, y, w, h) around the largest food blob, or None."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    return cv2.boundingRect(max(contours, key=cv2.contourArea))


def make_nose(kind: str = "color", target: str = "apple"):
    """Falls back to the colour nose if YOLO cannot start."""
    if kind == "yolo":
        try:
            nose = YoloNose(target=target)
            print(f"nose: YOLO, looking for '{target}'")
            return nose
        except Exception as error:
            print(f"nose: YOLO not available ({error}), using the colour nose")
    print("nose: colour nose, click the food to teach it")
    return ColorNose()


if __name__ == "__main__":
    import argparse

    from camera import Camera

    parser = argparse.ArgumentParser(description="Turn the camera into a nose.")
    parser.add_argument("--camera", default="auto")
    parser.add_argument("--nose", default="color", choices=["color", "yolo"])
    parser.add_argument("--target", default="apple", help="object name for --nose yolo")
    args = parser.parse_args()

    cam = Camera(args.camera)
    nose = make_nose(args.nose, args.target)
    latest = {"frame": None}

    def on_click(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and latest["frame"] is not None:
            nose.pick(latest["frame"], x, y)

    cv2.namedWindow("nose")
    cv2.setMouseCallback("nose", on_click)
    print("Click the food (colour nose). Press q to quit.")
    while True:
        frame, _ = cam.read()
        latest["frame"] = frame
        left, right, mask, box = nose.smell(frame)
        show = frame.copy()
        if box:
            x, y, w, h = box
            cv2.rectangle(show, (x, y), (x + w, y + h), (0, 255, 0), 2)
        mid = show.shape[1] // 2
        cv2.line(show, (mid, 0), (mid, show.shape[0]), (255, 255, 255), 1)
        cv2.putText(show, f"smell L {left:.2f}  R {right:.2f}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        if nose.hue is None:
            cv2.putText(show, "click the food", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.imshow("nose", show)
        if mask is not None:
            cv2.imshow("food mask", mask)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cam.close()
    cv2.destroyAllWindows()
