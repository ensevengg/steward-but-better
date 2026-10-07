from concurrent.futures import ThreadPoolExecutor
import time

from fastapi.testclient import TestClient
import pytest
import requests

from src.brain.contracts import TelemetryPacket
from src.brain.judging import assess
from src.brain.server import create_app, process_one
from src.brain.store import ConflictError, Store
from src.brain.studies import sao_paulo_packets
from src.telemetry.live_simulator import send_packet


def packet(case, sequence=0):
    return TelemetryPacket(
        session_id=case.session_id,
        sequence=sequence,
        event_date=case.event_date,
        session_name="Test replay",
        session_time_s=10 + sequence,
        cases=[case],
    )


def test_atomic_ingestion_idempotence_and_rollback(tmp_path, reviewed_case):
    store = Store(tmp_path / "state.db")
    assert store.ingest(packet(reviewed_case))["queued"] == 1
    assert not store.ingest(packet(reviewed_case))["accepted"]
    changed = reviewed_case.model_copy(update={"title": "Different evidence"})
    with pytest.raises(ConflictError):
        store.ingest(packet(changed, 1))
    assert store.snapshot()["live"]["sequence"] == 0
    assert len(store.snapshot()["investigations"]) == 1


def test_standalone_review_is_selectable_without_fabricating_live_data(tmp_path, reviewed_case):
    store = Store(tmp_path / "state.db")
    store.enqueue(reviewed_case)
    state = store.snapshot()
    assert state["sessions"][0]["id"] == reviewed_case.session_id
    assert state["live"] is None
    assert state["investigations"][0]["id"] == reviewed_case.id


def test_larger_sequence_cannot_rewind_session_time(tmp_path, reviewed_case):
    store = Store(tmp_path / "state.db")
    store.ingest(packet(reviewed_case, 5))
    with pytest.raises(ConflictError, match="backwards"):
        store.ingest(packet(reviewed_case, 6).model_copy(update={"session_time_s": 1}))
    assert store.snapshot()["live"]["session_time_s"] == 15


def test_out_of_order_finish_and_event_identity(tmp_path, reviewed_case):
    store = Store(tmp_path / "state.db")
    store.ingest(packet(reviewed_case, 5))
    assert not store.ingest(packet(reviewed_case, 2))["accepted"]
    changed = packet(reviewed_case, 6).model_copy(
        update={"event_date": reviewed_case.event_date.replace(year=2024), "cases": []}
    )
    with pytest.raises(ConflictError):
        store.ingest(changed)
    store.ingest(packet(reviewed_case, 6).model_copy(update={"status": "FINISHED"}))
    with pytest.raises(ConflictError):
        store.ingest(packet(reviewed_case, 7))


def test_lease_fencing_and_parallel_claims(tmp_path, reviewed_case):
    store = Store(tmp_path / "state.db")
    store.enqueue(reviewed_case)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.claim(), range(8)))
    assert sum(r is not None for r in results) == 1
    first = next(r for r in results if r)
    with store.connect() as db:
        db.execute("UPDATE cases SET lease_until=0")
    second = store.claim()
    assert second[1] == first[1] + 1
    assert not store.complete(reviewed_case.id, assess(reviewed_case), first[1])
    assert store.complete(reviewed_case.id, assess(reviewed_case), second[1])
    store.fail(reviewed_case.id, first[1])
    assert [a["action"] for a in store.get_case(reviewed_case.id)["audit"]] == ["submitted", "assessed"]


def test_delayed_judgment_cannot_rewind_live_or_reopen_case(tmp_path, reviewed_case):
    path = tmp_path / "state.db"
    store = Store(path)
    store.ingest(packet(reviewed_case))
    _, attempt = store.claim()
    closed = store.workflow(reviewed_case.id, "closed", 1)
    store.ingest(packet(reviewed_case, 100))
    store.complete(reviewed_case.id, assess(reviewed_case), attempt)
    restarted = Store(path)
    assert restarted.snapshot()["live"]["sequence"] == 100
    assert restarted.get_case(reviewed_case.id)["workflow"] == "closed"
    with pytest.raises(ConflictError):
        restarted.workflow(reviewed_case.id, "open", closed["version"])


def test_retries_end_in_visible_failed_state(tmp_path, reviewed_case):
    store = Store(tmp_path / "state.db")
    store.enqueue(reviewed_case)

    def broken(case):
        raise RuntimeError("Judge offline")

    for _ in range(3):
        with store.connect() as db:
            db.execute("UPDATE cases SET lease_until=0")
        assert process_one(store, broken)
    assert not process_one(store, broken)
    assert store.get_case(reviewed_case.id)["processing_state"] == "failed"


def test_new_session_focus_not_stolen_by_old_packets(tmp_path, reviewed_case):
    store = Store(tmp_path / "state.db")
    store.ingest(packet(reviewed_case))
    newer = reviewed_case.model_copy(update={"id": "new-case", "session_id": "new-session"})
    store.ingest(packet(newer))
    store.ingest(packet(reviewed_case, 9))
    assert store.snapshot()["live"]["session_id"] == "new-session"
    assert store.snapshot(reviewed_case.session_id)["live"]["sequence"] == 9


def test_api_validation_worker_and_workflow_restart(tmp_path, reviewed_case):
    path = tmp_path / "state.db"
    with TestClient(create_app(path, judge=assess)) as client:
        assert client.post("/telemetry", json={"garbage": True}).status_code == 422
        assert client.get("/cases/missing").status_code == 404
        assert (
            client.post("/telemetry", json=packet(reviewed_case).model_dump(mode="json")).status_code == 202
        )
        for _ in range(100):
            case = client.get(f"/cases/{reviewed_case.id}").json()
            if case["processing_state"] == "complete":
                break
            time.sleep(0.02)
        assert case["penalty_seconds"] == 10
        changed = client.patch(
            f"/cases/{reviewed_case.id}", json={"status": "closed", "expected_version": case["version"]}
        )
        assert changed.status_code == 200
        assert (
            client.patch(
                f"/cases/{reviewed_case.id}", json={"status": "open", "expected_version": case["version"]}
            ).status_code
            == 409
        )
        assert (
            client.post("/verdict", json=reviewed_case.model_dump(mode="json")).json()["penalty_seconds"]
            == 10
        )
    with TestClient(create_app(path, start_worker=False)) as client:
        assert client.get(f"/cases/{reviewed_case.id}").json()["workflow"] == "closed"


def test_recorded_real_pipeline_keeps_reconstruction_separate(tmp_path):
    session, case_id, packets = sao_paulo_packets()
    store = Store(tmp_path / "real.db")
    for p in packets:
        store.ingest(p)
        while process_one(store, assess):
            pass
    state = store.snapshot(session)
    assert state["live"]["status"] == "FINISHED"
    assert len(state["investigations"]) == 2
    documented = store.get_case(case_id)
    assert documented["penalty_seconds"] == 10
    raw = next(c for c in state["investigations"] if c["evidence_mode"] == "telemetry_only")
    assert raw["ruling"] == "INSUFFICIENT_EVIDENCE"
    assert raw["penalty_seconds"] is None
    assert len(documented["samples"]) == 576


@pytest.mark.parametrize("failure", [requests.ConnectionError(), requests.Timeout(), 503])
def test_transport_retries_same_packet(monkeypatch, failure):
    monkeypatch.setattr("src.telemetry.live_simulator.time.sleep", lambda _: None)
    seen = []

    class Client:
        def post(self, endpoint, json, timeout):
            seen.append(json)
            if len(seen) == 1 and isinstance(failure, Exception):
                raise failure
            response = requests.Response()
            response.status_code = failure if len(seen) == 1 else 202
            response._content = b'{"accepted": true}'
            return response

    assert send_packet(Client(), "test", {"sequence": 3})["accepted"]
    assert seen == [{"sequence": 3}] * 2


def test_transport_never_hides_rejection(monkeypatch):
    monkeypatch.setattr("src.telemetry.live_simulator.time.sleep", lambda _: None)

    class Client:
        def post(self, *args, **kwargs):
            response = requests.Response()
            response.status_code = 422
            return response

    with pytest.raises(requests.HTTPError):
        send_packet(Client(), "test", {})
