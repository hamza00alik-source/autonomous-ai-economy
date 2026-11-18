"""Policy-enforced simulated operating-budget reservations and expense settlement.

This module is deliberately local and simulated-only. It never signs, submits,
or broadcasts an external payment. A settled expense is an accounting entry,
not a transfer to a provider.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .financial_ledger import DoubleEntryLedger, FinancialLedgerError, IdempotencyConflict


class FinancialSpendingError(ValueError):
    """A spend request is invalid, unauthorized, or over budget."""


class AgentSpending:
    """Durable reservation service bound to the current signed owner policy."""

    def __init__(self, ledger: DoubleEntryLedger, policy_store: Any,
                 path: str | Path = "./data/financial-spending.sqlite3") -> None:
        self.ledger = ledger
        self.policies = policy_store
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_expense_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    terms_sha256 TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    policy_id TEXT NOT NULL,
                    policy_version INTEGER NOT NULL,
                    destination TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                    spend_day TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('reserved','settled','released','expired')),
                    expires_at TEXT NOT NULL,
                    journal_transaction_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS agent_expense_daily
                    ON agent_expense_reservations(agent_id,currency,spend_day,status);
            """)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _amount(value: object) -> bool:
        return (isinstance(value, int) and not isinstance(value, bool)
                and 0 < value <= 9_223_372_036_854_775_807)

    def _authorized_policy(self, agent_id: str, policy_id: str) -> dict[str, Any]:
        policy = self.policies.get(agent_id, policy_id)
        if not policy or not policy.get("currently_authorized"):
            raise FinancialSpendingError("no currently authorized owner-signed financial policy")
        body = policy.get("policy")
        if not isinstance(body, dict) or body.get("agent_id") != agent_id:
            raise FinancialSpendingError("financial policy agent binding is invalid")
        return body

    def reserve(self, *, agent_id: str, policy_id: str, destination: str,
                currency: str, amount_minor: int, idempotency_key: str,
                ttl_seconds: int = 900) -> dict[str, Any]:
        """Reserve a bounded expense against cleared simulated agent budget."""
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise FinancialSpendingError("agent_id is required")
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise FinancialSpendingError("policy_id is required")
        if not isinstance(destination, str) or not destination.strip():
            raise FinancialSpendingError("exact destination is required")
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise FinancialSpendingError("currency must be a three-letter code")
        currency = currency.upper()
        if not self._amount(amount_minor):
            raise FinancialSpendingError("amount_minor must be a positive signed-64-bit integer")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise FinancialSpendingError("idempotency_key is required")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 1 <= ttl_seconds <= 86_400:
            raise FinancialSpendingError("ttl_seconds must be between 1 and 86400")

        policy = self._authorized_policy(agent_id, policy_id)
        if currency != policy["currency"]:
            raise FinancialSpendingError("spend currency does not match signed policy")
        if destination not in policy["allowed_destinations"]:
            raise FinancialSpendingError("destination is not exactly allowlisted")
        if amount_minor > policy["per_transaction_limit_minor"]:
            raise FinancialSpendingError("per-transaction spending limit exceeded")

        now = self._now()
        now_text = now.isoformat()
        day = now.date().isoformat()
        terms = {
            "agent_id": agent_id, "policy_id": policy_id,
            "policy_version": policy["version"], "destination": destination,
            "currency": currency, "amount_minor": amount_minor,
            "spend_day": day, "ttl_seconds": ttl_seconds,
        }
        digest = hashlib.sha256(json.dumps(terms, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        reservation_id = str(uuid.uuid4())
        expires = (now + timedelta(seconds=ttl_seconds)).isoformat()
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT reservation_id,terms_sha256 FROM agent_expense_reservations WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing[1] != digest:
                    raise FinancialSpendingError("idempotency key reused with changed expense terms")
                db.commit()
                return self.get(str(existing[0]))

            # Recheck policy immediately before reserving, so rotation/suspension fails closed.
            current = self._authorized_policy(agent_id, policy_id)
            if current != policy:
                raise FinancialSpendingError("financial policy changed during reservation")
            reserved_row = db.execute(
                """SELECT COALESCE(SUM(amount_minor),0) FROM agent_expense_reservations
                   WHERE agent_id=? AND currency=? AND status='reserved' AND expires_at>?""",
                (agent_id, currency, now_text),
            ).fetchone()
            daily_row = db.execute(
                """SELECT COALESCE(SUM(amount_minor),0) FROM agent_expense_reservations
                   WHERE agent_id=? AND currency=? AND spend_day=? AND status IN ('reserved','settled')
                   AND (status='settled' OR expires_at>?)""",
                (agent_id, currency, day, now_text),
            ).fetchone()
            reserved = int(reserved_row[0])
            daily_used = int(daily_row[0])
            budget_balance = self.ledger.balance_minor(f"agent-budget:{agent_id}", currency)
            if amount_minor > budget_balance - reserved:
                raise FinancialSpendingError("insufficient unreserved agent operating budget")
            if amount_minor > policy["daily_spend_limit_minor"] - daily_used:
                raise FinancialSpendingError("daily spending limit exceeded")
            db.execute(
                """INSERT INTO agent_expense_reservations
                   (reservation_id,idempotency_key,terms_sha256,agent_id,policy_id,policy_version,
                    destination,currency,amount_minor,spend_day,status,expires_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,'reserved',?,?,?)""",
                (reservation_id, idempotency_key, digest, agent_id, policy_id,
                 policy["version"], destination, currency, amount_minor, day,
                 expires, now_text, now_text),
            )
            db.commit()
            return self.get(reservation_id)
        except sqlite3.Error as exc:
            db.rollback()
            raise FinancialSpendingError("reservation storage failed; no reservation was committed") from exc
        finally:
            db.close()

    def settle(self, reservation_id: str) -> dict[str, Any]:
        """Settle a reservation into the simulated journal exactly once."""
        reservation = self.get(reservation_id)
        if reservation is None:
            raise FinancialSpendingError("unknown expense reservation")
        if reservation["status"] == "settled":
            return reservation
        if reservation["status"] != "reserved":
            raise FinancialSpendingError("only an active reservation can be settled")
        now = self._now()
        if datetime.fromisoformat(reservation["expires_at"]) <= now:
            self._transition(reservation_id, "expired")
            raise FinancialSpendingError("expense reservation expired")
        policy = self._authorized_policy(reservation["agent_id"], reservation["policy_id"])
        if policy["version"] != reservation["policy_version"]:
            raise FinancialSpendingError("reservation policy was superseded")
        # Recheck all signed limits and destination at execution time.
        if (reservation["destination"] not in policy["allowed_destinations"]
                or reservation["amount_minor"] > policy["per_transaction_limit_minor"]
                or reservation["currency"] != policy["currency"]):
            raise FinancialSpendingError("current financial policy no longer authorizes this expense")
        key = f"agent-expense:{reservation_id}"
        journal_id = self.ledger.post(
            idempotency_key=key,
            description=f"Simulated agent expense: {reservation['destination']}",
            currency=reservation["currency"],
            lines=[
                {"account_id": f"operating-expense:{reservation['destination']}",
                 "direction": "debit", "amount_minor": reservation["amount_minor"],
                 "reference": reservation_id},
                {"account_id": f"agent-budget:{reservation['agent_id']}",
                 "direction": "credit", "amount_minor": reservation["amount_minor"],
                 "reference": reservation_id},
            ],
            simulated=True,
        )
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,journal_transaction_id FROM agent_expense_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if row is None:
                raise FinancialSpendingError("reservation disappeared during settlement")
            if row[0] == "settled":
                if row[1] != journal_id:
                    raise FinancialSpendingError("settled reservation journal mismatch")
            elif row[0] != "reserved":
                raise FinancialSpendingError("reservation is no longer active")
            else:
                db.execute(
                    """UPDATE agent_expense_reservations SET status='settled',
                       journal_transaction_id=?,updated_at=? WHERE reservation_id=? AND status='reserved'""",
                    (journal_id, self._now().isoformat(), reservation_id),
                )
            db.commit()
        except sqlite3.Error as exc:
            db.rollback()
            raise FinancialSpendingError("expense settlement state update failed; retry is safe") from exc
        finally:
            db.close()
        return self.get(reservation_id)

    def release(self, reservation_id: str) -> dict[str, Any]:
        """Release an unspent reservation; settled expenses cannot be reversed here."""
        return self._transition(reservation_id, "released")

    def expire(self) -> int:
        """Mark all elapsed reservations expired and return the number changed."""
        now = self._now().isoformat()
        with sqlite3.connect(self.path, timeout=10) as db:
            cursor = db.execute(
                """UPDATE agent_expense_reservations SET status='expired',updated_at=?
                   WHERE status='reserved' AND expires_at<=?""", (now, now)
            )
            return int(cursor.rowcount)

    def _transition(self, reservation_id: str, target: str) -> dict[str, Any]:
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status FROM agent_expense_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if row is None:
                db.rollback()
                raise FinancialSpendingError("unknown expense reservation")
            if row[0] == target:
                db.commit()
                return self.get(reservation_id)
            if row[0] != "reserved" or target not in {"released", "expired"}:
                db.rollback()
                raise FinancialSpendingError("only an active reservation can be released or expired")
            db.execute(
                "UPDATE agent_expense_reservations SET status=?,updated_at=? WHERE reservation_id=?",
                (target, self._now().isoformat(), reservation_id),
            )
            db.commit()
        return self.get(reservation_id)

    def get(self, reservation_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute(
                """SELECT reservation_id,idempotency_key,agent_id,policy_id,policy_version,
                          destination,currency,amount_minor,spend_day,status,expires_at,
                          journal_transaction_id,created_at,updated_at
                   FROM agent_expense_reservations WHERE reservation_id=?""",
                (reservation_id,),
            ).fetchone()
        return dict(row) if row else None
