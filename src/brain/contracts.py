"""Validated evidence contracts. Unknown is never coerced to false or zero."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, model_validator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    predicate: str = Field(min_length=1, max_length=80)
    value: StrictBool
    source: Literal["telemetry", "video_annotation", "official_document", "reviewer_annotation"]
    source_ref: str = Field(min_length=1, max_length=1000)
    detail: str = Field(min_length=1, max_length=1500)
    verified: StrictBool = False
    time_s: FiniteFloat | None = None


class Sample(StrictModel):
    driver: str = Field(min_length=1, max_length=20)
    session_time_s: FiniteFloat = Field(ge=0)
    speed_kph: FiniteFloat | None = Field(default=None, ge=0, le=450)
    lateral_g: FiniteFloat | None = Field(default=None, ge=0, le=12)
    longitudinal_g: FiniteFloat | None = Field(default=None, ge=-12, le=12)
    brake_applied: bool | None = None
    position_age_s: FiniteFloat | None = Field(default=None, ge=0)


class CaseInput(StrictModel):
    id: str = Field(min_length=1, max_length=120)
    session_id: str = Field(min_length=1, max_length=120)
    event_date: date
    championship: Literal["F1"] = "F1"
    session_type: Literal["R", "S", "Q", "FP"] = "R"
    title: str = Field(min_length=1, max_length=200)
    driver: str = Field(min_length=1, max_length=20)
    rival: str | None = Field(default=None, max_length=20)
    lap: int = Field(ge=0)
    corner: str = Field(default="Unknown", max_length=100)
    incident_type: Literal["collision", "off_track", "forced_wide", "telemetry_anomaly", "other"]
    evidence_mode: Literal["telemetry_only", "reviewed_evidence", "document_reconstruction"] = (
        "telemetry_only"
    )
    observations: list[Evidence] = Field(default_factory=list, max_length=100)
    samples: list[Sample] = Field(default_factory=list, max_length=5000)
    limitations: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_sources(self):
        ids = [item.id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence IDs must be unique")
        latest = {}
        for sample in self.samples:
            if sample.session_time_s <= latest.get(sample.driver, -1):
                raise ValueError("Samples must have increasing native timestamps per driver")
            latest[sample.driver] = sample.session_time_s
        if self.evidence_mode == "telemetry_only" and any(e.source != "telemetry" for e in self.observations):
            raise ValueError("Non-telemetry evidence requires an explicit reviewed/reconstruction mode")
        if self.evidence_mode != "document_reconstruction" and any(
            e.source == "official_document" for e in self.observations
        ):
            raise ValueError("Official decision facts must be labelled document_reconstruction")
        return self


class DriverSnapshot(StrictModel):
    driver_code: str = Field(min_length=1, max_length=20)
    driver_number: str | None = None
    team: str | None = None
    team_color: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{6}$")
    position_rank: int | None = Field(default=None, ge=1)
    lap_number: int | None = Field(default=None, ge=0)
    current_speed: FiniteFloat | None = Field(default=None, ge=0, le=450)
    delta_to_leader: FiniteFloat | None = Field(default=None, ge=0)
    gap_text: str | None = None
    sector: str | None = None
    throttle: FiniteFloat | None = Field(default=None, ge=0, le=100)
    brake_applied: StrictBool | None = None
    gear: int | None = Field(default=None, ge=0, le=8)
    rpm: FiniteFloat | None = Field(default=None, ge=0, le=25000)
    drs: int | None = Field(default=None, ge=0, le=20)
    lateral_g: FiniteFloat | None = Field(default=None, ge=0, le=12)
    longitudinal_g: FiniteFloat | None = Field(default=None, ge=-12, le=12)
    sample_time_s: FiniteFloat | None = Field(default=None, ge=0)
    timing_source: str | None = None
    status: Literal["ACTIVE", "PIT", "OUT", "UNKNOWN"] = "UNKNOWN"


class RaceMessage(StrictModel):
    id: str
    message: str = Field(max_length=3000)
    time: str | None = None
    category: str | None = None


class TelemetryPacket(StrictModel):
    session_id: str = Field(min_length=1, max_length=120)
    sequence: int = Field(ge=0)
    event_date: date
    session_name: str = Field(min_length=1, max_length=200)
    session_time_s: FiniteFloat = Field(ge=0)
    status: Literal["REPLAY", "LIVE", "FINISHED"] = "REPLAY"
    native_samples_processed: int = Field(default=0, ge=0)
    source: str = "external"
    race_control: list[RaceMessage] = Field(default_factory=list, max_length=100)
    track_status: str | None = None
    all_drivers: list[DriverSnapshot] = Field(default_factory=list, max_length=40)
    cases: list[CaseInput] = Field(default_factory=list, max_length=40)

    @model_validator(mode="after")
    def validate_session(self):
        if any(c.session_id != self.session_id or c.event_date != self.event_date for c in self.cases):
            raise ValueError("Case and packet session/date must match")
        codes = [d.driver_code for d in self.all_drivers]
        if len(codes) != len(set(codes)):
            raise ValueError("Duplicate driver snapshot")
        return self


class Condition(StrictModel):
    predicate: str
    status: Literal["supported", "contradicted", "unknown", "conflicting"]
    evidence_ids: list[str]


class ModelReview(StrictModel):
    conditions: list[Condition]
    rule_ids: list[str]
    summary: str = Field(min_length=1, max_length=2000)
    alternative_explanation: str = Field(min_length=1, max_length=2000)
    missing_facts: list[str]


class WorkflowUpdate(StrictModel):
    status: Literal["open", "closed"]
    expected_version: int = Field(ge=1)
