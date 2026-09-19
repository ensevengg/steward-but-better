import pandas as pd
from src.telemetry.driver_agnostic_detector import DriverAgnosticDetector
from src.telemetry.live_simulator import packets_from_frames
from src.brain.contracts import TelemetryPacket
from src.telemetry.incident_evaluator import evaluate_overtake_legality


def test_high_g_alone_does_not_trigger():
    d = DriverAgnosticDetector()
    for t in [1, 1.2, 1.4]:
        assert d.observe("A", {"session_time_s": t, "speed_kph": 250, "lateral_g": 6}) is None


def test_previous_speed_read_before_update_for_every_driver():
    d = DriverAgnosticDetector()
    for driver in ["A", "B", "PIA"]:
        d.observe(driver, {"session_time_s": 1, "speed_kph": 300, "lateral_g": 6})
        assert (
            d.observe(driver, {"session_time_s": 1.2, "speed_kph": 200, "lateral_g": 6})["driver"] == driver
        )


def test_stale_or_repeated_samples_cannot_trigger():
    d = DriverAgnosticDetector()
    d.observe("A", {"session_time_s": 1, "speed_kph": 300, "lateral_g": 6})
    assert d.observe("A", {"session_time_s": 1, "speed_kph": 100, "lateral_g": 6}) is None
    assert d.observe("A", {"session_time_s": 10, "speed_kph": 100, "lateral_g": 6}) is None


def test_native_event_survives_display_downsampling():
    frames = {
        name: pd.DataFrame(
            {
                "TimeSeconds": [1, 1.2, 1.4, 2.2],
                "Speed": [300, 200, 200, 200],
                "lateral_g": [6] * 4,
                "longitudinal_g": [0] * 4,
                "Brake": [False] * 4,
            }
        )
        for name in ["A", "B"]
    }
    packets = list(
        packets_from_frames(
            {"event_date": "2025-11-09", "name": "Synthetic regression", "lap": 6}, frames, session_id="test"
        )
    )
    assert {c["driver"] for p in packets for c in p["cases"]} == {"A", "B"}
    assert [p["sequence"] for p in packets] == list(range(len(packets)))
    assert all(TelemetryPacket.model_validate(p) for p in packets)
    assert {d["driver_code"] for d in packets[0]["all_drivers"]} == {"A", "B"}
    assert all(d["lap_number"] is None for d in packets[0]["all_drivers"])


def test_raw_geometry_never_issues_penalties():
    a = pd.DataFrame({"Speed": [250, 100], "X": [0, 10], "Y": [0, 0], "Brake": [False, True]})
    b = a.copy()
    b["Y"] = 1
    assert evaluate_overtake_legality(a, b)["verdict"]["verdict"] == "INCONCLUSIVE"
    assert evaluate_overtake_legality(a.iloc[:0], b)["verdict"]["verdict"] == "NO_DATA"
