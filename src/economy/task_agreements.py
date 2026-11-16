"""Signed, non-financial task offers and bilateral acceptance for the sandbox marketplace."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .delegation import _canonical
from .identity import verify_ed25519


class TaskAgreementStore:
    """Records buyer offers and provider acceptance; it is not a legal contract or payment rail."""

    def __init__(self, path: str | Path = "./data/participants.sqlite3", *,
                 verifier: Callable[[str, bytes, str], bool] = verify_ed25519) -> None:
        self.path = str(path)
        self.verifier = verifier
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS task_agreements (
                    task_id TEXT PRIMARY KEY,
                    listing_id TEXT NOT NULL,
                    buyer_id TEXT NOT NULL,
                    provider_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    acceptance_criteria TEXT NOT NULL,
                    due_at TEXT,
                    price_minor INTEGER,
                    currency TEXT,
                    offer_payload TEXT NOT NULL,
                    buyer_signature TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('offered','accepted','declined','withdrawn')),
                    provider_signature TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_task_offers_provider
                    ON task_agreements(provider_id,status,created_at);
                CREATE TABLE IF NOT EXISTS task_agreement_events (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
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

    def _key(self, db: sqlite3.Connection, participant_id: str) -> str:
        row = db.execute(
            "SELECT public_key,status FROM participants WHERE participant_id=?",
            (participant_id,),
        ).fetchone()
        if row is None or row["status"] != "active" or not row["public_key"]:
            raise ValueError("participant must be active and have a bound signing key")
        return row["public_key"]

    @staticmethod
    def offer_payload(*, task_id: str, listing_id: str, buyer_id: str,
                      provider_id: str, title: str, scope: str,
                      acceptance_criteria: str, due_at: str | None = None,
                      price_minor: int | None = None,
                      currency: str | None = None) -> dict[str, Any]:
        return {"version": "1", "event": "task_offer", "task_id": task_id,
                "listing_id": listing_id, "buyer_id": buyer_id,
                "provider_id": provider_id, "title": title, "scope": scope,
                "acceptance_criteria": acceptance_criteria, "due_at": due_at,
                "price_minor": price_minor, "currency": currency.upper() if currency else None}

    @staticmethod
    def offer_signing_bytes(**fields: Any) -> bytes:
        return _canonical(TaskAgreementStore.offer_payload(**fields))

    @staticmethod
    def response_payload(task_id: str, provider_id: str, decision: str,
                         offer_digest: str) -> bytes:
        return _canonical({"version": "1", "event": "task_offer_response",
                           "task_id": task_id, "provider_id": provider_id,
                           "decision": decision, "offer_digest": offer_digest})

    @staticmethod
    def _event(db: sqlite3.Connection, task_id: str, actor_id: str,
               event: str, detail: str) -> None:
        db.execute(
            "INSERT INTO task_agreement_events VALUES(?,?,?,?,?,?)",
            ("task_event_" + uuid.uuid4().hex, task_id, actor_id, event,
             detail, datetime.now(timezone.utc).isoformat()),
        )

    def create_offer(self, *, task_id: str, listing_id: str, buyer_id: str,
                     provider_id: str, title: str, scope: str,
                     acceptance_criteria: str, signature: str,
                     due_at: str | None = None, price_minor: int | None = None,
                     currency: str | None = None) -> dict[str, Any]:
        if not all(v.strip() for v in (task_id, listing_id, buyer_id, provider_id,
                                       title, scope, acceptance_criteria, signature)):
            raise ValueError("task, listing, parties, scope, criteria and signature are required")
        if buyer_id == provider_id:
            raise ValueError("buyer and provider must be different participants")
        if price_minor is not None and price_minor < 0:
            raise ValueError("price_minor must be non-negative")
        if (price_minor is None) != (currency is None):
            raise ValueError("price and currency must be supplied together")
        if currency and (len(currency) != 3 or not currency.isalpha()):
            raise ValueError("currency must be a three-letter code")
        payload = self.offer_payload(
            task_id=task_id, listing_id=listing_id, buyer_id=buyer_id,
            provider_id=provider_id, title=title, scope=scope,
            acceptance_criteria=acceptance_criteria, due_at=due_at,
            price_minor=price_minor, currency=currency,
        )
        with self._connect() as db:
            listing = db.execute(
                "SELECT provider_id,status FROM service_listings WHERE listing_id=?",
                (listing_id,),
            ).fetchone()
            if listing is None or listing["status"] != "active" or listing["provider_id"] != provider_id:
                raise ValueError("task offer must reference an active listing owned by the provider")
            buyer_key = self._key(db, buyer_id)
            self._key(db, provider_id)
            if not self.verifier(buyer_key, _canonical(payload), signature):
                raise ValueError("buyer task-offer signature is invalid")
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                """INSERT INTO task_agreements VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'offered',NULL,?,?)""",
                (task_id, listing_id, buyer_id, provider_id, title, scope,
                 acceptance_criteria, due_at, price_minor, currency.upper() if currency else None,
                 json.dumps(payload, sort_keys=True), signature, now, now),
            )
            self._event(db, task_id, buyer_id, "offered", "buyer-signed task offer")
        return self.get(task_id)

    def respond(self, task_id: str, *, provider_id: str, decision: str,
                signature: str) -> dict[str, Any]:
        if decision not in {"accept", "decline"}:
            raise ValueError("decision must be accept or decline")
        with self._connect() as db:
            row = db.execute("SELECT * FROM task_agreements WHERE task_id=?", (task_id,)).fetchone()
            if row is None or row["provider_id"] != provider_id or row["status"] != "offered":
                raise ValueError("open offer not found or provider is not authorized")
            key = self._key(db, provider_id)
            import hashlib
            digest = hashlib.sha256(_canonical(json.loads(row["offer_payload"]))).hexdigest()
            payload = self.response_payload(task_id, provider_id, decision, digest)
            if not self.verifier(key, payload, signature):
                raise ValueError("provider response signature is invalid")
            status = "accepted" if decision == "accept" else "declined"
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                "UPDATE task_agreements SET status=?,provider_signature=?,updated_at=? WHERE task_id=?",
                (status, signature, now, task_id),
            )
            self._event(db, task_id, provider_id, status, "provider-signed offer response")
        return self.get(task_id)

    def withdraw(self, task_id: str, *, buyer_id: str, signature: str) -> None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM task_agreements WHERE task_id=?", (task_id,)).fetchone()
            if row is None or row["buyer_id"] != buyer_id or row["status"] != "offered":
                raise ValueError("open offer not found or buyer is not authorized")
            key = self._key(db, buyer_id)
            payload = _canonical({"version": "1", "event": "task_offer_withdrawal",
                                  "task_id": task_id, "buyer_id": buyer_id})
            if not self.verifier(key, payload, signature):
                raise ValueError("buyer withdrawal signature is invalid")
            now = datetime.now(timezone.utc).isoformat()
            db.execute("UPDATE task_agreements SET status='withdrawn',updated_at=? WHERE task_id=?",
                       (now, task_id))
            self._event(db, task_id, buyer_id, "withdrawn", "buyer-signed offer withdrawal")

    def get(self, task_id: str) -> dict[str, Any]:
        with self._connect() as db:
            row = db.execute("SELECT * FROM task_agreements WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            result = dict(row)
            result["offer"] = json.loads(result.pop("offer_payload"))
            return result

    def offers_for_provider(self, provider_id: str, *, status: str = "offered",
                            limit: int = 50) -> list[dict[str, Any]]:
        if status not in {"offered", "accepted", "declined", "withdrawn"} or not 1 <= limit <= 100:
            raise ValueError("invalid status or limit")
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT task_id,listing_id,buyer_id,provider_id,title,scope,acceptance_criteria,due_at,price_minor,currency,status,created_at FROM task_agreements WHERE provider_id=? AND status=? ORDER BY created_at DESC LIMIT ?",
                (provider_id, status, limit),
            ).fetchall()]

    def events(self, task_id: str) -> list[dict[str, Any]]:
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM task_agreement_events WHERE task_id=? ORDER BY created_at",
                (task_id,),
            ).fetchall()]
