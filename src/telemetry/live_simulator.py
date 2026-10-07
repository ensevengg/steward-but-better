"""Replay native FastF1 samples; throttle display independently of detection."""

from __future__ import annotations
import argparse
from collections import deque
import json
from itertools import groupby
import heapq
from pathlib import Path
import time
import uuid
import pandas as pd
import requests
from .driver_agnostic_detector import DriverAgnosticDetector
from .telemetry_utils import compute_g_forces, merge_position_channels, timedelta_to_seconds


def finite(value):
    return None if value is None or pd.isna(value) else float(value)


def load_session(year, gp, lap=None, drivers=None, cache_dir="data/fastf1-cache", end_lap=None):
    import fastf1

    Path(cache_dir).mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(cache_dir)
    session = fastf1.get_session(year, gp, "R")
    session.load(telemetry=True, weather=False, messages=False)
    laps = session.laps if lap is None else session.laps[session.laps["LapNumber"] >= lap]
    if end_lap is not None:
        laps = laps[laps["LapNumber"] <= end_lap]
    if laps.empty:
        raise ValueError("Requested lap has no timing data")
    start = laps["LapStartTime"].min() - pd.Timedelta(seconds=5)
    end = laps["Time"].max() + pd.Timedelta(seconds=5)
    frames, roster = {}, {}
    for _, result in session.results.iterrows():
        code, number = str(result["Abbreviation"]), str(result["DriverNumber"])
        if drivers and code not in drivers:
            continue
        color = str(result.get("TeamColor", ""))
        roster[code] = {
            "driver_code": code,
            "driver_number": number,
            "team": str(result.get("TeamName", "")),
            "team_color": color
            if len(color) == 6 and all(c in "0123456789abcdefABCDEF" for c in color)
            else None,
        }
        car = session.car_data.get(number)
        if car is None or car.empty:
            continue
        if "Source" in car:
            # FastF1 can pad another driver's missing timestamps with zero values.
            # Only source car messages count as observations, never those padding rows.
            car = car[car["Source"] == "car"]
        frame = pd.DataFrame(car[(car["SessionTime"] >= start) & (car["SessionTime"] <= end)]).copy()
        frame = frame.sort_values("SessionTime").drop_duplicates("SessionTime").reset_index(drop=True)
        if frame.empty:
            continue
        frame = merge_position_channels(frame, session.pos_data.get(number))
        frame["TimeSeconds"] = frame["SessionTime"].apply(timedelta_to_seconds)
        # Lap labels use already-started laps; position uses completed timing only.
        driver_laps = (
            session.laps[session.laps["Driver"] == code] if "Driver" in session.laps else pd.DataFrame()
        )
        if not driver_laps.empty:
            starts = driver_laps[["LapStartTime", "LapNumber"]].dropna().copy()
            starts["TimeSeconds"] = starts["LapStartTime"].dt.total_seconds().astype(float)
            frame = pd.merge_asof(
                frame.sort_values("TimeSeconds"),
                starts[["TimeSeconds", "LapNumber"]].sort_values("TimeSeconds"),
                on="TimeSeconds",
                direction="backward",
            )
            if "Position" in driver_laps:
                finishes = driver_laps[["Time", "Position"]].dropna().copy()
                finishes["TimeSeconds"] = finishes["Time"].dt.total_seconds().astype(float)
                frame = pd.merge_asof(
                    frame,
                    finishes[["TimeSeconds", "Position"]].sort_values("TimeSeconds"),
                    on="TimeSeconds",
                    direction="backward",
                )
        frames[code] = compute_g_forces(frame)
    if not frames:
        raise ValueError("No telemetry available for requested drivers")
    return {
        "event_date": pd.Timestamp(session.date).date().isoformat(),
        "name": f"{year} {session.event['EventName']}" + (f" · from lap {lap}" if lap else " · full race"),
        "lap": lap or 0,
        "roster": roster,
    }, frames


def packets_from_frames(metadata, frames, session_id=None, display_interval=1.0):
    """Every native sample reaches detection; frames are never future-matched."""
    session_id = session_id or str(uuid.uuid4())
    if display_interval <= 0:
        raise ValueError("Display interval must be positive")

    # Bind each driver before creating its iterator; merge keeps only one head per car.
    def rows(driver, frame):
        for values in frame.itertuples(index=False, name=None):
            row = dict(zip(frame.columns, values))
            yield float(row["TimeSeconds"]), driver, row

    events = heapq.merge(
        *(rows(driver, frame) for driver, frame in frames.items()), key=lambda event: (event[0], event[1])
    )
    detector = DriverAgnosticDetector()
    history = {driver: deque(maxlen=100) for driver in frames}
    roster = metadata.get("roster") or {code: {"driver_code": code} for code in frames}
    latest, pending = {}, []
    sequence, last_display, processed, final_time = 0, -float("inf"), 0, None

    def snapshot(t, status):
        all_drivers = []
        for code, identity in roster.items():
            item = latest.get(code, {})
            fresh = bool(item) and t - item["sample_time_s"] <= 1
            all_drivers.append(
                {
                    **identity,
                    **item,
                    "status": "ACTIVE" if fresh else "UNKNOWN",
                    **(
                        {}
                        if fresh
                        else {
                            key: None
                            for key in [
                                "current_speed",
                                "throttle",
                                "brake_applied",
                                "gear",
                                "rpm",
                                "drs",
                                "lateral_g",
                                "longitudinal_g",
                            ]
                        }
                    ),
                }
            )
        return {
            "session_id": session_id,
            "sequence": sequence,
            "event_date": metadata["event_date"],
            "session_name": metadata["name"],
            "session_time_s": t,
            "status": status,
            "native_samples_processed": processed,
            "source": "FastF1 native replay",
            "all_drivers": all_drivers,
            "cases": list(pending),
        }

    for t, simultaneous in groupby(events, key=lambda event: event[0]):
        final_time = t
        for _, driver, row in simultaneous:
            processed += 1
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
            latest[driver] = {
                "current_speed": sample["speed_kph"],
                "sample_time_s": t,
                "lap_number": integer(row.get("LapNumber")),
                "position_rank": integer(row.get("Position")),
                "timing_source": "Last completed lap" if pd.notna(row.get("Position")) else None,
                "throttle": bounded(row.get("Throttle"), 0, 100),
                "brake_applied": sample["brake_applied"],
                "gear": integer(bounded(row.get("nGear"), 0, 8)),
                "rpm": bounded(row.get("RPM"), 0, 25000),
                "drs": integer(bounded(row.get("DRS"), 0, 20)),
                "lateral_g": sample["lateral_g"],
                "longitudinal_g": sample["longitudinal_g"],
            }
            candidate = detector.observe(driver, sample)
            if candidate:
                pending.append(
                    {
                        "id": f"{session_id}:{driver}:{t:.6f}",
                        "session_id": session_id,
                        "event_date": metadata["event_date"],
                        "title": f"Telemetry anomaly · {driver}",
                        "driver": driver,
                        "lap": integer(row.get("LapNumber")) or 0,
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
            yield snapshot(t, "REPLAY")
            pending.clear()
            last_display = t
            sequence += 1
    if final_time is not None:
        yield snapshot(final_time, "FINISHED")


def bounded(value, low, high):
    try:
        number = finite(value)
    except (ValueError, TypeError):
        return None
    return number if number is not None and low <= number <= high else None


def integer(value):
    return None if value is None or pd.isna(value) else int(value)


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
    parser.add_argument("--start-lap", type=int, help="Optional start bound; default is the entire race")
    parser.add_argument("--end-lap", type=int)
    parser.add_argument("--speed", type=float, default=1, help="Replay clock multiplier")
    parser.add_argument("--drivers", nargs="*")
    parser.add_argument("--endpoint", default="http://127.0.0.1:3000/api/telemetry")
    parser.add_argument("--export", type=Path)
    parser.add_argument("--no-send", action="store_true")
    parser.add_argument(
        "--pace", type=float, help="Legacy fixed seconds per packet; use --speed for clock pacing"
    )
    args = parser.parse_args()
    if args.speed <= 0:
        parser.error("--speed must be positive")
    metadata, frames = load_session(args.year, args.gp, args.start_lap, args.drivers, end_lap=args.end_lap)
    packets = packets_from_frames(metadata, frames)
    if args.export:
        packets = list(packets)
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
    counts = {
        "drivers": len(metadata["roster"]),
        "native_samples": sum(map(len, frames.values())),
        "packets": 0,
        "candidates": 0,
    }
    first_time, wall_start = None, time.monotonic()
    with requests.Session() as client:
        for packet in packets:
            counts["packets"] += 1
            counts["candidates"] += len(packet["cases"])
            if not args.no_send:
                if first_time is None:
                    first_time = packet["session_time_s"]
                if args.pace is None:
                    target = wall_start + (packet["session_time_s"] - first_time) / args.speed
                    time.sleep(max(0, target - time.monotonic()))
                send_packet(client, args.endpoint, packet)
                if args.pace is not None:
                    time.sleep(max(0, args.pace))
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
