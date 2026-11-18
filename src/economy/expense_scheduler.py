"""Recurring, policy-bounded simulated agent expense scheduler.

This module records schedules and runs due occurrences only through
AgentSpending's signed-policy checks and simulated journal. It does not
contact vendors, submit payment instructions, or create live transfers.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .financial_spending import AgentSpending, FinancialSpendingError


class ExpenseScheduleError(ValueError):
    """Invalid or unauthorized recurring expense schedule."""


class AgentExpenseScheduler:
    """Durable recurring schedule runner; safe to call repeatedly."""

    def __init__(self, spending: AgentSpending,
                 path: str | Path = "./data/financial-expense-schedules.sqlite3") -> None:
        self.spending = spending
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_expense_schedules (
                    schedule_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    terms_sha256 TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    policy_version INTEGER NOT NULL,
                    destination TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                    interval_seconds INTEGER NOT NULL,
                    next_run_at TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','paused','cancelled')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS agent_expense_schedules_due
                    ON agent_expense_schedules(status,next_run_at);
                CREATE TABLE IF NOT EXISTS agent_expense_occurrences (
                    occurrence_id TEXT PRIMARY KEY,
                    schedule_id TEXT NOT NULL REFERENCES agent_expense_schedules(schedule_id),
                    due_at TEXT NOT NULL,
                    reservation_id TEXT,
                    status TEXT NOT NULL CHECK(status IN ('settled','blocked')),
                    error_code TEXT,
                    journal_transaction_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(schedule_id,due_at)
                );
            """)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _parse_time(value: str | datetime) -> datetime:
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError as exc:
                raise ExpenseScheduleError("start_at must be an ISO-8601 timestamp") from exc
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ExpenseScheduleError("start_at must include an explicit timezone")
        return value.astimezone(timezone.utc)

    def create(self, *, agent_id: str, policy_id: str, destination: str,
               currency: str, amount_minor: int, interval_seconds: int,
               idempotency_key: str, start_at: str | datetime | None = None) -> dict[str, Any]:
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, int) or not 3600 <= interval_seconds <= 31 * 86400:
            raise ExpenseScheduleError("interval_seconds must be between 1 hour and 31 days")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ExpenseScheduleError("idempotency_key is required")
        policy = self.spending._authorized_policy(agent_id, policy_id)
        if currency.upper() != policy["currency"] or destination not in policy["allowed_destinations"]:
            raise ExpenseScheduleError("schedule currency or destination is not authorized by current policy")
        if (isinstance(amount_minor, bool) or not isinstance(amount_minor, int)
                or amount_minor <= 0 or amount_minor > policy["per_transaction_limit_minor"]):
            raise ExpenseScheduleError("schedule amount exceeds the signed per-transaction limit")
        start = self._parse_time(start_at) if start_at is not None else self._now()
        now = self._now()
        terms = {
            "agent_id": agent_id, "policy_id": policy_id, "policy_version": policy["version"],
            "destination": destination, "currency": currency.upper(),
            "amount_minor": amount_minor, "interval_seconds": interval_seconds,
            "start_at": start.isoformat() if start_at is not None else "immediate",
        }
        digest = hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        schedule_id = str(uuid.uuid4())
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT schedule_id,terms_sha256 FROM agent_expense_schedules WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing[1] != digest:
                    db.rollback()
                    raise ExpenseScheduleError("schedule idempotency key reused with changed terms")
                db.commit()
                return self.get(str(existing[0]))
            # Re-read policy while holding the schedule transaction to fail closed on rotation.
            current = self.spending._authorized_policy(agent_id, policy_id)
            if current != policy:
                db.rollback()
                raise ExpenseScheduleError("financial policy changed during schedule creation")
            db.execute(
                """INSERT INTO agent_expense_schedules
                   (schedule_id,idempotency_key,terms_sha256,agent_id,policy_id,policy_version,destination,
                    currency,amount_minor,interval_seconds,next_run_at,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,'active',?,?)""",
                (schedule_id, idempotency_key, digest, agent_id, policy_id, policy["version"], destination,
                 currency.upper(), amount_minor, interval_seconds, start.isoformat(),
                 now.isoformat(), now.isoformat()),
            )
            db.commit()
        return self.get(schedule_id)

    def run_due(self, *, now: str | datetime | None = None, limit: int = 100) -> dict[str, int]:
        """Process at most one due occurrence per schedule; safe for repeated polling."""
        current = self._parse_time(now) if now is not None else self._now()
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ExpenseScheduleError("limit must be between 1 and 1000")
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute(
                """SELECT * FROM agent_expense_schedules
                   WHERE status='active' AND next_run_at<=?
                   ORDER BY next_run_at,schedule_id LIMIT ?""",
                (current.isoformat(), limit),
            ).fetchall()
        counts = {"settled": 0, "blocked": 0, "skipped": 0}
        for schedule in rows:
            result = self._run_one(dict(schedule), current)
            counts[result] += 1
        return counts

    def _run_one(self, schedule: dict[str, Any], now: datetime) -> str:
        due_at = schedule["next_run_at"]
        occurrence_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"aae-expense:{schedule['schedule_id']}:{due_at}"))
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("BEGIN IMMEDIATE")
            current_schedule = db.execute(
                "SELECT status,next_run_at FROM agent_expense_schedules WHERE schedule_id=?",
                (schedule["schedule_id"],),
            ).fetchone()
            if (current_schedule is None or current_schedule[0] != "active"
                    or current_schedule[1] != due_at):
                db.commit()
                return "skipped"
            row = db.execute(
                "SELECT status FROM agent_expense_occurrences WHERE schedule_id=? AND due_at=?",
                (schedule["schedule_id"], due_at),
            ).fetchone()
            if row and row[0] == "settled":
                db.commit()
                return "settled"
            db.execute(
                """INSERT INTO agent_expense_occurrences
                   (occurrence_id,schedule_id,due_at,status,created_at,updated_at)
                   VALUES(?,?,?,'blocked',?,?)
                   ON CONFLICT(schedule_id,due_at) DO NOTHING""",
                (occurrence_id, schedule["schedule_id"], due_at, now.isoformat(), now.isoformat()),
            )
            db.commit()

        reservation = None
        try:
            current_policy = self.spending._authorized_policy(schedule["agent_id"], schedule["policy_id"])
            if current_policy["version"] != schedule["policy_version"]:
                raise FinancialSpendingError("scheduled expense policy was superseded; owner must recreate the schedule")
            reservation = self.spending.reserve(
                agent_id=schedule["agent_id"], policy_id=schedule["policy_id"],
                destination=schedule["destination"], currency=schedule["currency"],
                amount_minor=schedule["amount_minor"],
                idempotency_key=f"scheduled-expense:{occurrence_id}",
                ttl_seconds=3600,
            )
            settled = self.spending.settle(reservation["reservation_id"])
            with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
                db.execute("PRAGMA busy_timeout=10000")
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    """UPDATE agent_expense_occurrences SET status='settled',reservation_id=?,
                       journal_transaction_id=?,error_code=NULL,updated_at=?
                       WHERE schedule_id=? AND due_at=?""",
                    (reservation["reservation_id"], settled["journal_transaction_id"],
                     self._now().isoformat(), schedule["schedule_id"], due_at),
                )
                db.execute(
                    """UPDATE agent_expense_schedules SET next_run_at=?,updated_at=?
                       WHERE schedule_id=? AND status='active' AND next_run_at=?""",
                    ((datetime.fromisoformat(due_at) + timedelta(seconds=schedule["interval_seconds"])).isoformat(),
                     self._now().isoformat(), schedule["schedule_id"], due_at),
                )
                db.commit()
            return "settled"
        except (FinancialSpendingError, ExpenseScheduleError) as exc:
            code = str(exc)[:160]
            with sqlite3.connect(self.path, timeout=10) as db:
                db.execute(
                    """UPDATE agent_expense_occurrences SET status='blocked',error_code=?,updated_at=?
                       WHERE schedule_id=? AND due_at=?""",
                    (code, self._now().isoformat(), schedule["schedule_id"], due_at),
                )
            return "blocked"

    def pause(self, schedule_id: str) -> dict[str, Any]:
        return self._set_status(schedule_id, "paused")

    def resume(self, schedule_id: str) -> dict[str, Any]:
        schedule = self.get(schedule_id)
        if schedule is None:
            raise ExpenseScheduleError("unknown expense schedule")
        self.spending._authorized_policy(schedule["agent_id"], schedule["policy_id"])
        return self._set_status(schedule_id, "active")

    def cancel(self, schedule_id: str) -> dict[str, Any]:
        return self._set_status(schedule_id, "cancelled")

    def _set_status(self, schedule_id: str, status: str) -> dict[str, Any]:
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM agent_expense_schedules WHERE schedule_id=?", (schedule_id,)).fetchone()
            if row is None:
                db.rollback()
                raise ExpenseScheduleError("unknown expense schedule")
            if row[0] == "cancelled" and status != "cancelled":
                db.rollback()
                raise ExpenseScheduleError("cancelled schedules cannot be reactivated")
            db.execute(
                "UPDATE agent_expense_schedules SET status=?,updated_at=? WHERE schedule_id=?",
                (status, self._now().isoformat(), schedule_id),
            )
            db.commit()
        return self.get(schedule_id)

    def list_schedules(self, *, agent_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        """Return schedule metadata only; no private credentials are stored here."""
        if status is not None and status not in {"active", "paused", "cancelled"}:
            raise ExpenseScheduleError("status must be active, paused or cancelled")
        query = "SELECT * FROM agent_expense_schedules"
        clauses: list[str] = []
        params: list[object] = []
        if agent_id is not None:
            if not isinstance(agent_id, str) or not agent_id.strip():
                raise ExpenseScheduleError("agent_id must be non-empty")
            clauses.append("agent_id=?")
            params.append(agent_id)
        if status is not None:
            clauses.append("status=?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at,schedule_id"
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def pause_all(self) -> int:
        """Emergency-stop all active recurring schedules in one local transaction."""
        now = self._now().isoformat()
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "UPDATE agent_expense_schedules SET status='paused',updated_at=? WHERE status='active'",
                (now,),
            )
            changed = int(cursor.rowcount)
            db.commit()
            return changed

    def get(self, schedule_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM agent_expense_schedules WHERE schedule_id=?", (schedule_id,)).fetchone()
        return dict(row) if row else None
