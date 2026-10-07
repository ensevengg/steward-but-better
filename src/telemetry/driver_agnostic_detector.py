"""Identity-neutral candidate detection; anomalies are not offences."""

from __future__ import annotations
import math


class DriverAgnosticDetector:
    def __init__(self):
        self.previous = {}
        self.last_trigger = {}

    def observe(self, driver: str, sample: dict) -> dict | None:
        t, speed, lateral = sample.get("session_time_s"), sample.get("speed_kph"), sample.get("lateral_g")
        if t is None or speed is None or not math.isfinite(t) or not math.isfinite(speed):
            return None
        old = self.previous.get(driver)
        if old and t <= old[0]:
            return None
        self.previous[driver] = (t, speed)
        if not old or t - old[0] > 1 or lateral is None or not math.isfinite(lateral):
            return None
        drop = old[1] - speed
        if lateral >= 5 and drop >= 50 and t - self.last_trigger.get(driver, -100) >= 5:
            self.last_trigger[driver] = t
            return {
                "driver": driver,
                "session_time_s": t,
                "speed_drop_kph": drop,
                "reason": "Speed discontinuity with high estimated cornering load; responsibility unknown",
            }
        return None
