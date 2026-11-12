"""
Live module 2: what the fly sees.

Turns any camera frame into the fly's view, in the exact format the brain's
FeatureRoute (fly_pipeline.py) already expects: a (2, 16, 64) ON/OFF contrast map.

Why it works with ANY camera:
  * Size and shape: the whole picture is squeezed into 16 x 64. A fly's eyes see a
    very wide, very low-resolution panorama, so a wide strip is the right shape,
    and every camera ends up looking the same to the brain.
  * Colour: grayscale. The fly's motion/escape pathway (R1-R6) is colour-blind.
  * Frame rate: the fly cares about CHANGE per second. A 15 fps camera sees twice
    the change between frames that a 30 fps camera does, so the change is scaled
    by the real time between frames. Every camera gives the same answer.

ON  channel = parts that got brighter.
OFF channel = parts that got darker.
A small noise floor is subtracted so camera grain does not look like motion.

Test it on its own (wave your hand at the camera):
    uv run python live/fly_eye.py --camera 0
"""

from __future__ import annotations

import cv2
import numpy as np


class FlyEye:
    def __init__(self, height: int = 16, width: int = 64, noise_floor: float = 0.03, reference_fps: float = 30.0):
        self.height = height
        self.width = width
        self.noise_floor = noise_floor
        self.reference_dt = 1.0 / reference_fps
        self.previous = None
        self.previous_time = None

    def look(self, frame_bgr: np.ndarray, frame_time: float):
        """Returns (view, contrast).
        view:     (16, 64) grayscale, 0..1
        contrast: (2, 16, 64), channel 0 = ON, channel 1 = OFF, 0..1
        """
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        # INTER_AREA averages each region, like one ommatidium collecting light.
        view = cv2.resize(gray, (self.width, self.height), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0

        if self.previous is None:
            contrast = np.zeros((2, self.height, self.width), np.float32)
        else:
            seconds = max(frame_time - self.previous_time, 1e-3)
            change = (view - self.previous) * (self.reference_dt / seconds)
            on = np.clip(change - self.noise_floor, 0.0, 1.0)
            off = np.clip(-change - self.noise_floor, 0.0, 1.0)
            contrast = np.stack([on, off]).astype(np.float32)

        self.previous = view
        self.previous_time = frame_time
        return view, contrast


def picture(view: np.ndarray, contrast: np.ndarray, scale: int = 8) -> np.ndarray:
    """Make an image for the screen: fly view on top, ON (green) / OFF (red) below."""
    gray = cv2.cvtColor((view * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    change = np.zeros_like(gray)
    change[..., 1] = np.clip(contrast[0] * 4 * 255, 0, 255).astype(np.uint8)  # ON  -> green
    change[..., 2] = np.clip(contrast[1] * 4 * 255, 0, 255).astype(np.uint8)  # OFF -> red
    both = np.vstack([gray, change])
    return cv2.resize(both, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)


if __name__ == "__main__":
    import argparse

    from camera import Camera

    parser = argparse.ArgumentParser(description="Show what the fly sees.")
    parser.add_argument("--camera", default="auto")
    args = parser.parse_args()

    cam = Camera(args.camera)
    eye = FlyEye()
    last = 0.0
    print("Wave at the camera. Press q to quit.")
    while True:
        frame, taken = cam.read()
        if taken == last:
            cv2.waitKey(5)
            continue
        last = taken
        view, contrast = eye.look(frame, taken)
        half = eye.width // 2
        motion_left = contrast[:, :, :half].mean()
        motion_right = contrast[:, :, half:].mean()
        img = picture(view, contrast)
        cv2.putText(img, f"motion L {motion_left:.3f}  R {motion_right:.3f}", (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.imshow("camera", frame)
        cv2.imshow("what the fly sees", img)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break
    cam.close()
    cv2.destroyAllWindows()
