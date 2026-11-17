"""Signed work receipts, acceptance, disputes and evidence-derived reputation."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .delegation import _canonical
from .identity import verify_ed25519


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkRecordStore:
    """Local evidence ledger. Reputation is derived only from verified outcomes."""

    def __init__(self, path: str | Path = "./data/participants.sqlite3", *,
                 adjudicators: dict[str, str] | None = None,
                 verifier: Callable[[str, bytes, str], bool] = verify_ed25519) -> None:
        self.path = str(path)
        self.adjudicators = dict(adjudicators or {})
        self.verifier = verifier
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS work_receipts (
                    receipt_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL UNIQUE,
                    provider_id TEXT NOT NULL,
                    buyer_id TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    submitted_payload TEXT NOT NULL,
                    provider_signature TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('submitted','accepted','disputed','resolved')),
                    buyer_signature TEXT,
                    outcome TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS work_disputes (
                    dispute_id TEXT PRIMARY KEY,
                    receipt_id TEXT NOT NULL,
                    opened_by TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('open','resolved')),
                    resolution TEXT,
                    resolver_id TEXT,
                    resolution_signature TEXT,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_work_provider ON work_receipts(provider_id,status);
                CREATE INDEX IF NOT EXISTS idx_dispute_receipt ON work_disputes(receipt_id,status);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_dispute_per_receipt
                    ON work_disputes(receipt_id) WHERE status='open';
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _participant_key(self, db: sqlite3.Connection, participant_id: str) -> str:
        row = db.execute(
            "SELECT public_key,status FROM participants WHERE participant_id=?",
            (participant_id,),
        ).fetchone()
        if row is None or row["status"] != "active" or not row["public_key"]:
            raise ValueError("participant must be active and have a registered signing key")
        return row["public_key"]

    @staticmethod
    def _validate_evidence_refs(evidence_refs: list[str]) -> list[str]:
        """Validate stable evidence pointers; artifact pointers must be content-addressed.

        This validates reference syntax only. It does not fetch, retain, or attest to
        the bytes behind a reference.
        """
        import re
        if not isinstance(evidence_refs, list) or not evidence_refs:
            raise ValueError("at least one evidence reference is required")
        if any(not isinstance(ref, str) or not ref or len(ref) > 2048
               or ref.strip() != ref for ref in evidence_refs):
            raise ValueError("evidence references must be non-empty, trimmed strings up to 2048 chars")
        refs = sorted(set(evidence_refs))
        for ref in refs:
            if ref.startswith("artifact:"):
                if not re.fullmatch(r"artifact:sha256:[0-9a-f]{64}", ref):
                    raise ValueError("artifact references must use artifact:sha256:<64 lowercase hex chars>")
            elif ref.startswith("https://"):
                from urllib.parse import urlsplit
                parsed = urlsplit(ref)
                if not parsed.hostname or parsed.username or parsed.password:
                    raise ValueError("https evidence references must include a host and no embedded credentials")
            elif ref.startswith("task:"):
                if len(ref) <= len("task:") or any(ch.isspace() for ch in ref):
                    raise ValueError("task evidence references must include a whitespace-free task identifier")
            else:
                raise ValueError("evidence references must use https, task:, or content-addressed artifact:sha256:")
        return refs

    @staticmethod
    def submission_payload(*, task_id: str, provider_id: str, buyer_id: str,
                           summary: str, evidence_refs: list[str]) -> dict[str, Any]:
        return {"version": "1", "event": "work_submitted", "task_id": task_id,
                "provider_id": provider_id, "buyer_id": buyer_id,
                "summary": summary, "evidence_refs": sorted(set(evidence_refs))}

    @staticmethod
    def submission_signing_bytes(*, task_id: str, provider_id: str, buyer_id: str,
                                 summary: str, evidence_refs: list[str]) -> bytes:
        payload = WorkRecordStore.submission_payload(
            task_id=task_id, provider_id=provider_id, buyer_id=buyer_id,
            summary=summary, evidence_refs=evidence_refs,
        )
        return _canonical(payload)

    @staticmethod
    def acceptance_payload(receipt_id: str, buyer_id: str, provider_id: str,
                           task_id: str, agreement_digest: str,
                           artifact_digests: list[str]) -> bytes:
        """Bind buyer acceptance to the exact accepted agreement and submitted artifacts."""
        return _canonical({"version": "2", "event": "work_accepted",
                           "receipt_id": receipt_id, "task_id": task_id,
                           "agreement_id": task_id, "agreement_digest": agreement_digest,
                           "buyer_id": buyer_id, "provider_id": provider_id,
                           "artifact_digests": sorted(set(artifact_digests))})

    @staticmethod
    def dispute_payload(receipt_id: str, dispute_id: str, actor_id: str,
                        reason: str, evidence_refs: list[str]) -> bytes:
        return _canonical({"version": "1", "event": "work_disputed",
                           "receipt_id": receipt_id, "dispute_id": dispute_id,
                           "actor_id": actor_id, "reason": reason,
                           "evidence_refs": sorted(set(evidence_refs))})

    @staticmethod
    def resolution_payload(dispute_id: str, resolver_id: str, outcome: str,
                           note: str) -> bytes:
        return _canonical({"version": "1", "event": "dispute_resolved",
                           "dispute_id": dispute_id, "resolver_id": resolver_id,
                           "outcome": outcome, "note": note})

    def submit(self, *, task_id: str, provider_id: str, buyer_id: str,
               summary: str, evidence_refs: list[str], signature: str) -> dict[str, Any]:
        if not all(v.strip() for v in (task_id, provider_id, buyer_id, summary, signature)):
            raise ValueError("task, parties, summary and signature are required")
        if provider_id == buyer_id:
            raise ValueError("provider and buyer must be different participants")
        refs = self._validate_evidence_refs(evidence_refs)
        payload = self.submission_payload(task_id=task_id, provider_id=provider_id,
                                           buyer_id=buyer_id, summary=summary,
                                           evidence_refs=refs)
        with self._connect() as db:
            agreement_table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='task_agreements'"
            ).fetchone()
            if agreement_table is None:
                raise ValueError("task agreement store is unavailable; refusing an unlinked work receipt")
            agreement = db.execute(
                "SELECT buyer_id,provider_id,status FROM task_agreements WHERE task_id=?",
                (task_id,),
            ).fetchone()
            if (agreement is None or agreement["status"] != "accepted"
                    or agreement["buyer_id"] != buyer_id
                    or agreement["provider_id"] != provider_id):
                raise ValueError("work receipt must match an accepted task agreement")
            key = self._participant_key(db, provider_id)
            self._participant_key(db, buyer_id)
            if not self.verifier(key, _canonical(payload), signature):
                raise ValueError("provider work receipt signature is invalid")
            receipt_id = "receipt_" + uuid.uuid4().hex
            now = _now()
            db.execute(
                """INSERT INTO work_receipts VALUES(?,?,?,?,?,?,?,?,'submitted',NULL,NULL,?,?)""",
                (receipt_id, task_id, provider_id, buyer_id, summary,
                 json.dumps(refs), json.dumps(payload, sort_keys=True), signature, now, now),
            )
            return self.get_receipt(receipt_id)

    def accept(self, receipt_id: str, *, buyer_id: str, signature: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM work_receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
            if row is None or row["buyer_id"] != buyer_id or row["status"] != "submitted":
                raise ValueError("submitted receipt not found or buyer is not authorized")
            agreement = db.execute(
                "SELECT buyer_id,provider_id,status,offer_payload FROM task_agreements WHERE task_id=?",
                (row["task_id"],),
            ).fetchone()
            if (agreement is None or agreement["status"] != "accepted"
                    or agreement["buyer_id"] != buyer_id
                    or agreement["provider_id"] != row["provider_id"]):
                raise ValueError("buyer acceptance requires the matching accepted task agreement")
            agreement_digest = hashlib.sha256(
                _canonical(json.loads(agreement["offer_payload"]))
            ).hexdigest()
            evidence_refs = json.loads(row["evidence_json"])
            artifact_digests = [
                ref.removeprefix("artifact:sha256:")
                for ref in evidence_refs if ref.startswith("artifact:sha256:")
            ]
            key = self._participant_key(db, buyer_id)
            payload = self.acceptance_payload(
                receipt_id, buyer_id, row["provider_id"], row["task_id"],
                agreement_digest, artifact_digests,
            )
            if not self.verifier(key, payload, signature):
                raise ValueError("buyer acceptance signature is invalid")
            updated = db.execute(
                "UPDATE work_receipts SET status='accepted',buyer_signature=?,outcome='accepted',updated_at=? WHERE receipt_id=? AND status='submitted'",
                (signature, _now(), receipt_id),
            )
            if updated.rowcount != 1:
                raise ValueError("work receipt state changed before acceptance completed")
        return self.get_receipt(receipt_id)

    def open_dispute(self, receipt_id: str, *, actor_id: str, reason: str,
                     evidence_refs: list[str], signature: str) -> dict[str, Any]:
        if not reason.strip() or not evidence_refs:
            raise ValueError("a dispute reason and evidence references are required")
        with self._connect() as db:
            row = db.execute("SELECT * FROM work_receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
            if row is None or actor_id not in {row["provider_id"], row["buyer_id"]}:
                raise ValueError("only a work participant may dispute this receipt")
            if db.execute("SELECT 1 FROM work_disputes WHERE receipt_id=? AND status='open'",
                          (receipt_id,)).fetchone():
                raise ValueError("this receipt already has an open dispute")
            if row["status"] not in {"submitted", "accepted"}:
                raise ValueError("receipt cannot be disputed in its current state")
            key = self._participant_key(db, actor_id)
            dispute_id = "dispute_" + uuid.uuid4().hex
            refs = self._validate_evidence_refs(evidence_refs)
            payload = self.dispute_payload(receipt_id, dispute_id, actor_id, reason, refs)
            if not self.verifier(key, payload, signature):
                raise ValueError("dispute signature is invalid")
            now = _now()
            db.execute(
                """INSERT INTO work_disputes VALUES(?,?,?,?,?,'open',NULL,NULL,NULL,?,NULL)""",
                (dispute_id, receipt_id, actor_id, reason, json.dumps(refs), now),
            )
            db.execute("UPDATE work_receipts SET status='disputed',updated_at=? WHERE receipt_id=?",
                       (now, receipt_id))
            return dict(db.execute("SELECT * FROM work_disputes WHERE dispute_id=?",
                                   (dispute_id,)).fetchone())

    def resolve_dispute(self, dispute_id: str, *, resolver_id: str,
                        outcome: str, note: str, signature: str) -> dict[str, Any]:
        if outcome not in {"provider_favor", "buyer_favor", "no_fault"} or not note.strip():
            raise ValueError("resolution outcome and note are required")
        key = self.adjudicators.get(resolver_id)
        if not key:
            raise ValueError("resolver is not in the trusted adjudicator set")
        payload = self.resolution_payload(dispute_id, resolver_id, outcome, note)
        if not self.verifier(key, payload, signature):
            raise ValueError("adjudicator resolution signature is invalid")
        with self._connect() as db:
            dispute = db.execute("SELECT * FROM work_disputes WHERE dispute_id=?", (dispute_id,)).fetchone()
            if dispute is None or dispute["status"] != "open":
                raise ValueError("open dispute not found")
            receipt = db.execute("SELECT * FROM work_receipts WHERE receipt_id=?",
                                 (dispute["receipt_id"],)).fetchone()
            now = _now()
            updated = db.execute(
                """UPDATE work_disputes SET status='resolved',resolution=?,resolver_id=?,
                resolution_signature=?,resolved_at=? WHERE dispute_id=? AND status='open'""",
                (outcome, resolver_id, signature, now, dispute_id),
            )
            if updated.rowcount != 1:
                raise ValueError("dispute state changed before resolution completed")
            # A resolution is not silently converted into buyer acceptance.
            final_status = "resolved"
            db.execute(
                "UPDATE work_receipts SET status=?,outcome=?,updated_at=? WHERE receipt_id=?",
                (final_status, outcome, now, receipt["receipt_id"]),
            )
            return dict(db.execute("SELECT * FROM work_disputes WHERE dispute_id=?",
                                   (dispute_id,)).fetchone())

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM work_receipts WHERE receipt_id=?", (receipt_id,)).fetchone()
            if row is None:
                raise KeyError(receipt_id)
            result = dict(row)
            result["evidence_refs"] = json.loads(result.pop("evidence_json"))
            result["submitted_payload"] = json.loads(result["submitted_payload"])
            return result

    def disputes(self, receipt_id: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM work_disputes", []
        if receipt_id:
            sql += " WHERE receipt_id=?"
            params.append(receipt_id)
        sql += " ORDER BY created_at"
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def reputation(self, provider_id: str) -> dict[str, int]:
        """Conservative counts, not a star rating or proof of quality."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT status,outcome FROM work_receipts WHERE provider_id=?", (provider_id,)
            ).fetchall()
        accepted = sum(row["status"] == "accepted" for row in rows)
        disputed = sum(row["status"] == "disputed" for row in rows)
        resolved_provider = sum(row["status"] == "resolved" and row["outcome"] == "provider_favor" for row in rows)
        resolved_buyer = sum(row["status"] == "resolved" and row["outcome"] == "buyer_favor" for row in rows)
        resolved_no_fault = sum(row["status"] == "resolved" and row["outcome"] == "no_fault" for row in rows)
        pending = sum(row["status"] == "submitted" for row in rows)
        return {"accepted": accepted, "pending": pending, "disputed": disputed,
                "resolved_provider_favor": resolved_provider,
                "resolved_buyer_favor": resolved_buyer,
                "resolved_no_fault": resolved_no_fault, "total_receipts": len(rows)}
