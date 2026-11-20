"""AAE Pay Phase 1: simulation-only invoices and reconciliation.

This module is a local accounting prototype. Every event is simulated, non-cash,
non-transferable, and excluded from external revenue. It has no network, wallet,
provider, checkout, custody, or money-movement integration.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .financial_ledger import DoubleEntryLedger, FinancialLedgerError, IdempotencyConflict


class AaePayError(ValueError):
    """Invalid or unsafe AAE Pay operation."""


class AaePay:
    """Simulation-only invoice lifecycle backed by SQLite and the local journal."""

    def __init__(self, path: str | Path, ledger: DoubleEntryLedger) -> None:
        self.path = str(path)
        self.ledger = ledger
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS aae_pay_invoices (
                    invoice_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    terms_sha256 TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    gross_minor INTEGER NOT NULL CHECK(gross_minor > 0),
                    fee_minor INTEGER NOT NULL CHECK(fee_minor >= 0 AND fee_minor < gross_minor),
                    status TEXT NOT NULL CHECK(status IN
                      ('created','awaiting_payment','observed_pending','verified_settled',
                       'reconciled','delivered','reversed','expired')),
                    observation_id TEXT UNIQUE,
                    journal_transaction_id TEXT,
                    reversal_transaction_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS aae_pay_invoice_status
                  ON aae_pay_invoices(status, created_at);
            """)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _minor(value: object, *, zero: bool = False) -> bool:
        return (isinstance(value, int) and not isinstance(value, bool)
                and (value >= 0 if zero else value > 0)
                and value <= 9_223_372_036_854_775_807)

    @staticmethod
    def _currency(value: object) -> str:
        if (not isinstance(value, str) or len(value) != 3
                or not value.isascii() or not value.isalpha()):
            raise AaePayError("currency must be a three-letter code")
        return value.upper()

    def create_invoice(self, *, idempotency_key: str, agent_id: str,
                       currency: str, gross_minor: int, fee_minor: int) -> dict[str, Any]:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise AaePayError("idempotency_key is required")
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise AaePayError("agent_id is required")
        currency = self._currency(currency)
        if not self._minor(gross_minor) or not self._minor(fee_minor, zero=True):
            raise AaePayError("amounts must be valid positive minor units (fee may be zero)")
        if fee_minor >= gross_minor:
            raise AaePayError("fee must be smaller than gross amount")
        terms = {"agent_id": agent_id, "currency": currency,
                 "gross_minor": gross_minor, "fee_minor": fee_minor}
        digest = hashlib.sha256(json.dumps(
            terms, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        now = self._now()
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT invoice_id,terms_sha256 FROM aae_pay_invoices WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if row:
                if row[1] != digest:
                    raise IdempotencyConflict("invoice idempotency key reused with changed terms")
                db.commit()
                return self.get_invoice(str(row[0]))
            invoice_id = str(uuid.uuid4())
            db.execute("""INSERT INTO aae_pay_invoices
                (invoice_id,idempotency_key,terms_sha256,agent_id,currency,gross_minor,
                 fee_minor,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,'awaiting_payment',?,?)""",
                (invoice_id, idempotency_key, digest, agent_id, currency,
                 gross_minor, fee_minor, now, now))
            db.commit()
            return self.get_invoice(invoice_id)
        except sqlite3.Error as exc:
            db.rollback()
            raise AaePayError("invoice storage failed; no invoice was committed") from exc
        finally:
            db.close()

    def record_simulated_observation(self, *, invoice_id: str,
                                     observation_id: str, gross_minor: int,
                                     currency: str) -> dict[str, Any]:
        """Record a test fixture only; it is not external payment evidence."""
        if not isinstance(observation_id, str) or not observation_id.strip():
            raise AaePayError("observation_id is required")
        if not self._minor(gross_minor):
            raise AaePayError("observed amount must be positive minor units")
        currency = self._currency(currency)
        now = self._now()
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT status,gross_minor,currency,observation_id FROM aae_pay_invoices WHERE invoice_id=?",
                (invoice_id,),
            ).fetchone()
            if not row:
                raise AaePayError("unknown invoice")
            status, expected, expected_currency, old_observation = row
            if status == "observed_pending" and old_observation == observation_id:
                db.commit()
                return self.get_invoice(invoice_id)
            if status != "awaiting_payment":
                raise AaePayError("invoice is not awaiting payment")
            if gross_minor != expected or currency != expected_currency:
                raise AaePayError("simulated observation does not match invoice terms")
            db.execute("""UPDATE aae_pay_invoices SET status='observed_pending',
                observation_id=?,updated_at=? WHERE invoice_id=? AND status='awaiting_payment'""",
                (observation_id, now, invoice_id))
            db.commit()
            return self.get_invoice(invoice_id)
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise AaePayError("observation ID has already been used") from exc
        except sqlite3.Error as exc:
            db.rollback()
            raise AaePayError("observation storage failed") from exc
        finally:
            db.close()

    def verify_simulated_settlement(self, invoice_id: str) -> dict[str, Any]:
        """Advance a simulated test fixture; never verifies a real payment."""
        with sqlite3.connect(self.path) as db:
            cur = db.execute("""UPDATE aae_pay_invoices SET status='verified_settled',
                updated_at=? WHERE invoice_id=? AND status='observed_pending'""",
                (self._now(), invoice_id))
            if cur.rowcount != 1:
                row = db.execute("SELECT status FROM aae_pay_invoices WHERE invoice_id=?",
                                 (invoice_id,)).fetchone()
                if not row:
                    raise AaePayError("unknown invoice")
                if row[0] != "verified_settled":
                    raise AaePayError("only an observed simulated invoice can be verified")
        return self.get_invoice(invoice_id)

    def reconcile(self, invoice_id: str) -> dict[str, Any]:
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            raise AaePayError("unknown invoice")
        if invoice["status"] in {"reconciled", "delivered"}:
            return invoice
        if invoice["status"] != "verified_settled":
            raise AaePayError("only verified simulated settlements can be reconciled")
        gross, fee = invoice["gross_minor"], invoice["fee_minor"]
        net = gross - fee
        lines = [
            {"account_id": "treasury:simulated-clearing", "direction": "debit",
             "amount_minor": gross, "reference": invoice_id},
            {"account_id": "platform-fees:simulated", "direction": "credit",
             "amount_minor": fee, "reference": invoice_id},
            {"account_id": f"agent-payable:simulated:{invoice['agent_id']}",
             "direction": "credit", "amount_minor": net, "reference": invoice_id},
        ]
        journal_id = self.ledger.post(
            idempotency_key=f"aae-pay-reconcile:{invoice_id}",
            description=f"SIMULATED AAE Pay invoice reconciliation {invoice_id}",
            currency=invoice["currency"], lines=lines, simulated=True,
        )
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""UPDATE aae_pay_invoices SET status='reconciled',
                journal_transaction_id=?,updated_at=?
                WHERE invoice_id=? AND status='verified_settled'""",
                (journal_id, self._now(), invoice_id))
            db.commit()
        return self.get_invoice(invoice_id)

    def mark_delivered(self, invoice_id: str) -> dict[str, Any]:
        with sqlite3.connect(self.path) as db:
            cur = db.execute("""UPDATE aae_pay_invoices SET status='delivered',updated_at=?
                WHERE invoice_id=? AND status='reconciled'""", (self._now(), invoice_id))
            if cur.rowcount != 1:
                row = db.execute("SELECT status FROM aae_pay_invoices WHERE invoice_id=?",
                                 (invoice_id,)).fetchone()
                if not row:
                    raise AaePayError("unknown invoice")
                if row[0] != "delivered":
                    raise AaePayError("delivery requires reconciled simulated accounting")
        return self.get_invoice(invoice_id)

    def reverse(self, invoice_id: str, *, reason: str) -> dict[str, Any]:
        if not isinstance(reason, str) or not reason.strip():
            raise AaePayError("a reversal reason is required")
        invoice = self.get_invoice(invoice_id)
        if not invoice:
            raise AaePayError("unknown invoice")
        if invoice["status"] == "reversed":
            return invoice
        if invoice["status"] not in {"reconciled", "delivered"}:
            raise AaePayError("only reconciled invoices can be reversed")
        original = self.ledger.transaction(invoice["journal_transaction_id"])
        if not original or not original["simulated"]:
            raise AaePayError("original simulated journal transaction is missing")
        inverse = [
            {"account_id": line["account_id"],
             "direction": "credit" if line["direction"] == "debit" else "debit",
             "amount_minor": line["amount_minor"], "reference": invoice_id}
            for line in original["lines"]
        ]
        reversal_id = self.ledger.post(
            idempotency_key=f"aae-pay-reversal:{invoice_id}",
            description=f"SIMULATED AAE Pay reversal: {reason.strip()}",
            currency=invoice["currency"], lines=inverse, simulated=True,
        )
        with sqlite3.connect(self.path, timeout=10, isolation_level=None) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""UPDATE aae_pay_invoices SET status='reversed',
                reversal_transaction_id=?,updated_at=? WHERE invoice_id=?
                AND status IN ('reconciled','delivered')""",
                (reversal_id, self._now(), invoice_id))
            db.commit()
        return self.get_invoice(invoice_id)

    def get_invoice(self, invoice_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM aae_pay_invoices WHERE invoice_id=?",
                             (invoice_id,)).fetchone()
        return dict(row) if row else None

    def list_invoices(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise AaePayError("limit must be between 1 and 500")
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT * FROM aae_pay_invoices ORDER BY created_at DESC LIMIT ?",
                              (limit,)).fetchall()
        return [dict(row) for row in rows]
