"""Deny-by-default capability grants and authorization decisions."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HIGH_RISK_ACTIONS = {
    "publish", "customer_commitment", "contract_sign", "spend", "custody",
    "transfer", "permission_escalation", "ownership_change", "account_connect",
    "financial_execute", "private_data_export",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CapabilityStore:
    """Local SQLite capability registry; grants are explicit, scoped and revocable."""

    def __init__(self, path: str | Path = "./data/participants.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS capability_grants (
                    grant_id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL,
                    issuer_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    expires_at TEXT,
                    max_amount_minor INTEGER,
                    currency TEXT,
                    status TEXT NOT NULL CHECK(status IN ('active','revoked')),
                    created_at TEXT NOT NULL,
                    delegation_parent TEXT,
                    metadata_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_capability_subject
                    ON capability_grants(subject_id, status);
                CREATE TABLE IF NOT EXISTS authorization_audit (
                    event_id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    grant_id TEXT,
                    policy_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    context_json TEXT NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def grant(self, subject_id: str, issuer_id: str, action: str, resource: str,
              *, expires_at: str | None = None, max_amount_minor: int | None = None,
              currency: str | None = None, delegation_parent: str | None = None,
              metadata: dict[str, Any] | None = None) -> str:
        if not all(v.strip() for v in (subject_id, issuer_id, action, resource)):
            raise ValueError("subject_id, issuer_id, action and resource are required")
        if max_amount_minor is not None and max_amount_minor < 0:
            raise ValueError("max_amount_minor must be non-negative")
        grant_id = "grant_" + uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                """INSERT INTO capability_grants VALUES(?,?,?,?,?,?,?,?,'active',?,?,?)""",
                (grant_id, subject_id, issuer_id, action, resource, expires_at,
                 max_amount_minor, currency.upper() if currency else None, _now(),
                 delegation_parent, json.dumps(metadata or {}, sort_keys=True)),
            )
        return grant_id

    def revoke(self, grant_id: str, issuer_id: str) -> None:
        with self._connect() as db:
            cur = db.execute(
                "UPDATE capability_grants SET status='revoked' WHERE grant_id=? AND issuer_id=? AND status='active'",
                (grant_id, issuer_id),
            )
            if cur.rowcount != 1:
                raise ValueError("active grant not found or issuer is not authorized")

    def authorize(self, subject_id: str, action: str, resource: str, *,
                  amount_minor: int | None = None, currency: str | None = None,
                  approval_ref: str | None = None,
                  context: dict[str, Any] | None = None) -> dict[str, str]:
        """Return allow/deny/require_approval and persist every decision.

        High-risk actions always require an approval reference in addition to a
        matching capability. This prototype does not itself validate the approval
        reference; production must bind it to a signed, single-use approval service.
        """
        decision, reason, grant_id = "deny", "no matching active capability", None
        with self._connect() as db:
            rows = db.execute(
                """SELECT * FROM capability_grants WHERE subject_id=? AND action=?
                AND status='active' AND (resource=? OR resource='*')""",
                (subject_id, action, resource),
            ).fetchall()
            now = datetime.now(timezone.utc)
            for row in rows:
                if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= now:
                    continue
                if amount_minor is not None:
                    if row["max_amount_minor"] is None or amount_minor > row["max_amount_minor"]:
                        continue
                    if row["currency"] and row["currency"] != (currency or "").upper():
                        continue
                grant_id = row["grant_id"]
                if action in HIGH_RISK_ACTIONS and not approval_ref:
                    decision, reason = "require_approval", "high-risk action requires separate authorized approval"
                else:
                    decision, reason = "allow", "matching active scoped capability"
                break
            db.execute(
                """INSERT INTO authorization_audit VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ("authz_" + uuid.uuid4().hex, subject_id, action, resource, decision,
                 reason, grant_id, "1.0", _now(), json.dumps(context or {}, sort_keys=True)),
            )
        return {"decision": decision, "reason": reason, "grant_id": grant_id or ""}

    def audit(self, subject_id: str | None = None) -> list[dict[str, Any]]:
        sql, params = "SELECT * FROM authorization_audit", []
        if subject_id:
            sql += " WHERE subject_id=?"
            params.append(subject_id)
        sql += " ORDER BY created_at"
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]
