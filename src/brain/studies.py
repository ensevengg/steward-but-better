"""Explicit retrospective studies. Expected outcomes never enter the assessor."""

from __future__ import annotations
import json
from pathlib import Path
import uuid
from .contracts import CaseInput, TelemetryPacket

BENCHMARKS = Path(__file__).resolve().parents[2] / "benchmarks"


def sao_paulo_packets():
    session_id = f"sao-paulo-study-{uuid.uuid4().hex[:12]}"
    reviewed = json.loads((BENCHMARKS / "sao_paulo_2025.json").read_text(encoding="utf-8"))
    recording = json.loads((BENCHMARKS / "sao_paulo_2025_telemetry.json").read_text(encoding="utf-8"))
    reviewed.update(id=f"{session_id}:reviewed", session_id=session_id, samples=recording["samples"])
    telemetry = {
        **reviewed,
        "id": f"{session_id}:telemetry",
        "title": "São Paulo · telemetry-only assessment",
        "evidence_mode": "telemetry_only",
        "observations": [],
        "limitations": [
            "Incident window selected retrospectively; the telemetry detector did not identify this collision.",
            "FastF1 positions cannot establish overlap or responsibility. Brake pressure is unavailable.",
        ],
    }
    cases = [CaseInput.model_validate(telemetry), CaseInput.model_validate(reviewed)]
    packets = []
    for i, row in enumerate(recording["display_packets"]):
        packets.append(
            TelemetryPacket(
                session_id=session_id,
                sequence=i,
                event_date="2025-11-09",
                session_name="São Paulo 2025 · incident study",
                session_time_s=row["session_time_s"],
                status="FINISHED" if i == len(recording["display_packets"]) - 1 else "REPLAY",
                all_drivers=[{**driver, "lap_number": None} for driver in row["all_drivers"]],
                cases=cases if i == 0 else [],
            )
        )
    return session_id, reviewed["id"], packets
