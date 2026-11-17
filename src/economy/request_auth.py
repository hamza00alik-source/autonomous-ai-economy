"""Signed participant request authentication and replay protection.

This module is framework-independent and is not a deployed HTTP server.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from pathlib import Path
from typing import Callable

from .identity import ParticipantRegistry, verify_ed25519


class RequestAuthenticator:
    """Verify Ed25519-signed requests and atomically consume replay nonces."""

    def __init__(
        self,
        registry: ParticipantRegistry,
        replay_db: str | Path,
        *,
        verifier: Callable[[str, bytes, str], bool] = verify_ed25519,
        clock: Callable[[], float] = time.time,
        max_clock_skew_seconds: int = 300,
        nonce_ttl_seconds: int = 600,
    ) -> None:
        if not 30 <= max_clock_skew_seconds <= 900:
            raise ValueError("max_clock_skew_seconds must be between 30 and 900")
        if nonce_ttl_seconds < max_clock_skew_seconds * 2:
            raise ValueError("nonce_ttl_seconds must be at least twice the clock skew")
        self.registry = registry
        self.replay_db = str(replay_db)
        self.verifier = verifier
        self.clock = clock
        self.max_clock_skew_seconds = max_clock_skew_seconds
        self.nonce_ttl_seconds = nonce_ttl_seconds
        Path(self.replay_db).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS consumed_request_nonces (
                    participant_id TEXT NOT NULL,
                    nonce TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    PRIMARY KEY(participant_id, nonce)
                )
            """)
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_request_nonce_expiry "
                "ON consumed_request_nonces(expires_at)"
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.replay_db, timeout=10, isolation_level=None)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def signing_bytes(method: str, path: str, body: bytes,
                      timestamp: int, nonce: str) -> bytes:
        method = method.upper()
        if not re.fullmatch(r"[A-Z]{3,12}", method):
            raise ValueError("invalid HTTP method")
        if not path.startswith("/") or any(ch in path for ch in "\r\n"):
            raise ValueError("path must be an absolute request path")
        if not isinstance(body, bytes):
            raise TypeError("body must be bytes")
        if not 0 <= timestamp <= 9_999_999_999:
            raise ValueError("timestamp must be a Unix timestamp in seconds")
        if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", nonce):
            raise ValueError("nonce must be 16-128 URL-safe characters")
        body_digest = hashlib.sha256(body).hexdigest()
        canonical = "\n".join((
            "AAE-HTTP-SIGNATURE-V1",
            method,
            path,
            body_digest,
            str(timestamp),
            nonce,
        ))
        return canonical.encode("utf-8")

    def authenticate(self, participant_id: str, method: str, path: str,
                     body: bytes, timestamp: int, nonce: str,
                     signature: str) -> dict:
        now = int(self.clock())
        if abs(now - timestamp) > self.max_clock_skew_seconds:
            raise ValueError("request timestamp is outside the allowed clock window")
        participant = self.registry.get(participant_id)
        if participant is None or participant["status"] != "active":
            raise ValueError("participant is unknown or inactive")
        public_key = participant.get("public_key")
        if not public_key:
            raise ValueError("participant has no bound signing key")
        payload = self.signing_bytes(method, path, body, timestamp, nonce)
        if not self.verifier(public_key, payload, signature):
            raise ValueError("request signature is invalid")

        expires_at = now + self.nonce_ttl_seconds
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM consumed_request_nonces WHERE expires_at < ?", (now,))
            try:
                db.execute(
                    "INSERT INTO consumed_request_nonces VALUES(?,?,?)",
                    (participant_id, nonce, expires_at),
                )
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise ValueError("request nonce has already been used") from exc
            db.commit()
        return {
            "participant_id": participant_id,
            "participant_type": participant["participant_type"],
            "authenticated": True,
            "key_id": hashlib.sha256(public_key.encode("ascii")).hexdigest()[:24],
            "request_body_sha256": hashlib.sha256(body).hexdigest(),
        }
