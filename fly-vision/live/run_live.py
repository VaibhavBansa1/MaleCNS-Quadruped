"""
The whole loop, live, in one window:

    camera -> fly_eye (what the fly sees)  --\
    camera -> nose    (food -> smell)      ----> brain_link (flybrain) -> decide -> robot + virtual fly
    mic    -> ear     (sound bands)        --/

Every part has options and falls back instead of crashing:
    camera  --camera auto | 0 | 1 | http://...    (auto = first that works)
    nose    --nose color | yolo                    (yolo falls back to color)
    ears    --mic auto | esp | laptop | none       (auto: robot mics, then laptop, then none)
    robot   --port COM5 or /dev/ttyUSB0            (if it fails, runs without the robot)

Run (from the fly-vision folder):
    uv run python live/run_live.py --mic laptop                          # finds the robot by itself
    uv run python live/run_live.py --mic laptop --port COM5              # or name the port
    uv run python live/run_live.py --mic laptop --port none              # screen only
    uv run python live/run_live.py --list-cameras

Keys (also shown at the bottom of the window, h hides them):
    click the food   teach the colour nose what food looks like
    space            pause / resume the robot (brain keeps running)
    m                switch brain control <-> manual control
    w a s d x        drive by hand in manual mode (forward, left, back, right, stop)
    0                reset the virtual fly to the middle of its arena
    r                re-measure room noise + live baseline (keep the scene still 8 s)
    h                show / hide the key help
    q                quit
"""

from __future__ import annotations

import argparse
import time

import cv2
import numpy as np

from brain_link import FlyBrainLink
from camera import Camera, list_cameras
from decide import Decider
from ear import make_mic
from fly_eye import FlyEye, picture
from nose import make_nose
from robot_link import make_robot
from twin import VirtualFly

MAX_STEPS_PER_LOOP = 5     # if the loop gets slow, don't try to catch up more than this
CALIBRATE_SECONDS = 8.0    # live baseline: the real scene, kept still (longer = steadier)
MANUAL_KEYS = {ord("w"): "F", ord("s"): "B", ord("a"): "L", ord("d"): "R", ord("x"): "S"}
HELP = [
    "click food: teach nose    space: pause robot    m: brain / manual    w a s d x: drive (manual)",
    "0: reset virtual fly      r: recalibrate        h: hide help         q: quit",
]
WHITE = (255, 255, 255)
GRAY = (160, 160, 160)


def put(img, text, x, y, scale=0.5, color=WHITE, thickness=1):
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness)


def bar(img, x, y, label, value, top=1.0, width=180):
    """One labelled bar: label, outline, filled part, number."""
    filled = int(width * min(max(value / top, 0.0), 1.0))
    cv2.rectangle(img, (x + 130, y - 11), (x + 130 + width, y + 2), (90, 90, 90), 1)
    cv2.rectangle(img, (x + 130, y - 11), (x + 130 + filled, y + 2), WHITE, -1)
    put(img, label, x, y)
    put(img, f"{value:.2f}", x + 140 + width, y)


def fit(img, width, height):
    """Shrink a picture into width x height without stretching it (black borders).
    Returns the picture plus the scale and offsets, to place boxes on it."""
    h, w = img.shape[:2]
    scale = min(width / w, height / h)
    small = cv2.resize(img, (int(w * scale), int(h * scale)))
    canvas = np.zeros((height, width, 3), np.uint8)
    ox, oy = (width - small.shape[1]) // 2, (height - small.shape[0]) // 2
    canvas[oy:oy + small.shape[0], ox:ox + small.shape[1]] = small
    return canvas, scale, ox, oy


def brain_panel(rates, decider, smell, sound, command, status):
    panel = np.zeros((280, 480, 3), np.uint8)
    bar(panel, 10, 22, "smell L", smell[0])
    bar(panel, 10, 42, "smell R", smell[1])
    bar(panel, 10, 62, "sound L", max(sound[0], sound[1]))
    bar(panel, 10, 82, "sound R", max(sound[2], sound[3]))
    bar(panel, 10, 112, "escape x rest", decider.ratio(rates, "escape"), top=10)
    bar(panel, 10, 132, "forward x rest", decider.ratio(rates, "forward"), top=5)
    bar(panel, 10, 152, "backward x rest", decider.ratio(rates, "backward"), top=5)
    bar(panel, 10, 172, "steer L (Hz)", rates.get("steer_L", 0.0), top=2)
    bar(panel, 10, 192, "steer R (Hz)", rates.get("steer_R", 0.0), top=2)
    put(panel, f"COMMAND: {command}", 10, 232, scale=0.9, color=(0, 255, 255), thickness=2)
    put(panel, status, 10, 266, scale=0.45, color=GRAY)
    return panel


def average_rates(samples):
    """Mean firing rate of every behaviour group over the calibration samples."""
    return {name: float(np.mean([s[name] for s in samples])) for name in samples[0]}


def measure_rest(link, decider):
    print("Measuring resting baseline (2 s, no input)...")
    decider.calibrate(link.rest(2.0))


def main():
    parser = argparse.ArgumentParser(description="Live fly brain: camera + mic in, robot commands out.")
    parser.add_argument("--camera", default="auto", help="auto, a camera number, or a stream URL")
    parser.add_argument("--list-cameras", action="store_true")
    parser.add_argument("--nose", default="color", choices=["color", "yolo"])
    parser.add_argument("--target", default="apple", help="object name for --nose yolo")
    parser.add_argument("--mic", default="auto", choices=["auto", "esp", "laptop", "none"])
    parser.add_argument("--mic-device", default=None, help="laptop microphone number (python live/ear.py --list)")
    parser.add_argument("--port", default="auto", help="robot serial port: auto (default), COM5, /dev/ttyUSB0, or none")
    parser.add_argument("--device", default="auto", help="cpu, cuda or auto")
    parser.add_argument("--food-as-target", action="store_true",
                        help="also show the food to LC10a (steering route), not only the nose")
    args = parser.parse_args()

    if args.list_cameras:
        for index, w, h in list_cameras():
            print(f"camera {index}: {w}x{h}")
        return

    # ---- start every part, falling back where possible ----
    try:
        cam = Camera(args.camera)
    except IOError as error:
        print(f"camera: {error}")
        print("working cameras:", list_cameras() or "none")
        return
    eye = FlyEye()
    nose = make_nose(args.nose, args.target)
    robot = make_robot(None if args.port == "none" else args.port)   # before the mic: the robot mics need it
    mic_device = int(args.mic_device) if args.mic_device is not None else None
    mic = make_mic(args.mic, robot, mic_device)
    link = FlyBrainLink(device=args.device, food_as_target=args.food_as_target)
    decider = Decider()
    twin = VirtualFly()
    robot_name = "robot connected" if hasattr(robot, "serial") else "no robot"

    print("Stay quiet for 1 second (microphone baseline)...")
    mic.calibrate()
    measure_rest(link, decider)

    latest = {"frame": None, "scale": 1.0, "ox": 0, "oy": 0}

    def on_click(event, x, y, flags, param):
        # The camera picture sits in the top-left 480 x 360 of the window.
        if event != cv2.EVENT_LBUTTONDOWN or latest["frame"] is None or x >= 480 or y >= 360:
            return
        fx = int((x - latest["ox"]) / latest["scale"])
        fy = int((y - latest["oy"]) / latest["scale"])
        h, w = latest["frame"].shape[:2]
        if 0 <= fx < w and 0 <= fy < h:
            nose.pick(latest["frame"], fx, fy)

    cv2.namedWindow("fly brain")
    cv2.setMouseCallback("fly brain", on_click)

    mode = "brain"
    manual_command = "S"
    paused = False
    # Live baseline: the first seconds measure the brain WITH the real camera and mic,
    # so normal camera noise, screen flicker and room sound count as "rest".
    calibrate_until = time.time() + CALIBRATE_SECONDS
    calibration = []
    show_help = True
    last_frame_time = 0.0
    last_loop = time.time()

    try:
        while True:
            frame, taken = cam.read()
            if taken == last_frame_time:          # no new picture yet
                cv2.waitKey(2)
                continue
            last_frame_time = taken
            latest["frame"] = frame

            # 1. senses
            view, contrast = eye.look(frame, taken)
            smell_l, smell_r, mask, box = nose.smell(frame)
            sound = mic.levels()                  # (song_L, fast_L, song_R, fast_R)

            # 2. brain: run as many 20 ms steps as real time has passed
            now = time.time()
            elapsed = now - last_loop
            last_loop = now
            steps = int(np.clip(round(elapsed / link.dt), 1, MAX_STEPS_PER_LOOP))
            rates = link.step(contrast, (smell_l, smell_r), sound, steps)

            # 3. decision -> robot and virtual fly (both get exactly the same command)
            calibrating = now < calibrate_until
            if calibrating:
                calibration.append(rates)
            elif calibration:
                decider.calibrate(average_rates(calibration))
                rest = decider.rest
                print("live baseline: " + "  ".join(f"{k} {rest[k]:.2f}" for k in sorted(rest)
                                                   if k.split('_')[0] in ("escape", "steer", "forward")))
                calibration = []

            brain_command = decider.decide(rates)
            command = manual_command if mode == "manual" else brain_command
            sent = "S" if (paused or calibrating) else command
            robot.command(sent)
            twin.update(sent, elapsed)

            # face and head on the robot: manual mode looks where you steer,
            # brain mode looks where the brain wants to turn
            if mode == "manual":
                steer = {"L": -1.0, "R": 1.0}.get(sent, 0.0)
                robot.status(False, steer, False)
            else:
                robot.status(True, 0.0 if paused else decider.steer(rates), decider.escaping(rates))

            # 4. window: camera + fly view on the left, virtual fly + brain on the right
            camera_img, scale, ox, oy = fit(frame, 480, 360)
            latest.update(scale=scale, ox=ox, oy=oy)
            if box:
                x, y, w, h = box
                p1 = (int(ox + x * scale), int(oy + y * scale))
                p2 = (int(ox + (x + w) * scale), int(oy + (y + h) * scale))
                cv2.rectangle(camera_img, p1, p2, (0, 255, 0), 2)
            if nose.hue is None:
                put(camera_img, "click the food", 10, 30, scale=0.8, color=(0, 0, 255), thickness=2)
            if calibrating:
                put(camera_img, "calibrating: keep still", 10, 60, scale=0.8, color=(0, 255, 255), thickness=2)
            fly_view = cv2.resize(picture(view, contrast), (480, 240), interpolation=cv2.INTER_NEAREST)
            left = np.vstack([camera_img, fly_view])

            label = f"{mode} control" + ("  PAUSED" if paused else "")
            if calibrating:
                label = "CALIBRATING - keep the scene still"
            status = f"{label}  |  ear: {mic.name}  |  {robot_name}  |  brain steps: {steps}"
            right = np.vstack([twin.draw(command=sent), brain_panel(rates, decider, (smell_l, smell_r),
                                                                     sound, sent, status)])
            window = np.hstack([left, right])
            if show_help:
                strip = np.zeros((50, window.shape[1], 3), np.uint8)
                put(strip, HELP[0], 10, 20, scale=0.45, color=GRAY)
                put(strip, HELP[1], 10, 42, scale=0.45, color=GRAY)
                window = np.vstack([window, strip])
            cv2.imshow("fly brain", window)

            # 5. keys
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            elif key == ord(" "):
                paused = not paused
                print("robot paused" if paused else "robot resumed")
            elif key == ord("m"):
                mode = "manual" if mode == "brain" else "brain"
                manual_command = "S"
                print(f"{mode} control")
            elif key in MANUAL_KEYS and mode == "manual":
                manual_command = MANUAL_KEYS[key]
            elif key == ord("0"):
                twin.reset()
            elif key == ord("r"):
                robot.command("S")
                print("Measuring room noise (1 s)...")
                mic.calibrate()
                print(f"Measuring live baseline ({CALIBRATE_SECONDS:.0f} s), keep the scene still...")
                calibrate_until = time.time() + CALIBRATE_SECONDS
                calibration = []
            elif key == ord("h"):
                show_help = not show_help
    finally:
        robot.close()
        mic.close()
        cam.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
