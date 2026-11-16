"""Policy composition for scoped capabilities, delegation and exact owner approvals.

This module returns authorization decisions only. It never executes external actions.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .permissions import CapabilityStore, HIGH_RISK_ACTIONS
from .delegation import DelegationStore


FINANCIAL_ACTIONS = {"spend", "transfer", "financial_execute", "custody"}


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


class ActionApprovalStore:
    """Short-lived HMAC owner approvals bound to one exact authorization request."""

    def __init__(self, path: str | Path = "./data/participants.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS consumed_action_approvals (
                    nonce TEXT PRIMARY KEY,
                    request_digest TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
                )
            """)

    @staticmethod
    def _secret(secret: str | bytes) -> bytes:
        value = secret.encode("utf-8") if isinstance(secret, str) else secret
        if len(value) < 32:
            raise ValueError("action approval secret must contain at least 32 bytes")
        return value

    @staticmethod
    def request_payload(subject_id: str, action: str, resource: str,
                        amount_minor: int | None = None,
                        currency: str | None = None) -> dict[str, Any]:
        return {"subject_id": subject_id, "action": action, "resource": resource,
                "amount_minor": amount_minor, "currency": currency.upper() if currency else None}

    @classmethod
    def create_token(cls, subject_id: str, action: str, resource: str,
                     secret: str | bytes, *, amount_minor: int | None = None,
                     currency: str | None = None, ttl_seconds: int = 600) -> str:
        if not all(v.strip() for v in (subject_id, action, resource)):
            raise ValueError("subject, action and resource are required")
        if not 1 <= ttl_seconds <= 3600:
            raise ValueError("ttl_seconds must be between 1 and 3600")
        if action in FINANCIAL_ACTIONS:
            if amount_minor is None or amount_minor < 0 or not currency:
                raise ValueError("financial approvals require a non-negative amount and currency")
        if amount_minor is not None and amount_minor < 0:
            raise ValueError("amount_minor must be non-negative")
        if currency and (len(currency) != 3 or not currency.isalpha()):
            raise ValueError("currency must be a three-letter code")
        key = cls._secret(secret)
        request = cls.request_payload(subject_id, action, resource, amount_minor, currency)
        digest = hashlib.sha256(_canonical(request)).hexdigest()
        payload = {
            "v": 1, "purpose": "high_risk_action", "request_digest": digest,
            "expires_at": int((datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).timestamp()),
            "nonce": secrets.token_urlsafe(24),
        }
        encoded = base64.urlsafe_b64encode(_canonical(payload)).rstrip(b"=").decode("ascii")
        signature = hmac.new(key, ("AAE-ACTION-APPROVAL:" + encoded).encode("ascii"),
                             hashlib.sha256).hexdigest()
        return encoded + "." + signature

    def consume(self, token: str, subject_id: str, action: str, resource: str,
                secret: str | bytes, *, amount_minor: int | None = None,
                currency: str | None = None) -> tuple[bool, str]:
        try:
            key = self._secret(secret)
            encoded, supplied = token.split(".", 1)
            expected = hmac.new(key, ("AAE-ACTION-APPROVAL:" + encoded).encode("ascii"),
                                hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, supplied):
                return False, "Owner approval signature is invalid."
            token_payload = json.loads(base64.urlsafe_b64decode(
                (encoded + "=" * (-len(encoded) % 4)).encode("ascii")
            ))
            request = self.request_payload(subject_id, action, resource, amount_minor, currency)
            digest = hashlib.sha256(_canonical(request)).hexdigest()
            if token_payload.get("v") != 1 or token_payload.get("purpose") != "high_risk_action":
                return False, "Owner approval purpose is invalid."
            if not hmac.compare_digest(str(token_payload.get("request_digest", "")), digest):
                return False, "Owner approval does not match this exact action request."
            if int(token_payload.get("expires_at", 0)) <= int(datetime.now(timezone.utc).timestamp()):
                return False, "Owner approval has expired."
            nonce = str(token_payload["nonce"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
            return False, "Owner approval token is malformed or secret is unavailable."
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("PRAGMA busy_timeout=10000")
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO consumed_action_approvals VALUES(?,?,?)",
                    (nonce, digest, datetime.now(timezone.utc).isoformat()),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                return False, "Owner approval has already been used."
        return True, "Exact owner approval verified and consumed."


class PolicyEngine:
    """Combines capability/delegation authorization with verified one-time approvals."""

    def __init__(self, capabilities: CapabilityStore, approvals: ActionApprovalStore,
                 *, approval_secret: str | bytes,
                 delegations: DelegationStore | None = None) -> None:
        ActionApprovalStore._secret(approval_secret)
        self.capabilities = capabilities
        self.approvals = approvals
        self.approval_secret = approval_secret
        self.delegations = delegations

    def authorize(self, subject_id: str, action: str, resource: str, *,
                  amount_minor: int | None = None, currency: str | None = None,
                  approval_token: str | None = None,
                  delegation_id: str | None = None) -> dict[str, str]:
        if delegation_id:
            if self.delegations is None:
                return {"decision": "deny", "reason": "delegation service is not configured"}
            base = self.delegations.authorize(
                delegation_id, delegate_id=subject_id, action=action, resource=resource,
                amount_minor=amount_minor, currency=currency,
            )
        else:
            base = self.capabilities.authorize(
                subject_id, action, resource, amount_minor=amount_minor, currency=currency,
            )
        if base["decision"] == "deny":
            return {"decision": "deny", "reason": base["reason"]}
        if action not in HIGH_RISK_ACTIONS:
            return {"decision": "allow", "reason": base["reason"]}
        if not approval_token:
            return {"decision": "require_approval", "reason": "high-risk action requires an exact owner approval"}
        valid, reason = self.approvals.consume(
            approval_token, subject_id, action, resource, self.approval_secret,
            amount_minor=amount_minor, currency=currency,
        )
        if not valid:
            return {"decision": "require_approval", "reason": reason}
        return {"decision": "allow", "reason": "capability/delegation and one-time owner approval verified; no action executed"}
