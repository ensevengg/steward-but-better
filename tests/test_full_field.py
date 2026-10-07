import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from threading import Event
import time
import zlib

from fastapi.testclient import TestClient
import pandas as pd
import pytest

from src.brain.contracts import TelemetryPacket
from src.brain.judging import assess
from src.brain.server import create_app
from src.brain.studies import field_packets
from src.telemetry.live_bridge import LiveField, decode_payload, records
from src.telemetry.live_simulator import packets_from_frames

ORIGIN = datetime(2025, 11, 9, 15, tzinfo=timezone.utc)


def stamp(t):
    return (ORIGIN + timedelta(seconds=t)).isoformat()


def feed(state, t, count=20, invalid=False):
    channels = {"0": 11000, "2": 200, "3": 5, "4": 104 if invalid else 80, "5": 0}
    return state.consume(
        [
            "CarData.z",
            {"Entries": [{"Utc": stamp(t), "Cars": {str(i): {"Channels": channels} for i in range(count)}}]},
            stamp(t),
        ]
    )


def test_whole_roster_present_before_every_car_has_a_sample():
    frames = {"A": pd.DataFrame({"TimeSeconds": [1, 2], "Speed": [100, 110]})}
    meta = {
        "event_date": "2025-11-09",
        "name": "Race",
        "roster": {code: {"driver_code": code} for code in ["A", "B"]},
    }
    packets = list(packets_from_frames(meta, frames))
    assert len(packets[0]["all_drivers"]) == 2
    assert packets[0]["all_drivers"][1]["status"] == "UNKNOWN"
    assert packets[-1]["native_samples_processed"] == 2


def test_candidate_can_arrive_late_in_continuous_race_for_any_driver():
    times = [i * 0.25 for i in range(1600)]
    frames = {
        str(i): pd.DataFrame({"TimeSeconds": times, "Speed": [300] * 1600, "lateral_g": [6] * 1600})
        for i in range(24)
    }
    frames["23"].loc[1400:, "Speed"] = 200
    packets = list(
        packets_from_frames({"event_date": "2025-11-09", "name": "Synthetic sustained race"}, frames)
    )
    cases = [case for packet in packets for case in packet["cases"]]
    assert {c["driver"] for c in cases} == {"23"}
    assert packets[-1]["native_samples_processed"] == 38400
    assert all(len(p["all_drivers"]) == 24 for p in packets)
    assert all(TelemetryPacket.model_validate(p) for p in packets)


def test_recorded_field_fixture_has_twenty_drivers_and_evolving_telemetry():
    _, packets = field_packets()
    assert len(packets) > 60
    assert all(len(p.all_drivers) == 20 for p in packets)
    assert packets[-1].native_samples_processed > packets[0].native_samples_processed
    assert packets[0].all_drivers != packets[10].all_drivers
    assert not any(p.cases for p in packets)


def test_corrupt_native_channels_do_not_interrupt_the_field():
    frames = {
        "A": pd.DataFrame(
            {
                "TimeSeconds": [1, 2],
                "Speed": [100, 110],
                "nGear": [17, 5],
                "RPM": [30000, 11000],
                "DRS": [99, 12],
                "Throttle": [104, 80],
            }
        )
    }
    packets = list(packets_from_frames({"event_date": "2025-11-09", "name": "Race"}, frames))
    parsed = [TelemetryPacket.model_validate(p) for p in packets]
    first = parsed[0].all_drivers[0]
    assert first.gear is None and first.rpm is None and first.drs is None and first.throttle is None
    assert parsed[-1].all_drivers[0].gear == 5
    assert parsed[-1].native_samples_processed == 2


def test_live_compressed_channels_all_drivers_and_delta_merging():
    state = LiveField("live", stamp(0), "Live protocol test")
    state.consume(["DriverList", {str(i): {"Tla": f"D{i}", "TeamName": "Test"} for i in range(20)}, stamp(0)])
    feed(state, 1)
    state.consume(
        [
            "TimingData",
            {"Lines": {"0": {"Position": "1", "NumberOfLaps": 6, "GapToLeader": "LAP 1"}}},
            stamp(1),
        ]
    )
    state.consume(["TimingData", {"Lines": {"0": {"InPit": True}}}, stamp(1.2)])
    state.consume(
        [
            "RaceControlMessages",
            {"Messages": {"1": {"Message": "TEST YELLOW FLAG", "Category": "Flag", "Utc": stamp(1)}}},
            stamp(1),
        ]
    )
    packet = state.snapshot()
    assert len(packet.all_drivers) == 20
    assert packet.native_samples_processed == 20
    assert packet.all_drivers[0].status == "PIT"
    assert packet.all_drivers[0].position_rank == 1
    assert packet.all_drivers[0].gap_text == "LAP 1"
    assert packet.all_drivers[0].drs is None
    assert len(packet.race_control) == 1
    payload = {"Entries": [{"Utc": stamp(2), "Cars": {"0": {"Channels": {"2": 210, "4": 10, "5": 100}}}}]}
    compressor = zlib.compressobj(wbits=-15)
    encoded = base64.b64encode(
        compressor.compress(json.dumps(payload).encode()) + compressor.flush()
    ).decode()
    state.consume(["CarData.z", encoded, stamp(2)])
    assert state.snapshot().all_drivers[0].current_speed == 210
    assert state.snapshot().all_drivers[0].brake_applied is True
    assert state.snapshot().all_drivers[0].rpm is None


def test_live_duplicate_old_samples_and_stale_channels():
    state = LiveField("live", stamp(0), "Test")
    feed(state, 1)
    feed(state, 1)
    feed(state, 0.5)
    assert state.processed == 20
    feed(state, 5, 1)
    packet = state.snapshot()
    assert len(packet.all_drivers) == 20
    assert packet.all_drivers[1].current_speed is None
    assert packet.all_drivers[1].status == "UNKNOWN"


def test_live_invalid_channel_unknown_not_rejected_or_clipped():
    state = LiveField("live", stamp(0), "Test")
    feed(state, 1, invalid=True)
    assert all(d.throttle is None for d in state.snapshot().all_drivers)
    assert state.snapshot().native_samples_processed == 20


def test_live_position_never_future_matches():
    state = LiveField("live", stamp(0), "Test")
    state.consume(
        [
            "Position.z",
            {"Position": [{"Timestamp": stamp(10), "Entries": {"0": {"X": 1000, "Y": 200}}}]},
            stamp(10),
        ]
    )
    feed(state, 1, 1)
    assert state.history["0"][-1]["X"] is None
    assert state.snapshot().all_drivers[0].lateral_g is None


def test_record_reader_waits_for_complete_line_and_rejects_code(tmp_path):
    path = tmp_path / "feed.txt"
    path.write_text(repr(["DriverList", {}, stamp(0)]) + "\n", encoding="utf-8")
    assert len(list(records(path))) == 1
    path.write_text('__import__("os").system("echo unsafe")', encoding="utf-8")
    with pytest.raises(ValueError):
        list(records(path))
    with pytest.raises((ValueError, zlib.error)):
        decode_payload("not a compressed message!")


def test_slow_judge_never_blocks_live_field_ingestion(tmp_path, reviewed_case):
    entered, release = Event(), Event()

    def slow(case):
        entered.set()
        assert release.wait(10)
        return assess(case)

    with TestClient(create_app(tmp_path / "state.db", judge=slow)) as client:
        assert client.post("/cases", json=reviewed_case.model_dump(mode="json")).status_code == 202
        assert entered.wait(2)
        started = time.monotonic()
        try:
            for i in range(60):
                packet = {
                    "session_id": reviewed_case.session_id,
                    "sequence": i,
                    "event_date": "2025-11-09",
                    "session_name": "Continuous field",
                    "session_time_s": i,
                    "status": "LIVE",
                    "native_samples_processed": (i + 1) * 20,
                    "all_drivers": [{"driver_code": f"D{d}", "current_speed": 100 + i} for d in range(20)],
                }
                assert client.post("/telemetry", json=packet).status_code == 202
            state = client.get("/state").json()
            assert state["live"]["sequence"] == 59
            assert len(state["live"]["all_drivers"]) == 20
            assert state["investigations"][0]["processing_state"] == "processing"
            assert time.monotonic() - started < 5
        finally:
            release.set()


def test_partial_live_record_is_not_published(tmp_path):
    path = tmp_path / "live.txt"
    path.write_text("['DriverList',", encoding="utf-8")
    iterator = records(path, follow=True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(next, iterator)
        time.sleep(0.1)
        assert not future.done()
        with path.open("a", encoding="utf-8") as stream:
            stream.write("{}, '2025-11-09T15:00:00Z']\n")
        assert future.result(timeout=2)[0] == "DriverList"
    iterator.close()
