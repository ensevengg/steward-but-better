from types import SimpleNamespace
import json
import os
from pathlib import Path
import subprocess
import sys

import fastf1
import pandas as pd
import pytest
import requests

from src.brain.contracts import CaseInput, TelemetryPacket
from src.telemetry.live_simulator import load_session, send_packet


def test_native_loader_aligns_shared_session_window(monkeypatch, tmp_path):
    times = pd.to_timedelta([0, 0.2, 0.4, 0.6], unit="s")
    car = pd.DataFrame({"SessionTime": times, "Speed": [100, 110, 120, 130], "Brake": [False] * 4})
    session = SimpleNamespace(
        laps=pd.DataFrame(
            {
                "LapNumber": [6],
                "LapStartTime": pd.to_timedelta([0], unit="s"),
                "Time": pd.to_timedelta([1], unit="s"),
            }
        ),
        date=pd.Timestamp("2025-11-09"),
        event={"EventName": "São Paulo Grand Prix"},
        results=pd.DataFrame({"Abbreviation": ["PIA", "ANT"], "DriverNumber": ["81", "12"]}),
        car_data={"81": car, "12": car.copy()},
        pos_data={"81": pd.DataFrame({"SessionTime": times, "X": [0, 100, 200, 300], "Y": [0, 10, 20, 30]})},
        load=lambda **kwargs: None,
    )
    monkeypatch.setattr(fastf1, "get_session", lambda *args: session)
    monkeypatch.setattr(fastf1.Cache, "enable_cache", lambda *args: None)
    metadata, frames = load_session(2025, "Sao Paulo", 6, cache_dir=tmp_path)
    assert metadata["event_date"] == "2025-11-09"
    assert frames["PIA"].TimeSeconds.tolist() == [0, 0.2, 0.4, 0.6]
    assert frames["PIA"].X.tolist() == [0, 10, 20, 30]
    assert frames["ANT"].lateral_g.isna().all()
    assert len(load_session(2025, "Sao Paulo", 6, ["PIA"], tmp_path)[1]) == 1
    with pytest.raises(ValueError, match="No telemetry"):
        load_session(2025, "Sao Paulo", 6, ["UNKNOWN"], tmp_path)
    with pytest.raises(ValueError, match="no timing"):
        load_session(2025, "Sao Paulo", 7, cache_dir=tmp_path)


def test_contract_rejects_duplicate_or_backward_native_samples(reviewed_case):
    data = reviewed_case.model_dump(mode="json")
    data["samples"] = [{"driver": "A", "session_time_s": 2}, {"driver": "A", "session_time_s": 1}]
    with pytest.raises(ValueError, match="increasing"):
        CaseInput.model_validate(data)


def test_contract_rejects_cross_session_cases_and_duplicate_drivers(reviewed_case):
    data = {
        "session_id": "different",
        "sequence": 1,
        "event_date": "2025-11-09",
        "session_name": "test",
        "session_time_s": 1,
        "cases": [reviewed_case],
    }
    with pytest.raises(ValueError, match="must match"):
        TelemetryPacket.model_validate(data)
    data.update(cases=[], all_drivers=[{"driver_code": "A"}, {"driver_code": "A"}])
    with pytest.raises(ValueError, match="Duplicate"):
        TelemetryPacket.model_validate(data)


def test_cli_runs_real_case_contract():
    env = {k: v for k, v in os.environ.items() if k != "STEWARD_OPENCODE_URL"}
    output = subprocess.run(
        [sys.executable, "-m", "src.brain.steward_agent", "benchmarks/sao_paulo_2025.json"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(output.stdout)["penalty_seconds"] == 10


@pytest.mark.parametrize("failure", [requests.Timeout(), 503])
def test_transport_exhaustion_is_not_acknowledged(monkeypatch, failure):
    monkeypatch.setattr("src.telemetry.live_simulator.time.sleep", lambda _: None)
    calls = []

    class Client:
        def post(self, *args, **kwargs):
            calls.append(1)
            if isinstance(failure, Exception):
                raise failure
            response = requests.Response()
            response.status_code = failure
            return response

    with pytest.raises((RuntimeError, requests.Timeout)):
        send_packet(Client(), "test", {})
    assert len(calls) == 3
