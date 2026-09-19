"""Durable ingestion and asynchronous, evidence-based case assessment."""

from __future__ import annotations
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import threading
from .studies import sao_paulo_packets
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from .contracts import CaseInput, TelemetryPacket, WorkflowUpdate
from .judging import assess
from .providers import optional_review
from .store import ConflictError, Store

logger = logging.getLogger(__name__)


def process_one(store: Store, judge=None) -> bool:
    task = store.claim()
    if task is None:
        return False
    case, attempt = task
    try:
        result = (judge or (lambda c: optional_review(assess(c))))(case)
        store.complete(case.id, result, attempt)
    except Exception:
        logger.exception("Assessment failed for case %s", case.id)
        store.fail(case.id, attempt)
    return True


def create_app(db_path: str | Path | None = None, *, start_worker=True, judge=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        app.state.store = Store(db_path or os.getenv("STEWARD_DB", "data/steward.sqlite3"))
        stop = threading.Event()
        app.state.stop = stop
        app.state.replays = []
        app.state.replay_lock = threading.Lock()

        def worker():
            while not stop.is_set():
                try:
                    worked = process_one(app.state.store, judge)
                except Exception:
                    logger.exception("Queue temporarily unavailable")
                    worked = False
                if not worked:
                    stop.wait(0.15)

        thread = threading.Thread(target=worker, name="case-review", daemon=True)
        if start_worker:
            thread.start()
        yield
        stop.set()
        for replay in app.state.replays:
            replay.join(timeout=2)
        if start_worker:
            thread.join(timeout=55)

    app = FastAPI(title="Steward evidence service", version="2.0", lifespan=lifespan)

    @app.exception_handler(ConflictError)
    async def conflict_handler(request: Request, exc: ConflictError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.get("/health")
    def health():
        return {
            "status": "ready",
            "model_review": "configured" if os.getenv("STEWARD_OPENCODE_URL") else "disabled",
        }

    @app.post("/telemetry", status_code=202)
    def telemetry(packet: TelemetryPacket):
        return app.state.store.ingest(packet)

    @app.get("/state")
    def state(session_id: str | None = None):
        return app.state.store.snapshot(session_id)

    @app.post("/cases", status_code=202)
    def submit(case: CaseInput):
        return {"id": case.id, "queued": app.state.store.enqueue(case)}

    @app.get("/cases/{case_id}")
    def detail(case_id: str):
        try:
            return app.state.store.get_case(case_id)
        except KeyError:
            raise HTTPException(404, "Case not found")

    @app.patch("/cases/{case_id}")
    def workflow(case_id: str, update: WorkflowUpdate):
        try:
            return app.state.store.workflow(case_id, update.status, update.expected_version)
        except KeyError:
            raise HTTPException(404, "Case not found")

    @app.post("/verdict")
    def verdict(case: CaseInput):
        return optional_review(assess(case))

    @app.post("/studies/sao-paulo", status_code=202)
    def study():
        session_id, case_id, packets = sao_paulo_packets()

        def replay():
            for packet in packets[1:]:
                if app.state.stop.wait(0.25):
                    break
                app.state.store.ingest(packet)

        thread = threading.Thread(target=replay, daemon=True, name="historical-study")
        with app.state.replay_lock:
            app.state.replays = [t for t in app.state.replays if t.is_alive()]
            if len(app.state.replays) >= 3:
                raise HTTPException(429, "Wait for an active study to finish")
            app.state.store.ingest(packets[0])
            app.state.replays.append(thread)
            thread.start()
        return {"session_id": session_id, "case_id": case_id}

    return app


app = create_app()
