"""Replay native FastF1 samples; throttle display independently of detection."""

from __future__ import annotations
import argparse
from collections import deque
import json
from itertools import groupby
from pathlib import Path
import time
import uuid
import pandas as pd
import requests
from .driver_agnostic_detector import DriverAgnosticDetector
from .telemetry_utils import compute_g_forces, merge_position_channels, timedelta_to_seconds


def finite(value):
    return None if value is None or pd.isna(value) else float(value)


def load_session(year, gp, lap, drivers=None, cache_dir="data/fastf1-cache"):
    import fastf1

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(cache_dir)
    session = fastf1.get_session(year, gp, "R")
    session.load(telemetry=True, weather=False, messages=False)
    laps = session.laps[session.laps["LapNumber"] == lap]
    if laps.empty:
        raise ValueError("Requested lap has no timing data")
    start = laps["LapStartTime"].min() - pd.Timedelta(seconds=5)
    end = laps["Time"].max() + pd.Timedelta(seconds=5)
    frames = {}
    for _, result in session.results.iterrows():
        code, number = str(result["Abbreviation"]), str(result["DriverNumber"])
        if drivers and code not in drivers:
            continue
        car = session.car_data.get(number)
        if car is None or car.empty:
            continue
        frame = pd.DataFrame(car[(car["SessionTime"] >= start) & (car["SessionTime"] <= end)]).copy()
        frame = frame.sort_values("SessionTime").drop_duplicates("SessionTime").reset_index(drop=True)
        if frame.empty:
            continue
        frame = merge_position_channels(frame, session.pos_data.get(number))
        frame["TimeSeconds"] = frame["SessionTime"].apply(timedelta_to_seconds)
        frames[code] = compute_g_forces(frame)
    if not frames:
        raise ValueError("No telemetry available for requested drivers")
    return {
        "event_date": pd.Timestamp(session.date).date().isoformat(),
        "name": f"{year} {session.event['EventName']} · lap {lap}",
        "lap": lap,
    }, frames


def packets_from_frames(metadata, frames, session_id=None, display_interval=1.0):
    """Every native sample reaches detection; frames are never future-matched."""
    session_id = session_id or str(uuid.uuid4())
    events = [
        (float(row["TimeSeconds"]), driver, row)
        for driver, frame in frames.items()
        for _, row in frame.iterrows()
    ]
    events.sort(key=lambda e: (e[0], e[1]))
    detector = DriverAgnosticDetector()
    history = {driver: deque(maxlen=100) for driver in frames}
    latest, pending = {}, []
    sequence, last_display = 0, -float("inf")
    for t, simultaneous in groupby(events, key=lambda event: event[0]):
        for _, driver, row in simultaneous:
            sample = {
                "driver": driver,
                "session_time_s": t,
                "speed_kph": finite(row.get("Speed")),
                "lateral_g": finite(row.get("lateral_g")),
                "longitudinal_g": finite(row.get("longitudinal_g")),
                "brake_applied": bool(row["Brake"]) if pd.notna(row.get("Brake")) else None,
                "position_age_s": finite(row.get("position_age_s")),
            }
            history[driver].append(sample)
            latest[driver] = sample
            candidate = detector.observe(driver, sample)
            if candidate:
                pending.append(
                    {
                        "id": f"{session_id}:{driver}:{t:.6f}",
                        "session_id": session_id,
                        "event_date": metadata["event_date"],
                        "title": f"Telemetry anomaly · {driver}",
                        "driver": driver,
                        "lap": metadata["lap"],
                        "incident_type": "telemetry_anomaly",
                        "samples": list(history[driver]),
                        "observations": [],
                        "evidence_mode": "telemetry_only",
                        "limitations": [
                            candidate["reason"],
                            "Public positions cannot establish overlap, contact or responsibility.",
                        ],
                    }
                )
        if t - last_display >= display_interval:
            yield {
                "session_id": session_id,
                "sequence": sequence,
                "event_date": metadata["event_date"],
                "session_name": metadata["name"],
                "session_time_s": t,
                "status": "REPLAY",
                "all_drivers": [
                    {
                        "driver_code": code,
                        "current_speed": item["speed_kph"] if t - item["session_time_s"] <= 1 else None,
                        "lap_number": None,
                        "status": "ACTIVE" if t - item["session_time_s"] <= 1 else "UNKNOWN",
                    }
                    for code, item in sorted(latest.items())
                ],
                "cases": pending,
            }
            pending, last_display = [], t
            sequence += 1
    if events:
        yield {
            "session_id": session_id,
            "sequence": sequence,
            "event_date": metadata["event_date"],
            "session_name": metadata["name"],
            "session_time_s": events[-1][0],
            "status": "FINISHED",
            "all_drivers": [
                {
                    "driver_code": code,
                    "current_speed": item["speed_kph"]
                    if events[-1][0] - item["session_time_s"] <= 1
                    else None,
                    "lap_number": None,
                    "status": "UNKNOWN",
                }
                for code, item in sorted(latest.items())
            ],
            "cases": pending,
        }


def send_packet(client, endpoint, packet):
    """Ordered idempotent retries; never acknowledge a dropped packet."""
    for attempt in range(3):
        try:
            response = client.post(endpoint, json=packet, timeout=10)
            if response.status_code < 500:
                response.raise_for_status()
                return response.json()
        except (requests.ConnectionError, requests.Timeout):
            if attempt == 2:
                raise
        if attempt < 2:
            time.sleep(0.2 * (2**attempt))
    raise RuntimeError("Telemetry was not durably accepted after three attempts")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--gp", default="Sao Paulo")
    parser.add_argument("--start-lap", type=int, default=6)
    parser.add_argument("--drivers", nargs="*")
    parser.add_argument("--endpoint", default="http://127.0.0.1:3000/api/telemetry")
    parser.add_argument("--export", type=Path)
    parser.add_argument("--no-send", action="store_true")
    parser.add_argument("--pace", type=float, default=1.0)
    args = parser.parse_args()
    metadata, frames = load_session(args.year, args.gp, args.start_lap, args.drivers)
    packets = list(packets_from_frames(metadata, frames))
    if args.export:
        args.export.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            driver: [
                {
                    "driver": driver,
                    "session_time_s": float(r.TimeSeconds),
                    "speed_kph": finite(r.Speed),
                    "lateral_g": finite(r.lateral_g),
                    "longitudinal_g": finite(r.longitudinal_g),
                }
                for r in frame.itertuples()
            ]
            for driver, frame in frames.items()
        }
        args.export.write_text(
            json.dumps({"metadata": metadata, "native_samples": raw, "packets": packets}, allow_nan=False),
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "drivers": len(frames),
                "native_samples": sum(map(len, frames.values())),
                "packets": len(packets),
                "candidates": sum(len(p["cases"]) for p in packets),
            }
        )
    )
    if not args.no_send:
        with requests.Session() as client:
            for packet in packets:
                send_packet(client, args.endpoint, packet)
                time.sleep(max(0, args.pace))


if __name__ == "__main__":
    main()
