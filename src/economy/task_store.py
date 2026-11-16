"""SQLite-backed durable task queue. No external side effects are performed here."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    """Small transactional queue with idempotent enqueue and an append-only event log."""

    def __init__(self, path: str | Path = "./data/economy.sqlite3") -> None:
        self.path = str(path)
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
                    updated_at TEXT NOT NULL
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
        if max_attempts < 1 or max_attempts > 10:
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

    def claim(self) -> dict[str, Any] | None:
        """Atomically claim the oldest queued task; concurrent workers cannot claim it twice."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM tasks WHERE status='queued' ORDER BY created_at, task_id LIMIT 1"
            ).fetchone()
            if row is None:
                db.commit()
                return None
            now = _now()
            db.execute(
                "UPDATE tasks SET status='running', attempts=attempts+1, updated_at=? "
                "WHERE task_id=? AND status='queued'", (now, row["task_id"])
            )
            self._event(db, row["task_id"], "started", {"attempt": row["attempts"] + 1})
            claimed = db.execute("SELECT * FROM tasks WHERE task_id=?", (row["task_id"],)).fetchone()
            db.commit()
            return self._row(claimed)

    def finish(self, task_id: str, result: str) -> dict[str, Any]:
        return self._transition(task_id, "completed", result, "completed")

    def fail(self, task_id: str, error: str) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                db.rollback()
                raise KeyError(task_id)
            if row["status"] != "running":
                db.rollback()
                raise ValueError("only running tasks can fail")
            retry = row["attempts"] < row["max_attempts"]
            status = "queued" if retry else "failed"
            now = _now()
            db.execute("UPDATE tasks SET status=?, result=?, updated_at=? WHERE task_id=?",
                       (status, error, now, task_id))
            self._event(db, task_id, "retry_scheduled" if retry else "failed",
                        {"error": error, "attempt": row["attempts"]})
            updated = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            db.commit()
            return self._row(updated) or {}

    def _transition(self, task_id: str, status: str, result: str, event: str) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                db.rollback()
                raise KeyError(task_id)
            if row["status"] != "running":
                db.rollback()
                raise ValueError("only running tasks can complete")
            db.execute("UPDATE tasks SET status=?,result=?,updated_at=? WHERE task_id=?",
                       (status, result, _now(), task_id))
            self._event(db, task_id, event, {})
            updated = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            db.commit()
            return self._row(updated) or {}

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            return self._row(db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone())

    def list_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as db:
            if status:
                rows = db.execute("SELECT * FROM tasks WHERE status=? ORDER BY created_at", (status,))
            else:
                rows = db.execute("SELECT * FROM tasks ORDER BY created_at")
            return [dict(row) for row in rows.fetchall()]

    def events(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM task_events WHERE task_id=? ORDER BY event_id", (task_id,)
            )
            return [dict(row) for row in rows.fetchall()]
