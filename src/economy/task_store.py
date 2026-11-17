"""SQLite-backed durable task queue with leases and append-only task events."""
from __future__ import annotations

import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    """Transactional single-host queue with idempotency, bounded retries, and leases."""

    def __init__(self, path: str | Path = "./data/economy.sqlite3",
                 lease_seconds: int = 300) -> None:
        if not 1 <= lease_seconds <= 86400:
            raise ValueError("lease_seconds must be between 1 and 86400")
        self.path = str(path)
        self.lease_seconds = lease_seconds
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    idempotency_key TEXT UNIQUE,
                    title TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    assigned_agent TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
                    result TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    lease_until TEXT,
                    lease_token TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_status_created
                    ON tasks(status, created_at);
                CREATE TABLE IF NOT EXISTS task_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(tasks)")}
            if "lease_until" not in columns:
                db.execute("ALTER TABLE tasks ADD COLUMN lease_until TEXT")
            if "lease_token" not in columns:
                db.execute("ALTER TABLE tasks ADD COLUMN lease_token TEXT")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def _event(self, db: sqlite3.Connection, task_id: str, event: str,
               details: dict[str, Any] | None = None) -> None:
        db.execute(
            "INSERT INTO task_events(task_id,event_type,details_json,created_at) VALUES(?,?,?,?)",
            (task_id, event, json.dumps(details or {}, sort_keys=True), _now()),
        )

    def enqueue(self, title: str, objective: str, assigned_agent: str,
                idempotency_key: str | None = None, max_attempts: int = 3) -> dict[str, Any]:
        if not title.strip() or not objective.strip() or not assigned_agent.strip():
            raise ValueError("title, objective, and assigned_agent are required")
        if not 1 <= max_attempts <= 10:
            raise ValueError("max_attempts must be between 1 and 10")
        task_id, now = str(uuid.uuid4()), _now()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if idempotency_key:
                existing = db.execute(
                    "SELECT * FROM tasks WHERE idempotency_key=?", (idempotency_key,)
                ).fetchone()
                if existing:
                    db.commit()
                    return self._row(existing) or {}
            db.execute(
                """INSERT INTO tasks(task_id,idempotency_key,title,objective,assigned_agent,
                   status,attempts,max_attempts,created_at,updated_at)
                   VALUES(?,?,?,?,?,'queued',0,?,?,?)""",
                (task_id, idempotency_key, title.strip(), objective.strip(),
                 assigned_agent.strip(), max_attempts, now, now),
            )
            self._event(db, task_id, "queued", {"agent": assigned_agent})
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            db.commit()
            return self._row(row) or {}

    def enqueue_for_participant(self, title: str, objective: str,
                                participant_id: str, registry, *,
                                idempotency_key: str | None = None,
                                max_attempts: int = 3) -> dict[str, Any]:
        """Queue work for a currently active, key-bound agent participant.

        The registry is supplied explicitly so task assignment cannot silently
        infer a participant from a display name, role label, or unverified handle.
        """
        if not isinstance(participant_id, str) or not participant_id.strip():
            raise ValueError("participant_id is required")
        participant = registry.get(participant_id)
        if participant is None:
            raise ValueError("agent participant does not exist")
        if participant.get("participant_type") != "agent":
            raise ValueError("tasks can only be assigned to agent participants")
        if participant.get("status") != "active":
            raise ValueError("agent participant must be active")
        if not participant.get("public_key"):
            raise ValueError("agent participant must have a bound signing key")
        return self.enqueue(
            title, objective, participant_id,
            idempotency_key=idempotency_key, max_attempts=max_attempts,
        )

    def claim(self, allowed_agent_ids: list[str] | tuple[str, ...] | None = None) -> dict[str, Any] | None:
        """Recover expired leases, then claim one queued task.

        When an allowlist is supplied, only tasks assigned to those exact agent IDs
        are eligible. An empty allowlist deliberately claims nothing.
        """
        if allowed_agent_ids is not None:
            if any(not isinstance(item, str) or not item.strip() for item in allowed_agent_ids):
                raise ValueError("allowed_agent_ids must contain non-empty strings")
            allowed_agent_ids = list(dict.fromkeys(allowed_agent_ids))
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            now_dt = datetime.now(timezone.utc)
            now = now_dt.isoformat()
            expired = db.execute(
                "SELECT * FROM tasks WHERE status='running' AND lease_until IS NOT NULL AND lease_until<=?",
                (now,),
            ).fetchall()
            for old in expired:
                retry = old["attempts"] < old["max_attempts"]
                status = "queued" if retry else "failed"
                db.execute(
                    "UPDATE tasks SET status=?,lease_until=NULL,lease_token=NULL,updated_at=? WHERE task_id=?",
                    (status, now, old["task_id"]),
                )
                self._event(
                    db, old["task_id"],
                    "lease_expired_retry" if retry else "lease_expired_failed",
                    {"attempt": old["attempts"]},
                )
            if allowed_agent_ids is None:
                row = db.execute(
                    "SELECT * FROM tasks WHERE status='queued' ORDER BY created_at, task_id LIMIT 1"
                ).fetchone()
            elif not allowed_agent_ids:
                row = None
            else:
                placeholders = ",".join("?" for _ in allowed_agent_ids)
                row = db.execute(
                    f"SELECT * FROM tasks WHERE status='queued' AND assigned_agent IN ({placeholders}) "
                    "ORDER BY created_at, task_id LIMIT 1",
                    tuple(allowed_agent_ids),
                ).fetchone()
            if row is None:
                db.commit()
                return None
            lease_until = (now_dt + timedelta(seconds=self.lease_seconds)).isoformat()
            lease_token = secrets.token_urlsafe(32)
            db.execute(
                "UPDATE tasks SET status='running',attempts=attempts+1,updated_at=?,lease_until=?,lease_token=? "
                "WHERE task_id=? AND status='queued'",
                (now, lease_until, lease_token, row["task_id"]),
            )
            self._event(db, row["task_id"], "started", {"attempt": row["attempts"] + 1})
            claimed = db.execute(
                "SELECT * FROM tasks WHERE task_id=?", (row["task_id"],)
            ).fetchone()
            db.commit()
            return self._row(claimed)

    def finish(self, task_id: str, result: str, lease_token: str) -> dict[str, Any]:
        if not isinstance(result, str) or len(result) > 65536:
            raise ValueError("result must be text no longer than 65536 characters")
        return self._transition(task_id, "completed", result, "completed", lease_token)

    def fail(self, task_id: str, error: str, lease_token: str) -> dict[str, Any]:
        if not isinstance(error, str) or len(error) > 4096:
            raise ValueError("error must be text no longer than 4096 characters")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                db.rollback()
                raise KeyError(task_id)
            lease_expired = (
                not row["lease_until"]
                or datetime.fromisoformat(row["lease_until"]) <= datetime.now(timezone.utc)
            )
            if (row["status"] != "running" or lease_expired
                    or not isinstance(lease_token, str) or not row["lease_token"]
                    or not secrets.compare_digest(row["lease_token"], lease_token)):
                db.rollback()
                raise ValueError("active task lease is missing, expired, or does not match")
            retry = row["attempts"] < row["max_attempts"]
            status = "queued" if retry else "failed"
            now = _now()
            db.execute(
                "UPDATE tasks SET status=?,result=?,updated_at=?,lease_until=NULL,lease_token=NULL WHERE task_id=?",
                (status, error, now, task_id),
            )
            self._event(db, task_id, "retry_scheduled" if retry else "failed",
                        {"error": error, "attempt": row["attempts"]})
            updated = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            db.commit()
            return self._row(updated) or {}

    def _transition(self, task_id: str, status: str, result: str, event: str,
                    lease_token: str) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status,lease_token,lease_until FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                db.rollback()
                raise KeyError(task_id)
            if row["status"] != "running" or not row["lease_token"] or not secrets.compare_digest(row["lease_token"], lease_token):
                db.rollback()
                raise ValueError("active task lease is missing or does not match")
            db.execute(
                "UPDATE tasks SET status=?,result=?,updated_at=?,lease_until=NULL WHERE task_id=?",
                (status, result, _now(), task_id),
            )
            self._event(db, task_id, event, {})
            updated = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            db.commit()
            return self._row(updated) or {}

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            return self._row(db.execute(
                "SELECT * FROM tasks WHERE task_id=?", (task_id,)
            ).fetchone())

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if status:
                rows = db.execute(
                    "SELECT * FROM tasks WHERE status=? ORDER BY created_at", (status,)
                )
            else:
                rows = db.execute("SELECT * FROM tasks ORDER BY created_at")
            return [dict(row) for row in rows.fetchall()]

    def summary_counts(self) -> dict[str, int]:
        """Return task totals grouped by status without exposing task contents."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT status, COUNT(*) AS total FROM tasks GROUP BY status"
            ).fetchall()
        return {row["status"]: row["total"] for row in rows}

    def list_for_agent(self, agent_id: str, status: str | None = None,
                       limit: int = 50) -> list[dict[str, Any]]:
        """Return only tasks assigned to one authenticated participant."""
        if not agent_id or not 1 <= limit <= 100:
            raise ValueError("agent_id and a limit from 1 to 100 are required")
        allowed = {"queued", "running", "completed", "failed"}
        if status is not None and status not in allowed:
            raise ValueError("unsupported task status")
        with self._connect() as db:
            if status:
                rows = db.execute(
                    "SELECT * FROM tasks WHERE assigned_agent=? AND status=? "
                    "ORDER BY created_at,task_id LIMIT ?",
                    (agent_id, status, limit),
                )
            else:
                rows = db.execute(
                    "SELECT * FROM tasks WHERE assigned_agent=? "
                    "ORDER BY created_at,task_id LIMIT ?",
                    (agent_id, limit),
                )
            return [dict(row) for row in rows.fetchall()]
    def events(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM task_events WHERE task_id=? ORDER BY event_id", (task_id,)
            )
            return [dict(row) for row in rows.fetchall()]
