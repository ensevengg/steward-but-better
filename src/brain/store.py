"""Transactional SQLite history and durable leased queue, separate from live data."""

from __future__ import annotations
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from .contracts import CaseInput, TelemetryPacket, now_iso


class ConflictError(ValueError):
    pass


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                  id TEXT PRIMARY KEY, sequence INTEGER NOT NULL, payload TEXT NOT NULL, received_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cases (
                  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, input TEXT NOT NULL, input_hash TEXT NOT NULL,
                  result TEXT, workflow TEXT NOT NULL DEFAULT 'open', version INTEGER NOT NULL DEFAULT 1,
                  state TEXT NOT NULL DEFAULT 'queued', attempts INTEGER NOT NULL DEFAULT 0,
                  lease_until REAL NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audit (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, action TEXT NOT NULL,
                  payload TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS cases_session ON cases(session_id, created_at);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _enqueue(self, db, case: CaseInput):
        payload = case.model_dump_json()
        digest = hashlib.sha256(payload.encode()).hexdigest()
        existing = db.execute("SELECT input_hash FROM cases WHERE id=?", (case.id,)).fetchone()
        if existing:
            if existing[0] != digest:
                raise ConflictError("Incident ID exists with different evidence; use a new case ID")
            return False
        now = now_iso()
        db.execute(
            "INSERT INTO cases(id,session_id,input,input_hash,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (case.id, case.session_id, payload, digest, now, now),
        )
        self._audit(db, case.id, "submitted", {"input_hash": digest})
        return True

    def enqueue(self, case: CaseInput):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._enqueue(db, case)

    def ingest(self, packet: TelemetryPacket) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT sequence,payload FROM sessions WHERE id=?", (packet.session_id,)
            ).fetchone()
            if old and json.loads(old["payload"])["event_date"] != packet.event_date.isoformat():
                raise ConflictError("Session event date cannot change")
            if old and packet.sequence <= old["sequence"]:
                return {"accepted": False, "reason": "duplicate_or_out_of_order", "sequence": old["sequence"]}
            if old and packet.session_time_s < json.loads(old["payload"])["session_time_s"]:
                raise ConflictError("Session time cannot move backwards; create a new replay session")
            if old and json.loads(old["payload"])["status"] == "FINISHED":
                raise ConflictError("Finished session is immutable; create a new replay session")
            inserted = sum(self._enqueue(db, case) for case in packet.cases)
            payload = packet.model_dump(mode="json", exclude={"cases"})
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET sequence=excluded.sequence,payload=excluded.payload,received_at=excluded.received_at",
                (packet.session_id, packet.sequence, json.dumps(payload), now_iso()),
            )
            return {"accepted": True, "queued": inserted, "sequence": packet.sequence}

    def claim(self, lease_seconds=90) -> tuple[CaseInput, int] | None:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM cases WHERE state IN ('queued','processing') AND lease_until<? ORDER BY created_at LIMIT 1",
                (time.time(),),
            ).fetchone()
            if not row:
                return None
            attempt = row["attempts"] + 1
            db.execute(
                "UPDATE cases SET state='processing',attempts=?,lease_until=? WHERE id=?",
                (attempt, time.time() + lease_seconds, row["id"]),
            )
            return CaseInput.model_validate_json(row["input"]), attempt

    def complete(self, case_id: str, result: dict, attempt: int) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "UPDATE cases SET result=?,state='complete',version=version+1,updated_at=? WHERE id=? AND state='processing' AND attempts=?",
                (json.dumps(result, allow_nan=False), now_iso(), case_id, attempt),
            )
            if cursor.rowcount:
                self._audit(db, case_id, "assessed", result)
            return bool(cursor.rowcount)

    def fail(self, case_id: str, attempt: int):
        with self.connect() as db:
            state = "failed" if attempt >= 3 else "queued"
            changed = db.execute(
                "UPDATE cases SET state=?,lease_until=?,updated_at=? WHERE id=? AND attempts=? AND state='processing'",
                (state, time.time() + min(30, 2**attempt), now_iso(), case_id, attempt),
            )
            if changed.rowcount:
                self._audit(db, case_id, "assessment_failed", {"attempt": attempt})

    def workflow(self, case_id: str, status: str, version: int):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT id FROM cases WHERE id=?", (case_id,)).fetchone():
                raise KeyError(case_id)
            changed = db.execute(
                "UPDATE cases SET workflow=?,version=version+1,updated_at=? WHERE id=? AND version=?",
                (status, now_iso(), case_id, version),
            )
            if not changed.rowcount:
                raise ConflictError("Case changed; refresh before updating its workflow")
            self._audit(db, case_id, "workflow", {"status": status})
        return self.get_case(case_id)

    @staticmethod
    def _audit(db, case_id, action, payload):
        db.execute(
            "INSERT INTO audit(case_id,action,payload,created_at) VALUES(?,?,?,?)",
            (case_id, action, json.dumps(payload), now_iso()),
        )

    @staticmethod
    def _case(row, detail=True):
        data = json.loads(row["result"] or row["input"])
        if not detail:
            data = {
                k: v
                for k, v in data.items()
                if k not in {"samples", "observations", "conditions", "rules", "model_review"}
            }
        return {
            **data,
            "workflow": row["workflow"],
            "version": row["version"],
            "processing_state": row["state"],
            "updated_at": row["updated_at"],
        }

    def get_case(self, case_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
            if row is None:
                raise KeyError(case_id)
            data = self._case(row)
            data["audit"] = [
                {"action": r["action"], "timestamp": r["created_at"]}
                for r in db.execute("SELECT * FROM audit WHERE case_id=? ORDER BY id", (case_id,))
            ]
            return data

    def snapshot(self, session_id: str | None = None):
        with self.connect() as db:
            sessions = [
                {"id": r["id"], "name": json.loads(r["payload"])["session_name"]}
                for r in db.execute("SELECT * FROM sessions ORDER BY rowid DESC")
            ]
            sessions.extend(
                {"id": r["session_id"], "name": f"Case review · {r['session_id']}"}
                for r in db.execute(
                    "SELECT session_id FROM cases WHERE session_id NOT IN (SELECT id FROM sessions) "
                    "GROUP BY session_id ORDER BY MIN(created_at) DESC"
                )
            )
            if session_id is None and sessions:
                session_id = sessions[0]["id"]
            live = db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            cases = (
                db.execute(
                    "SELECT * FROM cases WHERE session_id=? ORDER BY created_at DESC", (session_id,)
                ).fetchall()
                if session_id
                else db.execute("SELECT * FROM cases ORDER BY created_at DESC").fetchall()
            )
            return {
                "sessions": sessions,
                "live": {**json.loads(live["payload"]), "received_at": live["received_at"]} if live else None,
                "investigations": [self._case(r, detail=False) for r in cases],
                "server_time": now_iso(),
            }
