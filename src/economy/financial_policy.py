"""Owner-signed, versioned financial policy provisioning.

Policies are authorization data, not payment execution. The current owner
participant key must sign each version; key rotation requires re-signing.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .identity import verify_ed25519


class ParticipantLookup(Protocol):
    def get(self, participant_id: str) -> dict[str, Any] | None: ...


class FinancialPolicyError(ValueError):
    """Invalid, unauthorized or stale financial policy."""


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class FinancialPolicyStore:
    """Persist policies signed by the active operator of an enrolled agent."""

    def __init__(self, participant_registry: ParticipantLookup,
                 path: str | Path = "./data/financial-policies.sqlite3") -> None:
        self.registry = participant_registry
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS financial_policies (
                    policy_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    owner_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    policy_json TEXT NOT NULL,
                    policy_sha256 TEXT NOT NULL,
                    owner_signature TEXT NOT NULL,
                    owner_public_key TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active','superseded','revoked')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(agent_id, policy_id, version)
                );
                CREATE INDEX IF NOT EXISTS financial_policy_active
                    ON financial_policies(agent_id, status, version);
            """)

    @staticmethod
    def payload(*, policy_id: str, version: int, owner_id: str, agent_id: str,
                currency: str, per_transaction_limit_minor: int,
                daily_spend_limit_minor: int, allowed_destinations: list[str]) -> dict[str, Any]:
        if not all(isinstance(v, str) and v.strip() for v in (policy_id, owner_id, agent_id)):
            raise FinancialPolicyError("policy_id, owner_id and agent_id are required")
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise FinancialPolicyError("version must be a positive integer")
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise FinancialPolicyError("currency must be a three-letter code")
        for value in (per_transaction_limit_minor, daily_spend_limit_minor):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 9_223_372_036_854_775_807:
                raise FinancialPolicyError("spending limits must be non-negative signed-64-bit integers")
        if per_transaction_limit_minor > daily_spend_limit_minor:
            raise FinancialPolicyError("per-transaction limit cannot exceed daily limit")
        if not isinstance(allowed_destinations, list) or not allowed_destinations:
            raise FinancialPolicyError("at least one exact allowlisted destination is required")
        if any(not isinstance(x, str) or not x.strip() or "*" in x for x in allowed_destinations):
            raise FinancialPolicyError("destinations must be exact non-wildcard strings")
        if len(set(allowed_destinations)) != len(allowed_destinations):
            raise FinancialPolicyError("destinations must be unique")
        return {
            "schema": "aae.financial-policy.v1",
            "policy_id": policy_id,
            "version": version,
            "owner_id": owner_id,
            "agent_id": agent_id,
            "currency": currency.upper(),
            "per_transaction_limit_minor": per_transaction_limit_minor,
            "daily_spend_limit_minor": daily_spend_limit_minor,
            "allowed_destinations": sorted(allowed_destinations),
        }

    def _participants(self, owner_id: str, agent_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        owner = self.registry.get(owner_id)
        agent = self.registry.get(agent_id)
        if owner is None or owner.get("status") != "active":
            raise FinancialPolicyError("owner participant is missing or inactive")
        if owner.get("participant_type") not in {"human", "organization"} or not owner.get("public_key"):
            raise FinancialPolicyError("owner must have an active human/organization signing key")
        if agent is None or agent.get("status") != "active" or agent.get("participant_type") != "agent":
            raise FinancialPolicyError("agent participant is missing, inactive or not an agent")
        if agent.get("operator_id") != owner_id:
            raise FinancialPolicyError("signing owner is not the enrolled agent's operator")
        return owner, agent

    def save(self, payload: dict[str, Any], signature: str) -> dict[str, Any]:
        required = {"schema","policy_id","version","owner_id","agent_id","currency",
                    "per_transaction_limit_minor","daily_spend_limit_minor","allowed_destinations"}
        if not isinstance(payload, dict) or set(payload) != required:
            raise FinancialPolicyError("policy payload has missing or unexpected fields")
        normalized = self.payload(
            policy_id=payload["policy_id"], version=payload["version"],
            owner_id=payload["owner_id"], agent_id=payload["agent_id"],
            currency=payload["currency"],
            per_transaction_limit_minor=payload["per_transaction_limit_minor"],
            daily_spend_limit_minor=payload["daily_spend_limit_minor"],
            allowed_destinations=payload["allowed_destinations"],
        )
        if payload["schema"] != normalized["schema"] or payload != normalized:
            raise FinancialPolicyError("policy payload is not in canonical normalized form")
        owner, _agent = self._participants(normalized["owner_id"], normalized["agent_id"])
        message = _canonical(normalized)
        if not verify_ed25519(owner["public_key"], message, signature):
            raise FinancialPolicyError("owner policy signature is invalid")
        digest = hashlib.sha256(message).hexdigest()
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT policy_sha256,status FROM financial_policies WHERE agent_id=? AND policy_id=? AND version=?",
                (normalized["agent_id"], normalized["policy_id"], normalized["version"]),
            ).fetchone()
            if existing:
                if existing[0] != digest:
                    db.rollback()
                    raise FinancialPolicyError("policy version already exists with different terms")
                if existing[1] != "active":
                    db.rollback()
                    raise FinancialPolicyError("policy version must increase monotonically; superseded policy cannot be reactivated")
                db.commit()
                return self.get(normalized["agent_id"], normalized["policy_id"])
            latest = db.execute(
                "SELECT MAX(version) FROM financial_policies WHERE agent_id=? AND policy_id=?",
                (normalized["agent_id"], normalized["policy_id"]),
            ).fetchone()[0]
            if latest is not None and normalized["version"] <= latest:
                db.rollback()
                raise FinancialPolicyError("policy version must increase monotonically")
            db.execute(
                "UPDATE financial_policies SET status='superseded' WHERE agent_id=? AND policy_id=? AND status='active'",
                (normalized["agent_id"], normalized["policy_id"]),
            )
            db.execute(
                """INSERT INTO financial_policies
                   (policy_id,version,owner_id,agent_id,policy_json,policy_sha256,
                    owner_signature,owner_public_key,status,created_at)
                   VALUES(?,?,?,?,?,?,?,?, 'active',?)""",
                (normalized["policy_id"], normalized["version"], normalized["owner_id"],
                 normalized["agent_id"], encoded, digest, signature, owner["public_key"], now),
            )
            db.commit()
        return self.get(normalized["agent_id"], normalized["policy_id"])

    def get(self, agent_id: str, policy_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """SELECT policy_id,version,owner_id,agent_id,policy_json,policy_sha256,
                          owner_signature,owner_public_key,status,created_at
                   FROM financial_policies WHERE agent_id=? AND policy_id=?
                   ORDER BY version DESC LIMIT 1""",
                (agent_id, policy_id),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["policy"] = json.loads(result.pop("policy_json"))
        # A key rotation or suspension invalidates this policy until the owner re-signs.
        try:
            owner, _agent = self._participants(result["owner_id"], result["agent_id"])
            current_key = owner["public_key"]
            signature_valid = bool(
                owner.get("status") == "active" and current_key
                and current_key == result["owner_public_key"]
                and verify_ed25519(current_key, _canonical(result["policy"]), result["owner_signature"])
            )
        except FinancialPolicyError:
            signature_valid = False
        result["currently_authorized"] = bool(result["status"] == "active" and signature_valid)
        return result

    def list_for_agent(self, agent_id: str | None = None) -> list[dict[str, Any]]:
        """List stored policy versions with authorization status re-evaluated now."""
        if agent_id is not None and (not isinstance(agent_id, str) or not agent_id.strip()):
            raise FinancialPolicyError("agent_id must be non-empty")
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            if agent_id is None:
                rows = db.execute(
                    "SELECT DISTINCT agent_id,policy_id FROM financial_policies ORDER BY agent_id,policy_id"
                ).fetchall()
            else:
                rows = db.execute(
                    "SELECT DISTINCT agent_id,policy_id FROM financial_policies WHERE agent_id=? ORDER BY policy_id",
                    (agent_id,),
                ).fetchall()
        results = []
        for row in rows:
            item = self.get(str(row["agent_id"]), str(row["policy_id"]))
            if item is not None:
                results.append(item)
        return results
