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
        if (max_amount_minor is None) != (currency is None):
            raise ValueError("amount ceiling and currency must be supplied together")
        if currency and (len(currency) != 3 or not currency.isalpha()):
            raise ValueError("currency must be a three-letter code")
        if expires_at:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                raise ValueError("expires_at must be a future timezone-aware timestamp")
        grant_id = "grant_" + uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                """INSERT INTO capability_grants VALUES(?,?,?,?,?,?,?,?,'active',?,?,?)""",
                (grant_id, subject_id, issuer_id, action, resource, expires_at,
                 max_amount_minor, currency.upper() if currency else None, _now(),
                 delegation_parent, json.dumps(metadata or {}, sort_keys=True)),
            )
        return grant_id

    @staticmethod
    def grant_payload(subject_id: str, issuer_id: str, action: str, resource: str, *,
                      expires_at: str | None = None,
                      max_amount_minor: int | None = None,
                      currency: str | None = None) -> bytes:
        """Canonical bytes an owner signs to authorize one exact capability grant."""
        payload = {
            "version": 1, "subject_id": subject_id, "issuer_id": issuer_id,
            "action": action, "resource": resource, "expires_at": expires_at,
            "max_amount_minor": max_amount_minor,
            "currency": currency.upper() if currency else None,
        }
        return ("AAE-CAPABILITY-GRANT-V1:" +
                json.dumps(payload, sort_keys=True, separators=(",", ":"))).encode("utf-8")

    def grant_signed(self, subject_id: str, issuer_id: str, action: str, resource: str,
                     signature: str, *, expires_at: str | None = None,
                     max_amount_minor: int | None = None, currency: str | None = None,
                     verifier=None) -> str:
        """Create a grant only with a signature from an active, key-bound human/org issuer.

        The signature binds the exact grant fields. Agent identities cannot issue
        owner grants. This authenticates key possession, not legal identity.
        """
        from .identity import verify_ed25519
        verify = verifier or verify_ed25519
        if not all(isinstance(v, str) and v.strip()
                   for v in (subject_id, issuer_id, action, resource, signature)):
            raise ValueError("grant fields and issuer signature are required")
        if max_amount_minor is not None and max_amount_minor < 0:
            raise ValueError("max_amount_minor must be non-negative")
        if (max_amount_minor is None) != (currency is None):
            raise ValueError("amount ceiling and currency must be supplied together")
        if currency and (len(currency) != 3 or not currency.isalpha()):
            raise ValueError("currency must be a three-letter code")
        if expires_at:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
                raise ValueError("expires_at must be a future timezone-aware timestamp")
        message = self.grant_payload(
            subject_id, issuer_id, action, resource, expires_at=expires_at,
            max_amount_minor=max_amount_minor, currency=currency,
        )
        with self._connect() as db:
            issuer = db.execute(
                """SELECT participant_type, status, public_key FROM participants
                   WHERE participant_id=?""", (issuer_id,)
            ).fetchone()
            if (issuer is None or issuer["status"] != "active"
                    or issuer["participant_type"] not in {"human", "organization"}
                    or not issuer["public_key"]):
                raise ValueError("issuer must be an active key-bound human or organization")
            if not verify(issuer["public_key"], message, signature):
                raise ValueError("issuer signature is invalid")
            subject = db.execute(
                "SELECT status FROM participants WHERE participant_id=?", (subject_id,)
            ).fetchone()
            if subject is None or subject["status"] != "active":
                raise ValueError("subject must be an active registered participant")
            grant_id = "grant_" + uuid.uuid4().hex
            db.execute(
                """INSERT INTO capability_grants VALUES(?,?,?,?,?,?,?,?,'active',?,?,?)""",
                (grant_id, subject_id, issuer_id, action, resource, expires_at,
                 max_amount_minor, currency.upper() if currency else None, _now(),
                 None, "{}"),
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

        High-risk actions always return require_approval, even if a reference string
        is supplied. This prototype has no approval-token verifier wired into this
        policy engine; a caller must not treat an unverified reference as authority.
        """
        decision, reason, grant_id = "deny", "no matching active capability", None
        with self._connect() as db:
            if amount_minor is not None and amount_minor < 0:
                reason = "amount must be non-negative"
                rows = []
            else:
                participant_table = db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='participants'"
                ).fetchone()
                participant = (db.execute(
                    "SELECT status FROM participants WHERE participant_id=?", (subject_id,)
                ).fetchone() if participant_table else None)
                if participant_table is None:
                    reason = "participant registry is unavailable"
                    rows = []
                elif participant is None or participant["status"] != "active":
                    reason = "subject participant is missing or inactive"
                    rows = []
                else:
                    rows = db.execute(
                        """SELECT * FROM capability_grants WHERE subject_id=? AND action=?
                        AND status='active' AND (resource=? OR resource='*')""",
                        (subject_id, action, resource),
                    ).fetchall()
            now = datetime.now(timezone.utc)
            for row in rows:
                if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= now:
                    continue
                if row["max_amount_minor"] is not None and amount_minor is None:
                    continue
                if amount_minor is not None:
                    if row["max_amount_minor"] is None or amount_minor > row["max_amount_minor"]:
                        continue
                    if row["currency"] and row["currency"] != (currency or "").upper():
                        continue
                grant_id = row["grant_id"]
                if action in HIGH_RISK_ACTIONS:
                    decision, reason = "require_approval", "high-risk action requires a separately verified approval; this prototype cannot validate approval references"
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
