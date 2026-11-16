"""Cryptographically verifiable, bounded participant-to-agent delegation.

Root delegations require an explicitly configured trusted owner public key.
Child delegations must be signed by the current delegate and may only narrow
their parent's authority. This is a local prototype, not remote authentication.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .identity import verify_ed25519
from .permissions import HIGH_RISK_ACTIONS

POLICY_VERSION = "1"
MAX_DELEGATION_DEPTH = 5


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def _scope_allows(parent: str, child: str) -> bool:
    return parent == "*" or parent == child


class DelegationStore:
    """Stores signed delegations; root authority is pinned out-of-band by the owner."""

    def __init__(self, path: str | Path = "./data/participants.sqlite3", *,
                 trusted_roots: dict[str, str] | None = None,
                 verifier: Callable[[str, bytes, str], bool] = verify_ed25519,
                 max_depth: int = MAX_DELEGATION_DEPTH) -> None:
        if not 1 <= max_depth <= 10:
            raise ValueError("max_depth must be between 1 and 10")
        self.path = str(path)
        self.trusted_roots = dict(trusted_roots or {})
        self.verifier = verifier
        self.max_depth = max_depth
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS signed_delegations (
                    delegation_id TEXT PRIMARY KEY,
                    delegator_id TEXT NOT NULL,
                    delegate_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    max_amount_minor INTEGER,
                    currency TEXT,
                    parent_id TEXT,
                    depth INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','revoked')),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_delegation_delegate
                    ON signed_delegations(delegate_id, status);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(signed_delegations)")}
            if "signer_public_key" not in columns:
                db.execute("ALTER TABLE signed_delegations ADD COLUMN signer_public_key TEXT")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _key_for(self, db: sqlite3.Connection, participant_id: str) -> str:
        row = db.execute(
            "SELECT public_key,status FROM participants WHERE participant_id=?",
            (participant_id,),
        ).fetchone()
        if row is None or row["status"] != "active":
            raise ValueError("delegator must be an active registered participant")
        if participant_id in self.trusted_roots:
            trusted_key = self.trusted_roots[participant_id]
            if row["public_key"] and row["public_key"] != trusted_key:
                raise ValueError("trusted root key configuration must match the participant's current key")
            return trusted_key
        if not row["public_key"]:
            raise ValueError("delegator has no registered signing key")
        return row["public_key"]

    @staticmethod
    def signing_payload(*, delegation_id: str, delegator_id: str, delegate_id: str,
                        action: str, resource: str, expires_at: str,
                        max_amount_minor: int | None = None, currency: str | None = None,
                        parent_id: str | None = None, depth: int = 0) -> dict[str, Any]:
        return {
            "policy_version": POLICY_VERSION,
            "delegation_id": delegation_id,
            "delegator_id": delegator_id,
            "delegate_id": delegate_id,
            "action": action,
            "resource": resource,
            "expires_at": expires_at,
            "max_amount_minor": max_amount_minor,
            "currency": currency.upper() if currency else None,
            "parent_id": parent_id,
            "depth": depth,
        }

    def create(self, *, delegation_id: str, delegator_id: str, delegate_id: str,
               action: str, resource: str, expires_at: str, signature: str,
               parent_id: str | None = None, max_amount_minor: int | None = None,
               currency: str | None = None) -> dict[str, Any]:
        if not all(v.strip() for v in (delegation_id, delegator_id, delegate_id, action, resource, signature)):
            raise ValueError("delegation identifiers, scope and signature are required")
        if max_amount_minor is not None and max_amount_minor < 0:
            raise ValueError("max_amount_minor must be non-negative")
        expiry = _time(expires_at)
        if expiry <= _now():
            raise ValueError("delegation expiry must be in the future")
        if (max_amount_minor is None) != (currency is None):
            raise ValueError("amount ceiling and currency must be supplied together")
        currency_value = currency.upper() if currency else None

        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                delegator_key = self._key_for(db, delegator_id)
                delegate = db.execute(
                    "SELECT participant_type,status FROM participants WHERE participant_id=?",
                    (delegate_id,),
                ).fetchone()
                if delegate is None or delegate["status"] != "active" or delegate["participant_type"] != "agent":
                    raise ValueError("delegate must be an active registered agent")
                depth = 0
                parent = None
                if parent_id:
                    parent = db.execute(
                        "SELECT * FROM signed_delegations WHERE delegation_id=?",
                        (parent_id,),
                    ).fetchone()
                    if parent is None:
                        raise ValueError("parent delegation does not exist")
                    if parent["delegate_id"] != delegator_id:
                        raise ValueError("delegator is not the parent delegation's delegate")
                    if not self._is_chain_active(db, parent, set()):
                        raise ValueError("parent delegation chain is inactive or revoked")
                    if not _scope_allows(parent["action"], action) or not _scope_allows(parent["resource"], resource):
                        raise ValueError("child scope exceeds parent delegation")
                    if _time(parent["expires_at"]) < expiry:
                        raise ValueError("child delegation cannot outlive its parent")
                    if parent["max_amount_minor"] is not None:
                        if max_amount_minor is None or max_amount_minor > parent["max_amount_minor"]:
                            raise ValueError("child amount ceiling exceeds parent or is unbounded")
                        if currency_value != parent["currency"]:
                            raise ValueError("child currency must match parent")
                    depth = parent["depth"] + 1
                else:
                    if self.trusted_roots.get(delegator_id) != delegator_key:
                        raise ValueError("root delegation must be signed by an explicitly trusted owner key")
                if depth >= self.max_depth:
                    raise ValueError("maximum delegation depth reached")
                payload = self.signing_payload(
                    delegation_id=delegation_id, delegator_id=delegator_id,
                    delegate_id=delegate_id, action=action, resource=resource,
                    expires_at=expiry.isoformat(), max_amount_minor=max_amount_minor,
                    currency=currency_value, parent_id=parent_id, depth=depth,
                )
                if not self.verifier(delegator_key, _canonical(payload), signature):
                    raise ValueError("delegation signature is invalid")
                db.execute(
                    """INSERT INTO signed_delegations
                    (delegation_id,delegator_id,delegate_id,action,resource,expires_at,
                     max_amount_minor,currency,parent_id,depth,payload_json,signature,
                     status,created_at,signer_public_key)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'active',?,?)""",
                    (delegation_id, delegator_id, delegate_id, action, resource,
                     expiry.isoformat(), max_amount_minor, currency_value, parent_id,
                     depth, json.dumps(payload, sort_keys=True), signature,
                     _now().isoformat(), delegator_key),
                )
                db.commit()
                return {**payload, "signature": signature, "status": "active"}
            except Exception:
                db.rollback()
                raise

    def _is_chain_active(self, db: sqlite3.Connection, row: sqlite3.Row,
                         visited: set[str]) -> bool:
        delegation_id = row["delegation_id"]
        if delegation_id in visited or row["status"] != "active":
            return False
        visited.add(delegation_id)
        if _time(row["expires_at"]) <= _now():
            return False
        for participant_id in (row["delegator_id"], row["delegate_id"]):
            participant = db.execute(
                "SELECT status,public_key FROM participants WHERE participant_id=?", (participant_id,)
            ).fetchone()
            if participant is None or participant["status"] != "active":
                return False
        signer = db.execute(
            "SELECT public_key FROM participants WHERE participant_id=?",
            (row["delegator_id"],),
        ).fetchone()
        expected_signer_key = (self.trusted_roots.get(row["delegator_id"])
                               if not row["parent_id"] else
                               (signer["public_key"] if signer else None))
        if (not row["signer_public_key"] or not expected_signer_key
                or row["signer_public_key"] != expected_signer_key):
            return False
        if signer and signer["public_key"] and signer["public_key"] != expected_signer_key:
            return False
        if row["parent_id"]:
            parent = db.execute(
                "SELECT * FROM signed_delegations WHERE delegation_id=?", (row["parent_id"],)
            ).fetchone()
            return bool(parent and parent["delegate_id"] == row["delegator_id"]
                        and self._is_chain_active(db, parent, visited))
        return row["delegator_id"] in self.trusted_roots

    def authorize(self, delegation_id: str, *, delegate_id: str, action: str,
                  resource: str, amount_minor: int | None = None,
                  currency: str | None = None) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM signed_delegations WHERE delegation_id=?", (delegation_id,)
            ).fetchone()
            allowed = bool(row and row["delegate_id"] == delegate_id
                           and _scope_allows(row["action"], action)
                           and _scope_allows(row["resource"], resource)
                           and self._is_chain_active(db, row, set()))
            reason = "valid active signed delegation" if allowed else "missing, mismatched, expired, revoked or inactive delegation chain"
            if allowed and amount_minor is not None:
                if amount_minor < 0:
                    allowed, reason = False, "amount must be non-negative"
                elif row["max_amount_minor"] is None or amount_minor > row["max_amount_minor"]:
                    allowed, reason = False, "amount exceeds delegation ceiling"
                elif (currency or "").upper() != row["currency"]:
                    allowed, reason = False, "currency does not match delegation"
            elif allowed and row["max_amount_minor"] is not None:
                allowed, reason = False, "amount and currency are required by delegation ceiling"
            if allowed and action in HIGH_RISK_ACTIONS:
                return {"decision": "require_approval",
                        "reason": "high-risk action requires a separately verified owner approval",
                        "delegation_id": delegation_id}
            return {"decision": "allow" if allowed else "deny", "reason": reason,
                    "delegation_id": delegation_id}

    def revoke(self, delegation_id: str, *, actor_id: str, signature: str) -> None:
        with self._connect() as db:
            row = db.execute(
                "SELECT * FROM signed_delegations WHERE delegation_id=?", (delegation_id,)
            ).fetchone()
            if row is None or row["status"] != "active" or row["delegator_id"] != actor_id:
                raise ValueError("active delegation not found or actor is not the delegator")
            key = self._key_for(db, actor_id)
            payload = {"policy_version": POLICY_VERSION, "event": "revoke",
                       "delegation_id": delegation_id, "actor_id": actor_id}
            if not self.verifier(key, _canonical(payload), signature):
                raise ValueError("revocation signature is invalid")
            db.execute("UPDATE signed_delegations SET status='revoked' WHERE delegation_id=?",
                       (delegation_id,))

    @staticmethod
    def revocation_payload(delegation_id: str, actor_id: str) -> bytes:
        return _canonical({"policy_version": POLICY_VERSION, "event": "revoke",
                           "delegation_id": delegation_id, "actor_id": actor_id})
