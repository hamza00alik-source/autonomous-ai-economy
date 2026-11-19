"""Owner-gated fulfillment lifecycle for external paid work.

This is a local orchestration ledger, not a marketplace executor. External
claims, submissions, delivery, and payment reconciliation require injected
verifiers and are never performed by this module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Callable


STATES = (
    "discovered", "owner_approved", "in_progress", "qa",
    "delivery_ready", "submission_approved", "accepted",
    "payment_pending", "reconciled", "rejected", "cancelled",
)
TRANSITIONS = {
    "discovered": {"owner_approved", "rejected", "cancelled"},
    "owner_approved": {"in_progress", "cancelled"},
    "in_progress": {"qa", "cancelled"},
    "qa": {"in_progress", "delivery_ready", "cancelled"},
    "delivery_ready": {"submission_approved", "in_progress", "cancelled"},
    "submission_approved": {"accepted", "delivery_ready", "cancelled"},
    "accepted": {"payment_pending"},
    "payment_pending": {"reconciled"},
    "reconciled": set(), "rejected": set(), "cancelled": set(),
}
FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class FulfillmentError(ValueError):
    """Raised when a lifecycle transition fails a safety invariant."""


@dataclass(frozen=True)
class FulfillmentJob:
    job_id: str
    source: str
    external_id: str
    agent_id: str
    agent_key_fingerprint: str
    state: str
    payload: dict[str, Any]
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class FulfillmentStore:
    """SQLite state machine with immutable audit events and idempotent commands."""

    def __init__(
        self,
        path: str | Path = "./data/fulfillment.sqlite3",
        *,
        identity_verifier: Callable[[str, str], bool] | None = None,
        owner_approval_verifier: Callable[[str, str, str], bool] | None = None,
        settlement_verifier: Callable[[str, str], dict[str, Any] | None] | None = None,
    ):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.identity_verifier = identity_verifier
        self.owner_approval_verifier = owner_approval_verifier
        self.settlement_verifier = settlement_verifier
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS fulfillment_jobs (
                    job_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_key_fingerprint TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(source, external_id)
                );
                CREATE TABLE IF NOT EXISTS fulfillment_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    from_state TEXT,
                    to_state TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    evidence_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(job_id) REFERENCES fulfillment_jobs(job_id)
                );
            """)

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def create_job(
        self, *, source: str, external_id: str, agent_id: str,
        agent_key_fingerprint: str, payload: dict[str, Any],
        idempotency_key: str,
    ) -> FulfillmentJob:
        if not all(isinstance(v, str) and v.strip() for v in
                   (source, external_id, agent_id, idempotency_key)):
            raise FulfillmentError("source, external ID, agent ID and idempotency key are required")
        if not isinstance(payload, dict):
            raise FulfillmentError("job payload must be an object")
        if not FINGERPRINT.fullmatch(agent_key_fingerprint or ""):
            raise FulfillmentError("a canonical SHA-256 agent key fingerprint is required")
        if self.identity_verifier is None or not self.identity_verifier(agent_id, agent_key_fingerprint):
            raise FulfillmentError("agent identity is not cryptographically verified")
        now = self._now()
        job_id = hashlib.sha256(f"{source}\n{external_id}".encode()).hexdigest()
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM fulfillment_jobs WHERE source=? AND external_id=?",
                                   (source, external_id)).fetchone()
            if existing:
                db.execute("COMMIT")
                return self._row(existing)
            db.execute("""INSERT INTO fulfillment_jobs
                (job_id,source,external_id,agent_id,agent_key_fingerprint,state,payload_json,created_at,updated_at)
                VALUES(?,?,?,?,?,'discovered',?,?,?)""",
                (job_id, source, external_id, agent_id, agent_key_fingerprint, encoded, now, now))
            db.execute("""INSERT INTO fulfillment_events
                (job_id,from_state,to_state,actor,idempotency_key,evidence_json,created_at)
                VALUES(?,NULL,'discovered','system',?,?,?)""",
                (job_id, "create:" + idempotency_key, "{}", now))
            row = db.execute("SELECT * FROM fulfillment_jobs WHERE job_id=?", (job_id,)).fetchone()
            db.execute("COMMIT")
        return self._row(row)

    @staticmethod
    def _row(row: sqlite3.Row) -> FulfillmentJob:
        return FulfillmentJob(
            job_id=row["job_id"], source=row["source"], external_id=row["external_id"],
            agent_id=row["agent_id"], agent_key_fingerprint=row["agent_key_fingerprint"],
            state=row["state"], payload=json.loads(row["payload_json"]),
            created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def get(self, job_id: str) -> FulfillmentJob | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM fulfillment_jobs WHERE job_id=?", (job_id,)).fetchone()
        return self._row(row) if row else None

    def transition(
        self, job_id: str, target: str, *, actor: str,
        idempotency_key: str, evidence: dict[str, Any] | None = None,
        owner_approval: str | None = None,
    ) -> FulfillmentJob:
        if target not in STATES or not actor or not idempotency_key:
            raise FulfillmentError("valid target state, actor and idempotency key are required")
        evidence = evidence or {}
        if not isinstance(evidence, dict):
            raise FulfillmentError("evidence must be an object")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT job_id FROM fulfillment_events WHERE idempotency_key=?",
                               (idempotency_key,)).fetchone()
            if prior:
                row = db.execute("SELECT * FROM fulfillment_jobs WHERE job_id=?", (prior["job_id"],)).fetchone()
                db.execute("COMMIT")
                if not row or row["job_id"] != job_id:
                    raise FulfillmentError("idempotency key was already used for another job")
                return self._row(row)
            row = db.execute("SELECT * FROM fulfillment_jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                db.execute("ROLLBACK")
                raise FulfillmentError("unknown fulfillment job")
            current = row["state"]
            if target not in TRANSITIONS[current]:
                db.execute("ROLLBACK")
                raise FulfillmentError(f"transition {current} -> {target} is not allowed")
            if target in {"owner_approved", "submission_approved"}:
                if (not owner_approval or self.owner_approval_verifier is None or
                    not self.owner_approval_verifier(owner_approval, job_id, target)):
                    db.execute("ROLLBACK")
                    raise FulfillmentError("valid owner approval evidence is required")
            now = self._now()
            db.execute("UPDATE fulfillment_jobs SET state=?,updated_at=? WHERE job_id=? AND state=?",
                       (target, now, job_id, current))
            db.execute("""INSERT INTO fulfillment_events
                (job_id,from_state,to_state,actor,idempotency_key,evidence_json,created_at)
                VALUES(?,?,?,?,?,?,?)""",
                (job_id, current, target, actor, idempotency_key,
                 json.dumps(evidence, sort_keys=True, separators=(",", ":")), now))
            updated = db.execute("SELECT * FROM fulfillment_jobs WHERE job_id=?", (job_id,)).fetchone()
            db.execute("COMMIT")
        return self._row(updated)

    def reconcile(self, job_id: str, *, idempotency_key: str) -> FulfillmentJob:
        job = self.get(job_id)
        if not job or job.state != "payment_pending":
            raise FulfillmentError("only accepted work in payment_pending can be reconciled")
        if self.settlement_verifier is None:
            raise FulfillmentError("independent settlement verifier is not configured")
        proof = self.settlement_verifier(job.source, job.external_id)
        if not isinstance(proof, dict) or proof.get("verified") is not True:
            raise FulfillmentError("provider/on-chain settlement was not independently verified")
        amount = proof.get("net_amount")
        currency = proof.get("currency")
        reference = proof.get("settlement_reference")
        if not all(isinstance(v, str) and v.strip() for v in (amount, currency, reference)):
            raise FulfillmentError("verified settlement must include net amount, currency and reference")
        return self.transition(
            job_id, "reconciled", actor="settlement-verifier",
            idempotency_key=idempotency_key,
            evidence={"net_amount": amount, "currency": currency,
                      "settlement_reference": reference, "verified": True},
        )

    def events(self, job_id: str) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM fulfillment_events WHERE job_id=? ORDER BY event_id",
                              (job_id,)).fetchall()
        return [{**dict(row), "evidence": json.loads(row["evidence_json"])} for row in rows]
