"""Incrementally consume FastF1 live recorder messages; never load a finished session.

Run the official authenticated recorder in one process and this tailer in another.
The raw recording remains the recovery log; judging runs separately in the backend.
"""

from __future__ import annotations
import argparse
import ast
import base64
from collections import deque
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
import uuid
import zlib
import pandas as pd
import requests
from .driver_agnostic_detector import DriverAgnosticDetector
from .live_simulator import bounded, integer, send_packet
from .telemetry_utils import compute_g_forces
from src.brain.contracts import TelemetryPacket

MAX_RECORD = 8 * 1024 * 1024
logger = logging.getLogger(__name__)


def decode_payload(payload):
    if isinstance(payload, dict):
        return payload
    if not isinstance(payload, str):
        raise ValueError("Expected a feed object or encoded string")
    if payload.lstrip().startswith(("{", "[")):
        return json.loads(payload)
    raw = base64.b64decode(payload.strip('"'), validate=True)
    decoder = zlib.decompressobj(-zlib.MAX_WBITS)
    decoded = decoder.decompress(raw, MAX_RECORD + 1)
    if len(decoded) > MAX_RECORD or not decoder.eof:
        raise ValueError("Compressed feed record exceeds limit or is incomplete")
    return json.loads(decoded)


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Feed timestamps require a timezone")
    return parsed.timestamp()


class LiveField:
    def __init__(self, session_id, start_utc, name, mode="LIVE"):
        self.session_id, self.name, self.mode = session_id, name, mode
        self.origin = timestamp(start_utc)
        self.event_date = datetime.fromtimestamp(self.origin, timezone.utc).date().isoformat()
        self.roster, self.latest, self.timing, self.positions, self.history = {}, {}, {}, {}, {}
        self.messages, self.pending = {}, []
        self.track_status = None
        self.clock = 0.0
        self.sequence = self.processed = 0
        self.detector = DriverAgnosticDetector()

    def consume(self, record):
        if not isinstance(record, (list, tuple)) or len(record) != 3:
            raise ValueError("Expected [topic, payload, timestamp]")
        topic, encoded, date = record
        if topic not in {
            "DriverList",
            "TimingData",
            "TrackStatus",
            "RaceControlMessages",
            "CarData.z",
            "Position.z",
        }:
            return False
        payload = decode_payload(encoded)
        if date:
            self.clock = max(self.clock, timestamp(date) - self.origin)
        if topic == "DriverList":
            for number, item in payload.items():
                if not isinstance(item, dict):
                    continue
                previous = self.roster.get(number, {"driver_code": str(number), "driver_number": str(number)})
                color = item.get("TeamColour")
                self.roster[number] = {
                    **previous,
                    **({"driver_code": item["Tla"]} if item.get("Tla") else {}),
                    **({"team": item["TeamName"]} if item.get("TeamName") else {}),
                    **(
                        {"team_color": color}
                        if isinstance(color, str)
                        and len(color) == 6
                        and all(c in "0123456789abcdefABCDEF" for c in color)
                        else {}
                    ),
                }
        elif topic == "TimingData":
            for number, item in payload.get("Lines", {}).items():
                self.timing[number] = {**self.timing.get(number, {}), **item}
        elif topic == "TrackStatus":
            self.track_status = payload.get("Message", self.track_status)
        elif topic == "RaceControlMessages":
            messages = payload.get("Messages", {})
            for key, item in enumerate(messages) if isinstance(messages, list) else messages.items():
                if "Message" not in item:
                    continue
                identity = f"{item.get('Utc', date)}:{key}"
                self.messages[identity] = {
                    "id": identity,
                    "message": item["Message"],
                    "time": item.get("Utc", date),
                    "category": item.get("Category"),
                }
            self.messages = dict(list(self.messages.items())[-100:])
        elif topic == "Position.z":
            for entry in payload.get("Position", []):
                t = timestamp(entry["Timestamp"]) - self.origin
                for number, point in entry.get("Entries", {}).items():
                    if "X" in point and "Y" in point:
                        self.positions.setdefault(number, deque(maxlen=30)).append(
                            (t, point["X"] / 10, point["Y"] / 10)
                        )
        elif topic == "CarData.z":
            for entry in sorted(payload.get("Entries", []), key=lambda item: item["Utc"]):
                t = timestamp(entry["Utc"]) - self.origin
                if t < 0:
                    continue
                self.clock = max(self.clock, t)
                for number, car in entry.get("Cars", {}).items():
                    if t <= self.latest.get(number, {}).get("sample_time_s", -1):
                        continue
                    channels = car.get("Channels", {})
                    self.roster.setdefault(number, {"driver_code": str(number), "driver_number": str(number)})
                    code = self.roster[number]["driver_code"]
                    speed = bounded(channels.get("2"), 0, 450)
                    position = next(
                        (p for p in reversed(self.positions.get(number, [])) if 0 <= t - p[0] <= 0.3), None
                    )
                    rows = self.history.setdefault(number, deque(maxlen=100))
                    rows.append(
                        {
                            "TimeSeconds": t,
                            "Speed": speed,
                            "X": position[1] if position else None,
                            "Y": position[2] if position else None,
                        }
                    )
                    physical = compute_g_forces(pd.DataFrame(list(rows)[-8:])).iloc[-1]
                    brake = bool(channels["5"]) if channels.get("5") in (0, 100, False, True) else None
                    item = {
                        "current_speed": speed,
                        "sample_time_s": t,
                        "throttle": bounded(channels.get("4"), 0, 100),
                        "brake_applied": brake,
                        "gear": integer(bounded(channels.get("3"), 0, 8)),
                        "rpm": bounded(channels.get("0"), 0, 25000),
                        "drs": integer(bounded(channels.get("45"), 0, 20)),
                        "lateral_g": bounded(physical.lateral_g, 0, 12),
                        "longitudinal_g": bounded(physical.longitudinal_g, -12, 12),
                    }
                    self.latest[number] = item
                    self.processed += 1
                    sample = {
                        "driver": code,
                        "session_time_s": t,
                        "speed_kph": speed,
                        "lateral_g": item["lateral_g"],
                        "longitudinal_g": item["longitudinal_g"],
                        "brake_applied": brake,
                    }
                    candidate = self.detector.observe(code, sample)
                    if candidate:
                        self.pending.append(
                            {
                                "id": f"{self.session_id}:{number}:{t:.6f}",
                                "session_id": self.session_id,
                                "event_date": self.event_date,
                                "title": f"Telemetry anomaly · {code}",
                                "driver": code,
                                "lap": integer(self.timing.get(number, {}).get("NumberOfLaps")) or 0,
                                "incident_type": "telemetry_anomaly",
                                "samples": [sample],
                                "observations": [],
                                "limitations": [
                                    candidate["reason"],
                                    "Telemetry does not establish responsibility.",
                                ],
                            }
                        )
        return True

    def snapshot(self):
        drivers = []
        for number, identity in self.roster.items():
            data = dict(self.latest.get(number, {}))
            timing = self.timing.get(number, {})
            fresh = bool(data) and self.clock - data["sample_time_s"] <= 1
            if not fresh:
                data = {key: value if key == "sample_time_s" else None for key, value in data.items()}
            gap = timing.get("GapToLeader")
            if isinstance(gap, dict):
                gap = gap.get("Value")
            drivers.append(
                {
                    **identity,
                    **data,
                    "position_rank": integer(bounded(timing.get("Position"), 1, 40)),
                    "lap_number": integer(bounded(timing.get("NumberOfLaps"), 0, 200)),
                    "gap_text": str(gap) if gap is not None else None,
                    "timing_source": "Live timing (reported lap)",
                    "status": "OUT"
                    if timing.get("Retired")
                    else "PIT"
                    if timing.get("InPit")
                    else "ACTIVE"
                    if fresh
                    else "UNKNOWN",
                }
            )
        packet = TelemetryPacket(
            session_id=self.session_id,
            sequence=self.sequence,
            event_date=self.event_date,
            session_name=self.name,
            session_time_s=self.clock,
            status=self.mode,
            source="FastF1 recorder / incremental live adapter",
            native_samples_processed=self.processed,
            all_drivers=drivers,
            cases=self.pending[:40],
            race_control=list(self.messages.values())[-100:],
            track_status=self.track_status,
        )
        return packet

    def acknowledged(self, packet):
        del self.pending[: len(packet.cases)]
        self.sequence += 1


def records(path, follow=False):
    """Partial lines wait for completion; existing recording is processed in order."""
    with Path(path).open(encoding="utf-8") as stream:
        pending = ""
        while True:
            part = stream.readline(MAX_RECORD + 1)
            if part:
                pending += part
                if len(pending) > MAX_RECORD:
                    raise ValueError("Feed record too large")
                if pending.endswith("\n"):
                    yield ast.literal_eval(pending)
                    pending = ""
            elif follow:
                time.sleep(0.05)
            else:
                if pending.strip():
                    yield ast.literal_eval(pending)
                return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--start-utc", required=True, help="Session clock origin, ISO8601 with timezone")
    parser.add_argument("--name", required=True)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--follow", action="store_true", help="Follow a growing live recorder file")
    parser.add_argument("--endpoint", default="http://127.0.0.1:3000/api/telemetry")
    args = parser.parse_args()
    state = LiveField(
        args.session_id or str(uuid.uuid4()), args.start_utc, args.name, "LIVE" if args.follow else "REPLAY"
    )
    last_sent = -float("inf")
    with requests.Session() as client:
        for record in records(args.recording, args.follow):
            if state.consume(record) and (time.monotonic() - last_sent >= 0.25 or len(state.pending) >= 40):
                packet = state.snapshot()
                send_packet(client, args.endpoint, packet.model_dump(mode="json"))
                state.acknowledged(packet)
                last_sent = time.monotonic()
        if not args.follow:
            state.mode = "FINISHED"
            while True:
                packet = state.snapshot()
                # Drain pending cases before making the session immutable.
                if len(state.pending) > 40:
                    packet.status = "REPLAY"
                send_packet(client, args.endpoint, packet.model_dump(mode="json"))
                state.acknowledged(packet)
                if not state.pending:
                    break


if __name__ == "__main__":
    main()
