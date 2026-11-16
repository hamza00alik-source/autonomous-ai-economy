"""Provider-signed service listing drafts with an explicit publication gate."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import json
import re
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Callable
from datetime import timedelta

from .delegation import _canonical
from .identity import verify_ed25519


class CatalogApprovalStore:
    """HMAC-signed, exact-listing, expiring and single-use publication approvals."""

    def __init__(self, path: str | Path = "./data/participants.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS consumed_catalog_approvals (
                    nonce TEXT PRIMARY KEY,
                    approval_digest TEXT NOT NULL,
                    consumed_at TEXT NOT NULL
                )
            """)

    @staticmethod
    def _secret(secret: str | bytes) -> bytes:
        value = secret.encode("utf-8") if isinstance(secret, str) else secret
        if len(value) < 32:
            raise ValueError("catalog approval secret must contain at least 32 bytes")
        return value

    @classmethod
    def create_token(cls, listing_id: str, approval_payload: bytes,
                     secret: str | bytes, *, ttl_seconds: int = 600) -> str:
        if not 1 <= ttl_seconds <= 3600:
            raise ValueError("ttl_seconds must be between 1 and 3600")
        key = cls._secret(secret)
        digest = hashlib.sha256(approval_payload).hexdigest()
        token_payload = {
            "v": 1, "purpose": "service_listing_publish", "listing_id": listing_id,
            "approval_digest": digest,
            "expires_at": int((datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).timestamp()),
            "nonce": secrets.token_urlsafe(24),
        }
        encoded = base64.urlsafe_b64encode(_canonical(token_payload)).rstrip(b"=").decode("ascii")
        signature = hmac.new(key, ("AAE-CATALOG-APPROVAL:" + encoded).encode("ascii"),
                             hashlib.sha256).hexdigest()
        return encoded + "." + signature

    def consume(self, token: str, listing_id: str, approval_payload: bytes,
                secret: str | bytes) -> tuple[bool, str]:
        try:
            key = self._secret(secret)
            encoded, supplied = token.split(".", 1)
            expected = hmac.new(key, ("AAE-CATALOG-APPROVAL:" + encoded).encode("ascii"),
                                hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, supplied):
                return False, "Catalog approval signature is invalid."
            padded = encoded + "=" * (-len(encoded) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
            digest = hashlib.sha256(approval_payload).hexdigest()
            if payload.get("v") != 1 or payload.get("purpose") != "service_listing_publish":
                return False, "Catalog approval token purpose is invalid."
            if payload.get("listing_id") != listing_id or not hmac.compare_digest(
                str(payload.get("approval_digest", "")), digest
            ):
                return False, "Catalog approval does not match this exact listing."
            if int(payload.get("expires_at", 0)) <= int(datetime.now(timezone.utc).timestamp()):
                return False, "Catalog approval token has expired."
            nonce = str(payload["nonce"])
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, UnicodeError):
            return False, "Catalog approval token is malformed or secret is unavailable."
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("PRAGMA busy_timeout=10000")
            try:
                db.execute("BEGIN IMMEDIATE")
                db.execute(
                    "INSERT INTO consumed_catalog_approvals VALUES(?,?,?)",
                    (nonce, digest, datetime.now(timezone.utc).isoformat()),
                )
                db.commit()
            except sqlite3.IntegrityError:
                db.rollback()
                return False, "Catalog approval token has already been used."
        return True, "Catalog approval verified and consumed."



class ServiceCatalog:
    """Local catalog; listings stay private drafts until a trusted approval verifier accepts."""

    def __init__(self, path: str | Path = "./data/participants.sqlite3", *,
                 verifier: Callable[[str, bytes, str], bool] = verify_ed25519) -> None:
        self.path = str(path)
        self.verifier = verifier
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS service_listings (
                    listing_id TEXT PRIMARY KEY,
                    provider_id TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    category TEXT NOT NULL,
                    delivery_format TEXT NOT NULL,
                    terms TEXT NOT NULL,
                    price_minor INTEGER,
                    currency TEXT,
                    payload_json TEXT NOT NULL,
                    provider_signature TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('draft','active','withdrawn','suspended')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_catalog_public
                    ON service_listings(status,category,slug);
                CREATE TABLE IF NOT EXISTS catalog_events (
                    event_id TEXT PRIMARY KEY,
                    listing_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    event TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def listing_payload(*, provider_id: str, slug: str, title: str,
                        description: str, category: str, delivery_format: str,
                        terms: str, price_minor: int | None = None,
                        currency: str | None = None) -> dict[str, Any]:
        return {"version": "1", "provider_id": provider_id, "slug": slug,
                "title": title, "description": description, "category": category,
                "delivery_format": delivery_format, "terms": terms,
                "price_minor": price_minor, "currency": currency.upper() if currency else None}

    @staticmethod
    def publication_payload(listing_id: str, payload: dict[str, Any]) -> bytes:
        fingerprint = hashlib.sha256(_canonical(payload)).hexdigest()
        return _canonical({"version": "1", "event": "publish_listing",
                           "listing_id": listing_id, "fingerprint": fingerprint})

    @staticmethod
    def listing_signing_bytes(**fields: Any) -> bytes:
        return _canonical(ServiceCatalog.listing_payload(**fields))

    @staticmethod
    def withdrawal_signing_bytes(listing_id: str, provider_id: str) -> bytes:
        return _canonical({"version": "1", "event": "withdraw_listing",
                           "listing_id": listing_id, "provider_id": provider_id})

    def _provider_key(self, db: sqlite3.Connection, provider_id: str) -> str:
        row = db.execute(
            "SELECT public_key,status,participant_type FROM participants WHERE participant_id=?",
            (provider_id,),
        ).fetchone()
        if row is None or row["status"] != "active" or row["participant_type"] not in {"agent", "human", "organization"} or not row["public_key"]:
            raise ValueError("provider must be an active human, agent or organization with a signing key")
        return row["public_key"]

    def create_draft(self, *, provider_id: str, slug: str, title: str,
                     description: str, category: str, delivery_format: str,
                     terms: str, signature: str, price_minor: int | None = None,
                     currency: str | None = None) -> dict[str, Any]:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise ValueError("slug must contain lowercase letters, digits and hyphens")
        if not all(v.strip() for v in (title, description, category, delivery_format, terms, signature)):
            raise ValueError("all listing text fields and signature are required")
        if len(title) > 120 or len(description) > 5000 or len(terms) > 3000:
            raise ValueError("listing text exceeds its length limit")
        if price_minor is not None and price_minor < 0:
            raise ValueError("price_minor must be non-negative")
        if (price_minor is None) != (currency is None):
            raise ValueError("price and currency must be supplied together")
        if currency and (len(currency) != 3 or not currency.isalpha()):
            raise ValueError("currency must be a three-letter code")
        payload = self.listing_payload(
            provider_id=provider_id, slug=slug, title=title, description=description,
            category=category, delivery_format=delivery_format, terms=terms,
            price_minor=price_minor, currency=currency,
        )
        with self._connect() as db:
            key = self._provider_key(db, provider_id)
            if not self.verifier(key, _canonical(payload), signature):
                raise ValueError("provider listing signature is invalid")
            listing_id = "listing_" + uuid.uuid4().hex
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                """INSERT INTO service_listings VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'draft',?,?)""",
                (listing_id, provider_id, slug, title, description, category,
                 delivery_format, terms, price_minor, currency.upper() if currency else None,
                 json.dumps(payload, sort_keys=True), signature, now, now),
            )
            self._event(db, listing_id, provider_id, "draft_created", "provider-signed draft")
        return self.get(listing_id)

    @staticmethod
    def _event(db: sqlite3.Connection, listing_id: str, actor_id: str,
               event: str, detail: str) -> None:
        db.execute(
            "INSERT INTO catalog_events VALUES(?,?,?,?,?,?)",
            ("catalog_event_" + uuid.uuid4().hex, listing_id, actor_id,
             event, detail, datetime.now(timezone.utc).isoformat()),
        )

    def publish(self, listing_id: str, *, approval_ref: str,
                approval_verifier: Callable[[str, bytes], bool] | None = None) -> dict[str, Any]:
        if not approval_ref or approval_verifier is None:
            raise ValueError("a separately configured owner approval verifier is required")
        with self._connect() as db:
            row = db.execute("SELECT * FROM service_listings WHERE listing_id=?", (listing_id,)).fetchone()
            if row is None or row["status"] != "draft":
                raise ValueError("draft listing not found")
            payload = json.loads(row["payload_json"])
            approval_payload = self.publication_payload(listing_id, payload)
            if not approval_verifier(approval_ref, approval_payload):
                raise ValueError("owner approval is invalid, expired, mismatched or already consumed")
            now = datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE service_listings SET status='active',updated_at=? WHERE listing_id=?",
                       (now, listing_id))
            self._event(db, listing_id, "owner", "published", "owner approval verifier accepted exact listing fingerprint")
        return self.get(listing_id)

    def publish_with_token(self, listing_id: str, *, approval_token: str,
                           approval_secret: str | bytes) -> dict[str, Any]:
        approval_store = CatalogApprovalStore(self.path)
        def verify(token: str, payload: bytes) -> bool:
            valid, _reason = approval_store.consume(
                token, listing_id, payload, approval_secret
            )
            return valid
        return self.publish(listing_id, approval_ref=approval_token,
                            approval_verifier=verify)

    def withdraw(self, listing_id: str, *, provider_id: str, signature: str) -> None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM service_listings WHERE listing_id=?", (listing_id,)).fetchone()
            if row is None or row["provider_id"] != provider_id or row["status"] not in {"draft", "active"}:
                raise ValueError("listing not found or provider is not authorized")
            key = self._provider_key(db, provider_id)
            payload = self.withdrawal_signing_bytes(listing_id, provider_id)
            if not self.verifier(key, payload, signature):
                raise ValueError("provider withdrawal signature is invalid")
            now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            db.execute("UPDATE service_listings SET status='withdrawn',updated_at=? WHERE listing_id=?",
                       (now, listing_id))
            self._event(db, listing_id, provider_id, "withdrawn", "provider-signed withdrawal")

    def get(self, listing_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM service_listings WHERE listing_id=?", (listing_id,)).fetchone()
            if row is None:
                raise KeyError(listing_id)
            result = dict(row)
            result["payload"] = json.loads(result.pop("payload_json"))
            return result

    def discover(self, *, query: str = "", category: str | None = None,
                 limit: int = 50) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        clauses, params = ["status='active'"], []
        if category:
            clauses.append("category=?")
            params.append(category)
        if query.strip():
            clauses.append("(title LIKE ? OR description LIKE ? OR category LIKE ?)")
            term = "%" + query.strip() + "%"
            params.extend([term, term, term])
        sql = "SELECT listing_id,provider_id,slug,title,description,category,delivery_format,terms,price_minor,currency FROM service_listings WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, params).fetchall()]

    def events(self, listing_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM catalog_events WHERE listing_id=? ORDER BY created_at",
                (listing_id,),
            ).fetchall()]
