"""Double-entry journal for AAE's local, simulated financial accounting.

This module never connects to a wallet, provider, bank, or chain. It refuses
non-simulated postings. A real-money ledger requires a separately reviewed
settlement and authorization implementation.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping


class FinancialLedgerError(ValueError):
    """Invalid or unsafe journal operation."""


class IdempotencyConflict(FinancialLedgerError):
    """An idempotency key was reused with different posting terms."""


class DoubleEntryLedger:
    """Atomic, append-only double-entry journal backed by SQLite.

    Account balances are returned as debit-minus-credit. Account normal
    balances are an accounting/reporting concern and are not inferred here.
    Every transaction is marked simulated; no live money is represented.
    """

    def __init__(self, path: str | Path = "./data/financial-ledger.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS financial_journal_transactions (
                    transaction_id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    description TEXT NOT NULL,
                    currency TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    simulated INTEGER NOT NULL CHECK (simulated = 1),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS financial_journal_lines (
                    line_id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL REFERENCES financial_journal_transactions(transaction_id),
                    account_id TEXT NOT NULL,
                    direction TEXT NOT NULL CHECK (direction IN ('debit', 'credit')),
                    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
                    reference TEXT
                );
                CREATE INDEX IF NOT EXISTS financial_journal_lines_account
                    ON financial_journal_lines(account_id, transaction_id);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @staticmethod
    def _validate(currency: str, description: str, idempotency_key: str,
                  lines: Iterable[Mapping[str, object]]) -> tuple[str, list[dict[str, object]]]:
        if not isinstance(currency, str) or len(currency) != 3 or not currency.isascii() or not currency.isalpha():
            raise FinancialLedgerError("currency must be a three-letter code")
        if not isinstance(description, str) or not description.strip():
            raise FinancialLedgerError("description is required")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise FinancialLedgerError("idempotency_key is required")
        normalized: list[dict[str, object]] = []
        for line in lines:
            account_id = line.get("account_id")
            direction = line.get("direction")
            amount = line.get("amount_minor")
            reference = line.get("reference")
            if not isinstance(account_id, str) or not account_id.strip():
                raise FinancialLedgerError("each line requires an account_id")
            if not isinstance(direction, str) or direction not in {"debit", "credit"}:
                raise FinancialLedgerError("line direction must be debit or credit")
            if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
                raise FinancialLedgerError("line amount_minor must be a positive signed-64-bit integer")
            if reference is not None and not isinstance(reference, str):
                raise FinancialLedgerError("line reference must be text or null")
            normalized.append({
                "account_id": account_id.strip(),
                "direction": direction,
                "amount_minor": amount,
                "reference": reference,
            })
        if len(normalized) < 2:
            raise FinancialLedgerError("a journal transaction requires at least two lines")
        debits = sum(int(x["amount_minor"]) for x in normalized if x["direction"] == "debit")
        credits = sum(int(x["amount_minor"]) for x in normalized if x["direction"] == "credit")
        if debits != credits:
            raise FinancialLedgerError("journal transaction is not balanced")
        return currency.upper(), normalized

    def post(self, *, idempotency_key: str, description: str, currency: str,
             lines: Iterable[Mapping[str, object]], simulated: bool = True) -> str:
        """Post a balanced simulated transaction and return its stable ID."""
        if simulated is not True:
            raise FinancialLedgerError("real-money postings are disabled")
        currency, normalized = self._validate(currency, description, idempotency_key, lines)
        payload = {
            "description": description.strip(),
            "currency": currency,
            "lines": normalized,
            "simulated": True,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT transaction_id,payload_sha256 FROM financial_journal_transactions WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if existing[1] != digest:
                    db.rollback()
                    raise IdempotencyConflict("idempotency key reused with changed journal terms")
                db.commit()
                return str(existing[0])

            transaction_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).isoformat()
            db.execute(
                """INSERT INTO financial_journal_transactions
                   (transaction_id,idempotency_key,description,currency,payload_sha256,simulated,created_at)
                   VALUES(?,?,?,?,?,1,?)""",
                (transaction_id, idempotency_key, description.strip(), currency, digest, created_at),
            )
            db.executemany(
                """INSERT INTO financial_journal_lines
                   (line_id,transaction_id,account_id,direction,amount_minor,reference)
                   VALUES(?,?,?,?,?,?)""",
                [
                    (str(uuid.uuid4()), transaction_id, line["account_id"],
                     line["direction"], line["amount_minor"], line["reference"])
                    for line in normalized
                ],
            )
            db.commit()
            return transaction_id
        except sqlite3.Error as exc:
            db.rollback()
            raise FinancialLedgerError("journal storage failed; no posting was committed") from exc
        finally:
            db.close()

    def balance_minor(self, account_id: str, currency: str = "USD") -> int:
        if not account_id.strip():
            raise FinancialLedgerError("account_id is required")
        with self._connect() as db:
            row = db.execute(
                """SELECT COALESCE(SUM(CASE direction WHEN 'debit' THEN amount_minor
                                                       ELSE -amount_minor END),0)
                   FROM financial_journal_lines l
                   JOIN financial_journal_transactions t USING(transaction_id)
                   WHERE l.account_id=? AND t.currency=? AND t.simulated=1""",
                (account_id, currency.upper()),
            ).fetchone()
        return int(row[0])

    def transaction(self, transaction_id: str) -> dict[str, object] | None:
        with self._connect() as db:
            header = db.execute(
                """SELECT transaction_id,idempotency_key,description,currency,simulated,created_at
                   FROM financial_journal_transactions WHERE transaction_id=?""",
                (transaction_id,),
            ).fetchone()
            if header is None:
                return None
            rows = db.execute(
                """SELECT account_id,direction,amount_minor,reference
                   FROM financial_journal_lines WHERE transaction_id=? ORDER BY rowid""",
                (transaction_id,),
            ).fetchall()
        return {
            "transaction_id": header[0],
            "idempotency_key": header[1],
            "description": header[2],
            "currency": header[3],
            "simulated": bool(header[4]),
            "created_at": header[5],
            "lines": [
                {"account_id": row[0], "direction": row[1],
                 "amount_minor": row[2], "reference": row[3]}
                for row in rows
            ],
        }
