"""Authenticated, expiring, single-use owner approvals for opportunity drafts.

This is a local prototype control, not identity verification or a hardened remote
authorization service. Keep the HMAC secret outside source control.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .opportunities import Opportunity


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def opportunity_fingerprint(opportunity: Opportunity) -> str:
    evidence = [
        {
            "source_name": item.source_name,
            "url": item.url,
            "observed_on": item.observed_on,
            "kind": item.kind.value,
            "finding": item.finding,
            "independent_source": item.independent_source,
        }
        for item in opportunity.evidence
    ]
    payload = {
        "title": opportunity.title,
        "buyer_segment": opportunity.buyer_segment,
        "problem": opportunity.problem,
        "proposed_solution": opportunity.proposed_solution,
        "delivery_format": opportunity.delivery_format,
        "estimated_startup_cost_minor": opportunity.estimated_startup_cost_minor,
        "currency": opportunity.currency,
        "legal_risk_notes": opportunity.legal_risk_notes,
        "evidence": evidence,
    }
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _secret_bytes(secret: str | bytes) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else secret
    if len(value) < 32:
        raise ValueError("owner approval secret must contain at least 32 bytes")
    return value


def create_approval_token(
    opportunity: Opportunity,
    secret: str | bytes,
    *,
    ttl_seconds: int = 600,
) -> str:
    """Create a token after the owner has reviewed and explicitly approved the draft."""
    if not 1 <= ttl_seconds <= 3600:
        raise ValueError("ttl_seconds must be between 1 and 3600")
    key = _secret_bytes(secret)
    payload = {
        "v": 1,
        "opportunity": opportunity_fingerprint(opportunity),
        "expires_at": int((datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).timestamp()),
        "nonce": secrets.token_urlsafe(24),
    }
    encoded = base64.urlsafe_b64encode(_canonical(payload)).rstrip(b"=").decode("ascii")
    signature = hmac.new(key, encoded.encode("ascii"), hashlib.sha256).hexdigest()
    return encoded + "." + signature


class OwnerApprovalStore:
    """Consumes signed approvals once in a local SQLite database."""

    def __init__(self, path: str | Path = "./data/owner-approvals.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS consumed_approvals (
                    nonce TEXT PRIMARY KEY,
                    opportunity_fingerprint TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
                )
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def consume(
        self,
        token: str,
        opportunity: Opportunity,
        secret: str | bytes,
    ) -> tuple[bool, str]:
        try:
            key = _secret_bytes(secret)
            encoded, supplied_signature = token.split(".", 1)
            expected = hmac.new(key, encoded.encode("ascii"), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, supplied_signature):
                return False, "Owner approval signature is invalid."
            padded = encoded + "=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
            if payload.get("v") != 1 or not payload.get("nonce"):
                return False, "Owner approval token format is invalid."
            fingerprint = opportunity_fingerprint(opportunity)
            if not hmac.compare_digest(str(payload.get("opportunity", "")), fingerprint):
                return False, "Approval does not match this exact opportunity and evidence."
            if int(payload.get("expires_at", 0)) <= int(datetime.now(timezone.utc).timestamp()):
                return False, "Owner approval token has expired."
            nonce = str(payload["nonce"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
            return False, "Owner approval token is malformed or approval secret is unavailable."

        with self._connect() as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO consumed_approvals(nonce,opportunity_fingerprint,consumed_at) VALUES(?,?,?)",
                    (nonce, fingerprint, datetime.now(timezone.utc).isoformat()),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                return False, "Owner approval token has already been used."
        return True, "Owner approval verified and consumed."
