"""
Live module 6: brain activity -> one robot command.

Reads the behaviour groups the brain reports and picks ONE command letter,
the same letters the ESP32 gait firmware understands:
    B = back away (escape fired)     L / R = turn     F = walk forward     S = stop

Every rate is compared with the RESTING rate (measured from the still live scene during the first seconds),
because the network always fires a little on its own. "3x resting" means
something; a raw number does not.

Rules, checked in order:
    1. escape (DNp01) above escape_ratio x rest        -> B
    2. steer (DNa02) left vs right differ by steer_gap -> L or R
       (left DNa02 firing turns a fly to the left)
    3. forward (DNg100) above forward_ratio x rest     -> F
    4. otherwise                                       -> S

A command is held for at least hold_seconds so the robot does not twitch.

Test it on its own (fake numbers):
    uv run python live/decide.py
"""

from __future__ import annotations

import time


class Decider:
    def __init__(self, escape_ratio: float = 4.0, steer_gap: float = 0.5, forward_ratio: float = 1.5,
                 hold_seconds: float = 0.4, confirm_seconds: float = 0.3):
        self.escape_ratio = escape_ratio
        self.steer_gap = steer_gap
        self.forward_ratio = forward_ratio
        self.hold_seconds = hold_seconds
        self.rest = None
        self.command = "S"
        self.since = 0.0
        # A new command must be wanted continuously for confirm_seconds before it is used.
        # The behaviour groups are tiny (escape and steer are ONE neuron per side), so a
        # single random spike must not move the robot.
        self.confirm_seconds = confirm_seconds
        self.candidate = "S"
        self.candidate_since = 0.0

    def calibrate(self, resting_rates: dict) -> None:
        """Remember the resting rates. A small floor stops division by zero."""
        self.rest = {name: max(value, 0.05) for name, value in resting_rates.items()}

    def ratio(self, rates: dict, name: str) -> float:
        """How many times above resting, both sides added together."""
        now = rates.get(f"{name}_L", 0.0) + rates.get(f"{name}_R", 0.0)
        base = self.rest.get(f"{name}_L", 0.05) + self.rest.get(f"{name}_R", 0.05)
        return now / base

    def steer(self, rates: dict) -> float:
        """How much the brain wants to turn: -1 = left ... +1 = right, 0 = straight.
        Left steering neurons (DNa02 left) firing above their rest -> negative."""
        if self.rest is None:
            return 0.0
        left = rates.get("steer_L", 0.0) / self.rest.get("steer_L", 0.05)
        right = rates.get("steer_R", 0.0) / self.rest.get("steer_R", 0.05)
        return max(-1.0, min(1.0, (right - left) / (left + right + 1.0)))

    def escaping(self, rates: dict) -> bool:
        return self.rest is not None and self.ratio(rates, "escape") > self.escape_ratio

    def choose(self, rates: dict) -> str:
        if self.rest is None:
            return "S"
        if self.ratio(rates, "escape") > self.escape_ratio:
            return "B"
        left = rates.get("steer_L", 0.0) / self.rest.get("steer_L", 0.05)
        right = rates.get("steer_R", 0.0) / self.rest.get("steer_R", 0.05)
        if left - right > self.steer_gap:
            return "L"
        if right - left > self.steer_gap:
            return "R"
        if self.ratio(rates, "forward") > self.forward_ratio:
            return "F"
        return "S"

    def decide(self, rates: dict, now: float | None = None) -> str:
        """choose(), but only after it has been wanted for confirm_seconds,
        and keep each command for at least hold_seconds."""
        now = time.time() if now is None else now
        wanted = self.choose(rates)
        if wanted != self.candidate:
            self.candidate = wanted
            self.candidate_since = now
        confirmed = now - self.candidate_since >= self.confirm_seconds
        if confirmed and wanted != self.command and now - self.since >= self.hold_seconds:
            self.command = wanted
            self.since = now
        return self.command


if __name__ == "__main__":
    decider = Decider(hold_seconds=0.0, confirm_seconds=0.0)
    resting = {"escape_L": 0.07, "escape_R": 0.07, "steer_L": 0.13, "steer_R": 0.13,
               "forward_L": 0.05, "forward_R": 0.05}
    decider.calibrate(resting)
    tests = {
        "resting": resting,
        "escape firing": {**resting, "escape_L": 3.0, "escape_R": 2.0},
        "left steer": {**resting, "steer_L": 0.4},
        "right steer": {**resting, "steer_R": 0.4},
        "forward": {**resting, "forward_L": 0.2, "forward_R": 0.2},
    }
    for name, rates in tests.items():
        print(f"{name:15s} -> {decider.decide(rates)}")
