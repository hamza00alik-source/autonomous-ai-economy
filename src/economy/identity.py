"""Local participant identity registry for the open economy prototype.

Public-key enrollment uses Ed25519 through the optional 'identity' extra.
The registry stores public keys only. It never creates or stores private keys.
Human account records are not government-ID/KYC verification.
"""
from __future__ import annotations

import base64
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PARTICIPANT_TYPES = {"human", "agent", "organization"}
STATUSES = {"active", "suspended", "revoked"}
CLAIM_STATUSES = {"self_asserted", "verified", "expired", "revoked"}


class ParticipantRateLimitExceeded(Exception):
    """Raised when a participant exceeds a durable operation quota."""



def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _decode_key(value: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise ValueError("public_key must be URL-safe base64") from exc
    if len(raw) != 32:
        raise ValueError("Ed25519 public_key must decode to exactly 32 bytes")
    return raw


def verify_ed25519(public_key: str, message: bytes, signature: str) -> bool:
    """Fail closed when optional cryptography support is not installed."""
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise RuntimeError("Install the optional identity extra: pip install -e '.[identity]'") from exc
    try:
        key = Ed25519PublicKey.from_public_bytes(_decode_key(public_key))
        sig = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        key.verify(sig, message)
        return True
    except (ValueError, InvalidSignature):
        return False


class ParticipantRegistry:
    """SQLite registry for public participant records and single-use agent challenges."""

    def __init__(self, path: str | Path = "./data/participants.sqlite3",
                 challenge_ttl_seconds: int = 300) -> None:
        if not 30 <= challenge_ttl_seconds <= 1800:
            raise ValueError("challenge_ttl_seconds must be between 30 and 1800")
        self.path = str(path)
        self.challenge_ttl_seconds = challenge_ttl_seconds
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS participants (
                    participant_id TEXT PRIMARY KEY,
                    participant_type TEXT NOT NULL,
                    handle TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL,
                    public_key TEXT UNIQUE,
                    operator_id TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS enrollment_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    handle TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    public_key TEXT NOT NULL,
                    operator_id TEXT,
                    challenge TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS participant_key_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    participant_id TEXT NOT NULL,
                    public_key TEXT NOT NULL,
                    challenge TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    FOREIGN KEY(participant_id) REFERENCES participants(participant_id)
                );
                CREATE TABLE IF NOT EXISTS participant_key_rotation_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    participant_id TEXT NOT NULL,
                    old_public_key TEXT NOT NULL,
                    new_public_key TEXT NOT NULL,
                    challenge TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    FOREIGN KEY(participant_id) REFERENCES participants(participant_id)
                );
                CREATE TABLE IF NOT EXISTS participant_key_history (
                    event_id TEXT PRIMARY KEY,
                    participant_id TEXT NOT NULL,
                    old_public_key TEXT NOT NULL,
                    new_public_key TEXT NOT NULL,
                    rotated_at TEXT NOT NULL,
                    challenge_id TEXT NOT NULL UNIQUE,
                    FOREIGN KEY(participant_id) REFERENCES participants(participant_id)
                );
                CREATE TABLE IF NOT EXISTS participant_operation_events (
                    event_id TEXT PRIMARY KEY,
                    participant_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    FOREIGN KEY(participant_id) REFERENCES participants(participant_id)
                );
                CREATE INDEX IF NOT EXISTS idx_participant_operation_events
                    ON participant_operation_events(participant_id, operation, occurred_at);
                CREATE TABLE IF NOT EXISTS participant_security_events (
                    event_id TEXT PRIMARY KEY,
                    participant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    FOREIGN KEY(participant_id) REFERENCES participants(participant_id)
                );
                CREATE INDEX IF NOT EXISTS idx_security_events_participant
                    ON participant_security_events(participant_id, occurred_at);
                CREATE TABLE IF NOT EXISTS identity_claims (
                    claim_id TEXT PRIMARY KEY,
                    participant_id TEXT NOT NULL,
                    claim_type TEXT NOT NULL,
                    issuer TEXT NOT NULL,
                    status TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    issued_at TEXT NOT NULL,
                    expires_at TEXT,
                    evidence_ref TEXT,
                    FOREIGN KEY(participant_id) REFERENCES participants(participant_id)
                );
                CREATE INDEX IF NOT EXISTS idx_claims_participant ON identity_claims(participant_id);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _consume_operation_quota(db: sqlite3.Connection, participant_id: str,
                                 operation: str, *, limit: int = 5,
                                 window_seconds: int = 3600) -> None:
        """Atomically record one operation or reject it inside a rolling UTC window."""
        now = _now()
        cutoff = _iso(now - timedelta(seconds=window_seconds))
        now_text = _iso(now)
        db.execute("BEGIN IMMEDIATE")
        try:
            count = db.execute(
                """SELECT COUNT(*) AS n FROM participant_operation_events
                   WHERE participant_id=? AND operation=? AND occurred_at>?""",
                (participant_id, operation, cutoff),
            ).fetchone()["n"]
            if count >= limit:
                db.rollback()
                raise ParticipantRateLimitExceeded(operation)
            db.execute(
                """INSERT INTO participant_operation_events
                   (event_id,participant_id,operation,occurred_at) VALUES(?,?,?,?)""",
                (str(uuid.uuid4()), participant_id, operation, now_text),
            )
            db.commit()
        except ParticipantRateLimitExceeded:
            raise
        except Exception:
            db.rollback()
            raise

    @staticmethod
    def _participant(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json"))
        return item

    @staticmethod
    def _key_used_in_history(db: sqlite3.Connection, public_key: str) -> bool:
        return bool(db.execute(
            "SELECT 1 FROM participant_key_history WHERE old_public_key=? OR new_public_key=?",
            (public_key, public_key),
        ).fetchone())

    def create_human(self, handle: str, display_name: str,
                     account_control_method: str = "unverified",
                     metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a basic human account record; this does NOT verify legal identity."""
        if not handle.strip() or not display_name.strip():
            raise ValueError("handle and display_name are required")
        if len(handle) > 64 or len(display_name) > 120:
            raise ValueError("handle or display_name is too long")
        if account_control_method not in {"unverified", "email", "passkey", "external_credential"}:
            raise ValueError("unsupported account_control_method")
        participant_id = "human_" + uuid.uuid4().hex
        meta = dict(metadata or {})
        meta["account_control_method"] = account_control_method
        with self._connect() as db:
            db.execute(
                """INSERT INTO participants VALUES(?,?,?,?,NULL,NULL,'active',?,?)""",
                (participant_id, "human", handle.strip().lower(), display_name.strip(),
                 _iso(), json.dumps(meta, sort_keys=True)),
            )
        return self.get(participant_id)

    def create_organization(self, handle: str, display_name: str,
                            metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        if not handle.strip() or not display_name.strip():
            raise ValueError("handle and display_name are required")
        participant_id = "org_" + uuid.uuid4().hex
        with self._connect() as db:
            db.execute(
                """INSERT INTO participants VALUES(?,?,?,?,NULL,NULL,'active',?,?)""",
                (participant_id, "organization", handle.strip().lower(), display_name.strip(),
                 _iso(), json.dumps(metadata or {}, sort_keys=True)),
            )
        return self.get(participant_id)

    def begin_agent_enrollment(self, handle: str, display_name: str,
                               public_key: str, operator_id: str | None = None) -> dict[str, str]:
        if not handle.strip() or not display_name.strip():
            raise ValueError("handle and display_name are required")
        _decode_key(public_key)
        challenge_id = str(uuid.uuid4())
        challenge = "AAE-AGENT-ENROLL-V1:" + secrets.token_urlsafe(32)
        expires = _iso(_now() + timedelta(seconds=self.challenge_ttl_seconds))
        with self._connect() as db:
            self._consume_operation_quota(db, participant_id, "key_binding_challenge")
            if self._key_used_in_history(db, public_key):
                raise ValueError("public key has already appeared in participant key history")
            if operator_id:
                owner = db.execute("SELECT status FROM participants WHERE participant_id=?",
                                    (operator_id,)).fetchone()
                if owner is None or owner["status"] != "active":
                    raise ValueError("operator_id must reference an active participant")
            db.execute(
                """INSERT INTO enrollment_challenges
                (challenge_id,handle,display_name,public_key,operator_id,challenge,expires_at)
                VALUES(?,?,?,?,?,?,?)""",
                (challenge_id, handle.strip().lower(), display_name.strip(), public_key,
                 operator_id, challenge, expires),
            )
        return {"challenge_id": challenge_id, "challenge": challenge,
                "expires_at": expires, "signature_encoding": "base64url"}

    def complete_agent_enrollment(self, challenge_id: str, signature: str,
                                  verifier=verify_ed25519) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM enrollment_challenges WHERE challenge_id=?",
                             (challenge_id,)).fetchone()
            if row is None:
                db.rollback()
                raise ValueError("unknown enrollment challenge")
            if row["consumed_at"] is not None:
                db.rollback()
                raise ValueError("enrollment challenge already consumed")
            if datetime.fromisoformat(row["expires_at"]) <= _now():
                db.rollback()
                raise ValueError("enrollment challenge expired")
            if self._key_used_in_history(db, row["public_key"]):
                db.rollback()
                raise ValueError("public key has already appeared in participant key history")
            if not verifier(row["public_key"], row["challenge"].encode("utf-8"), signature):
                db.rollback()
                raise ValueError("agent key proof is invalid")
            participant_id = "agent_" + uuid.uuid4().hex
            now = _iso()
            try:
                db.execute(
                    """INSERT INTO participants VALUES(?,?, ?,?,?,?,'active',?,?)""",
                    (participant_id, "agent", row["handle"], row["display_name"],
                     row["public_key"], row["operator_id"], now,
                     json.dumps({"identity_method": "ed25519_possession"}, sort_keys=True)),
                )
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise ValueError("handle or public key is already registered") from exc
            db.execute("UPDATE enrollment_challenges SET consumed_at=? WHERE challenge_id=?",
                       (now, challenge_id))
            db.commit()
        return self.get(participant_id)

    def begin_key_binding(self, participant_id: str, public_key: str) -> dict[str, str]:
        """Start proof-of-possession key binding for an existing human or organization."""
        _decode_key(public_key)
        challenge_id = str(uuid.uuid4())
        challenge = "AAE-PARTICIPANT-KEY-BIND-V1:" + secrets.token_urlsafe(32)
        expires = _iso(_now() + timedelta(seconds=self.challenge_ttl_seconds))
        with self._connect() as db:
            if self._key_used_in_history(db, public_key):
                raise ValueError("public key has already appeared in participant key history")
            row = db.execute(
                "SELECT participant_type,status,public_key FROM participants WHERE participant_id=?",
                (participant_id,),
            ).fetchone()
            if row is None or row["status"] != "active":
                raise ValueError("participant must exist and be active")
            if row["participant_type"] == "agent":
                raise ValueError("agents bind keys during agent enrollment")
            if row["public_key"]:
                raise ValueError("participant already has a signing key")
            db.execute(
                """INSERT INTO participant_key_challenges
                (challenge_id,participant_id,public_key,challenge,expires_at)
                VALUES(?,?,?,?,?)""",
                (challenge_id, participant_id, public_key, challenge, expires),
            )
        return {"challenge_id": challenge_id, "challenge": challenge,
                "expires_at": expires, "signature_encoding": "base64url"}

    def complete_key_binding(self, challenge_id: str, signature: str,
                             verifier=verify_ed25519) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM participant_key_challenges WHERE challenge_id=?",
                (challenge_id,),
            ).fetchone()
            if row is None:
                db.rollback()
                raise ValueError("unknown participant key challenge")
            if row["consumed_at"] is not None:
                db.rollback()
                raise ValueError("participant key challenge already consumed")
            if datetime.fromisoformat(row["expires_at"]) <= _now():
                db.rollback()
                raise ValueError("participant key challenge expired")
            participant = db.execute(
                "SELECT participant_type,status,public_key,metadata_json FROM participants WHERE participant_id=?",
                (row["participant_id"],),
            ).fetchone()
            if participant is None or participant["status"] != "active" or participant["public_key"]:
                db.rollback()
                raise ValueError("participant is inactive or already has a signing key")
            if participant["participant_type"] == "agent":
                db.rollback()
                raise ValueError("agent keys are bound during enrollment")
            if self._key_used_in_history(db, row["public_key"]):
                db.rollback()
                raise ValueError("public key has already appeared in participant key history")
            if not verifier(row["public_key"], row["challenge"].encode("utf-8"), signature):
                db.rollback()
                raise ValueError("participant key proof is invalid")
            metadata = json.loads(participant["metadata_json"])
            metadata["signing_key_method"] = "ed25519_possession"
            now = _iso()
            try:
                db.execute(
                    "UPDATE participants SET public_key=?,metadata_json=? WHERE participant_id=? AND public_key IS NULL",
                    (row["public_key"], json.dumps(metadata, sort_keys=True), row["participant_id"]),
                )
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise ValueError("public key is already bound to another participant") from exc
            db.execute(
                "UPDATE participant_key_challenges SET consumed_at=? WHERE challenge_id=?",
                (now, challenge_id),
            )
            db.commit()
        return self.get(row["participant_id"])

    def begin_key_rotation(self, participant_id: str, new_public_key: str) -> dict[str, str]:
        """Start dual-proof key rotation; both old and new private keys must sign."""
        _decode_key(new_public_key)
        challenge_id = str(uuid.uuid4())
        challenge = "AAE-PARTICIPANT-KEY-ROTATE-V1:" + secrets.token_urlsafe(32)
        expires = _iso(_now() + timedelta(seconds=self.challenge_ttl_seconds))
        with self._connect() as db:
            self._consume_operation_quota(db, participant_id, "key_rotation_challenge")
            participant = db.execute(
                "SELECT status,public_key FROM participants WHERE participant_id=?",
                (participant_id,),
            ).fetchone()
            if participant is None or participant["status"] != "active" or not participant["public_key"]:
                raise ValueError("participant must be active and have an existing signing key")
            if participant["public_key"] == new_public_key:
                raise ValueError("new public key must differ from current key")
            if self._key_used_in_history(db, new_public_key):
                raise ValueError("new public key has already appeared in participant key history")
            if db.execute("SELECT 1 FROM participants WHERE public_key=?",
                          (new_public_key,)).fetchone():
                raise ValueError("new public key is already bound")
            db.execute(
                """INSERT INTO participant_key_rotation_challenges
                (challenge_id,participant_id,old_public_key,new_public_key,challenge,expires_at)
                VALUES(?,?,?,?,?,?)""",
                (challenge_id, participant_id, participant["public_key"],
                 new_public_key, challenge, expires),
            )
        return {"challenge_id": challenge_id, "challenge": challenge,
                "expires_at": expires, "signature_encoding": "base64url",
                "required_signatures": "current_and_new_key"}

    def complete_key_rotation(self, challenge_id: str, old_signature: str,
                              new_signature: str, verifier=verify_ed25519, *,
                              expected_participant_id: str | None = None) -> dict[str, Any]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM participant_key_rotation_challenges WHERE challenge_id=?",
                (challenge_id,),
            ).fetchone()
            if row is None:
                db.rollback()
                raise ValueError("unknown key rotation challenge")
            if (expected_participant_id is not None
                    and row["participant_id"] != expected_participant_id):
                db.rollback()
                raise ValueError("key rotation challenge belongs to another participant")
            if row["consumed_at"] is not None:
                db.rollback()
                raise ValueError("key rotation challenge already consumed")
            if datetime.fromisoformat(row["expires_at"]) <= _now():
                db.rollback()
                raise ValueError("key rotation challenge expired")
            participant = db.execute(
                "SELECT status,public_key,metadata_json FROM participants WHERE participant_id=?",
                (row["participant_id"],),
            ).fetchone()
            if (participant is None or participant["status"] != "active"
                    or participant["public_key"] != row["old_public_key"]):
                db.rollback()
                raise ValueError("participant is inactive or current key has changed")
            if self._key_used_in_history(db, row["new_public_key"]):
                db.rollback()
                raise ValueError("new public key has already appeared in participant key history")
            message = row["challenge"].encode("utf-8")
            if not verifier(row["old_public_key"], message, old_signature):
                db.rollback()
                raise ValueError("current-key rotation proof is invalid")
            if not verifier(row["new_public_key"], message, new_signature):
                db.rollback()
                raise ValueError("new-key rotation proof is invalid")
            metadata = json.loads(participant["metadata_json"])
            metadata["signing_key_method"] = "ed25519_dual_proof_rotation"
            now = _iso()
            try:
                updated = db.execute(
                    "UPDATE participants SET public_key=?,metadata_json=? WHERE participant_id=? AND public_key=?",
                    (row["new_public_key"], json.dumps(metadata, sort_keys=True),
                     row["participant_id"], row["old_public_key"]),
                )
                if updated.rowcount != 1:
                    raise ValueError("participant key changed during rotation")
                db.execute(
                    "INSERT INTO participant_key_history VALUES(?,?,?,?,?,?)",
                    ("key_rotation_" + uuid.uuid4().hex, row["participant_id"],
                     row["old_public_key"], row["new_public_key"], now, challenge_id),
                )
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise ValueError("new public key is already bound") from exc
            db.execute(
                "UPDATE participant_key_rotation_challenges SET consumed_at=? WHERE challenge_id=?",
                (now, challenge_id),
            )
            db.commit()
        return self.get(row["participant_id"])

    def key_history(self, participant_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM participant_key_history WHERE participant_id=? ORDER BY rotated_at",
                (participant_id,),
            ).fetchall()]

    def emergency_lock_account(self, participant_id: str) -> dict[str, Any]:
        """Suspend a participant and invalidate pending key challenges atomically.

        This is intentionally one-way through the participant API. Recovery requires
        a separate owner-controlled process outside this registry method.
        """
        now = _iso()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            participant = db.execute(
                "SELECT status FROM participants WHERE participant_id=?",
                (participant_id,),
            ).fetchone()
            if participant is None:
                db.rollback()
                raise KeyError(participant_id)
            if participant["status"] != "active":
                db.rollback()
                raise ValueError("participant is not active")
            db.execute(
                "UPDATE participants SET status='suspended' WHERE participant_id=? AND status='active'",
                (participant_id,),
            )
            db.execute(
                """UPDATE participant_key_challenges SET consumed_at=?
                   WHERE participant_id=? AND consumed_at IS NULL""",
                (now, participant_id),
            )
            db.execute(
                """UPDATE participant_key_rotation_challenges SET consumed_at=?
                   WHERE participant_id=? AND consumed_at IS NULL""",
                (now, participant_id),
            )
            db.execute(
                """INSERT INTO participant_security_events
                   (event_id,participant_id,event_type,occurred_at,details_json)
                   VALUES(?,?,?,?,?)""",
                ("security_" + uuid.uuid4().hex, participant_id,
                 "participant_requested_account_lock", now, "{}"),
            )
            db.commit()
        return {"participant_id": participant_id, "status": "suspended",
                "locked_at": now}

    def security_events(self, participant_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                """SELECT event_id,event_type,occurred_at,details_json
                   FROM participant_security_events WHERE participant_id=?
                   ORDER BY occurred_at,event_id""",
                (participant_id,),
            ).fetchall()]

    def get(self, participant_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            return self._participant(db.execute(
                "SELECT * FROM participants WHERE participant_id=?", (participant_id,)
            ).fetchone())

    def list_participants(self, participant_type: str | None = None,
                          include_inactive: bool = False) -> list[dict[str, Any]]:
        if participant_type and participant_type not in PARTICIPANT_TYPES:
            raise ValueError("unsupported participant_type")
        clauses, params = [], []
        if participant_type:
            clauses.append("participant_type=?")
            params.append(participant_type)
        if not include_inactive:
            clauses.append("status='active'")
        sql = "SELECT * FROM participants"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at, participant_id"
        with self._connect() as db:
            return [self._participant(row) for row in db.execute(sql, params).fetchall()]

    def summary_counts(self) -> dict[str, dict[str, int]]:
        """Return aggregate participant counts without exposing participant records."""
        with self._connect() as db:
            rows = db.execute(
                "SELECT participant_type, status, COUNT(*) AS total "
                "FROM participants GROUP BY participant_type, status"
            ).fetchall()
        result: dict[str, dict[str, int]] = {}
        for row in rows:
            result.setdefault(row["participant_type"], {})[row["status"]] = row["total"]
        return result

    def add_claim(self, participant_id: str, claim_type: str, issuer: str,
                  scope: str, status: str = "self_asserted",
                  expires_at: str | None = None, evidence_ref: str | None = None) -> str:
        if status not in CLAIM_STATUSES:
            raise ValueError("unsupported claim status")
        if not all(value.strip() for value in (claim_type, issuer, scope)):
            raise ValueError("claim_type, issuer and scope are required")
        claim_id = "claim_" + uuid.uuid4().hex
        with self._connect() as db:
            if not db.execute("SELECT 1 FROM participants WHERE participant_id=?",
                              (participant_id,)).fetchone():
                raise KeyError(participant_id)
            db.execute(
                """INSERT INTO identity_claims VALUES(?,?,?,?,?,?,?,?,?)""",
                (claim_id, participant_id, claim_type, issuer, status, scope,
                 _iso(), expires_at, evidence_ref),
            )
        return claim_id

    def claims(self, participant_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM identity_claims WHERE participant_id=? ORDER BY issued_at",
                (participant_id,),
            ).fetchall()
            return [dict(row) for row in rows]

    def set_status(self, participant_id: str, status: str) -> None:
        if status not in STATUSES:
            raise ValueError("unsupported participant status")
        with self._connect() as db:
            cur = db.execute("UPDATE participants SET status=? WHERE participant_id=?",
                             (status, participant_id))
            if cur.rowcount != 1:
                raise KeyError(participant_id)
