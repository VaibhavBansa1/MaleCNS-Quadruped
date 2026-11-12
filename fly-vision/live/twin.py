"""
Live module 8: the virtual twin (a simulated fly body on screen).

A small top-down arena with a fly in it. It receives the SAME command letters
the robot gets (F, B, L, R, S), so visitors see the brain's decision act on a
simulated body and on the real robot side by side.

The arena has walls. If the twin walks into one it stops there; press 0 to put
it back in the middle (like picking the real robot up and placing it back).

The speeds below are guesses. To match your robot: send F for 10 seconds,
measure how far it walked, divide by 10, and put that in WALK_CM_PER_S.
Do the same with L for TURN_DEG_PER_S.

Test it on its own (drive with the keyboard):
    uv run python live/twin.py
    w forward   s back   a left   d right   x stop   0 reset   q quit
"""

from __future__ import annotations

import math

import cv2
import numpy as np

ARENA_CM = (45.0, 30.0)       # width, height of the virtual table (small, so slow walking is visible)
WALK_CM_PER_S = 0.67          # measured: about 1 cm every 1.5 s
TURN_DEG_PER_S = 4.5           # estimated on the table: about 4-5 degrees per second
BODY_CM = 3.0                 # drawn size of the fly


class VirtualFly:
    def __init__(self):
        self.reset()

    def reset(self) -> None:
        """Back to the middle of the arena, facing up, trail cleared."""
        self.x = ARENA_CM[0] / 2
        self.y = ARENA_CM[1] / 2
        self.heading = 0.0            # degrees, 0 = up, 90 = right
        self.trail = [(self.x, self.y)]
        self.hit_wall = False

    def update(self, command: str, seconds: float) -> None:
        """Move for `seconds` according to one command letter."""
        seconds = min(seconds, 0.5)   # never jump far if the program stalls
        step = 0.0
        if command == "F":
            step = WALK_CM_PER_S * seconds
        elif command == "B":
            step = -WALK_CM_PER_S * seconds
        elif command == "L":
            self.heading -= TURN_DEG_PER_S * seconds
        elif command == "R":
            self.heading += TURN_DEG_PER_S * seconds

        if step:
            angle = math.radians(self.heading)
            new_x = self.x + math.sin(angle) * step
            new_y = self.y - math.cos(angle) * step
            margin = BODY_CM / 2
            inside_x = min(max(new_x, margin), ARENA_CM[0] - margin)
            inside_y = min(max(new_y, margin), ARENA_CM[1] - margin)
            self.hit_wall = (inside_x != new_x) or (inside_y != new_y)
            self.x, self.y = inside_x, inside_y
            if math.dist(self.trail[-1], (self.x, self.y)) > 0.5:
                self.trail.append((self.x, self.y))
                self.trail = self.trail[-600:]

    def draw(self, width: int = 480, height: int = 320, command: str = "S") -> np.ndarray:
        """Picture of the arena with the fly, its trail and the current command."""
        img = np.zeros((height, width, 3), np.uint8)
        scale = min((width - 20) / ARENA_CM[0], (height - 50) / ARENA_CM[1])
        ox = (width - ARENA_CM[0] * scale) / 2
        oy = 35

        def px(x, y):
            return int(ox + x * scale), int(oy + y * scale)

        cv2.rectangle(img, px(0, 0), px(*ARENA_CM), (200, 200, 200), 1)
        if len(self.trail) > 1:
            points = np.array([px(x, y) for x, y in self.trail], np.int32)
            cv2.polylines(img, [points], False, (110, 110, 110), 1)

        # The fly: a triangle pointing where it faces.
        a = math.radians(self.heading)
        size = BODY_CM * scale / 2
        nose = (self.x + math.sin(a) * BODY_CM / 2, self.y - math.cos(a) * BODY_CM / 2)
        left = (self.x + math.sin(a - 2.5) * BODY_CM / 2, self.y - math.cos(a - 2.5) * BODY_CM / 2)
        right = (self.x + math.sin(a + 2.5) * BODY_CM / 2, self.y - math.cos(a + 2.5) * BODY_CM / 2)
        body = np.array([px(*nose), px(*left), px(*right)], np.int32)
        cv2.fillPoly(img, [body], (255, 255, 255))
        cv2.circle(img, px(*nose), max(2, int(size / 4)), (0, 0, 0), -1)

        cv2.putText(img, f"virtual fly   command: {command}", (10, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (255, 255, 255), 1)
        if self.hit_wall:
            cv2.putText(img, "wall! press 0 to reset", (10, height - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (0, 0, 255), 1)
        return img


if __name__ == "__main__":
    import time

    keys = {ord("w"): "F", ord("s"): "B", ord("a"): "L", ord("d"): "R", ord("x"): "S"}
    fly = VirtualFly()
    command = "S"
    last = time.time()
    print("w a s d x to drive, 0 to reset, q to quit")
    while True:
        now = time.time()
        fly.update(command, now - last)
        last = now
        cv2.imshow("virtual fly", fly.draw(command=command))
        key = cv2.waitKey(30) & 0xFF
        if key == ord("q"):
            break
        if key == ord("0"):
            fly.reset()
        if key in keys:
            command = keys[key]
    cv2.destroyAllWindows()
