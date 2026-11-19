"""Owner-configured autonomous spending budgets for agent wallets.

The policy store reserves bounded spend before an external signer is invoked.
It never holds keys, signs transactions, or broadcasts funds. A production signer
must enforce the same policy at the custody boundary.
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class SpendPolicy:
    agent_id: str
    network: str
    asset: str
    daily_limit_minor: int
    per_transaction_limit_minor: int
    allowed_destinations: tuple[str, ...]
    enabled: bool = True


@dataclass(frozen=True)
class SpendReservation:
    reservation_id: str
    agent_id: str
    network: str
    asset: str
    destination: str
    amount_minor: int
    status: str


@runtime_checkable
class PolicyBoundSigner(Protocol):
    """Production signer boundary; implementation must independently enforce policy."""

    def sign_and_broadcast(self, *, agent_id: str, network: str, asset: str,
                           destination: str, amount_minor: int,
                           idempotency_key: str) -> str:
        """Return a transaction hash, or raise without exposing key material."""
        ...


class WalletSpendController:
    """Budget reservation and settlement state machine; no custody functionality."""

    def __init__(self, path: str | Path = "./data/agent_spending.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS agent_spend_policies (
                    agent_id TEXT NOT NULL,
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    daily_limit_minor INTEGER NOT NULL CHECK(daily_limit_minor > 0),
                    per_transaction_limit_minor INTEGER NOT NULL CHECK(per_transaction_limit_minor > 0),
                    allowed_destinations_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(agent_id, network, asset)
                );
                CREATE TABLE IF NOT EXISTS agent_spend_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('reserved','broadcast','settled','cancelled')),
                    tx_hash TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    settled_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_spend_daily
                    ON agent_spend_reservations(agent_id, network, asset, created_at, status);
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def configure_policy(self, policy: SpendPolicy) -> None:
        if not all(isinstance(v, str) and v.strip() for v in
                   (policy.agent_id, policy.network, policy.asset)):
            raise ValueError("agent, network and asset are required")
        if not policy.allowed_destinations or any(
            not isinstance(v, str) or not v.strip() for v in policy.allowed_destinations
        ):
            raise ValueError("at least one explicit destination allowlist entry is required")
        for name, value in (("daily_limit_minor", policy.daily_limit_minor),
                            ("per_transaction_limit_minor", policy.per_transaction_limit_minor)):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if policy.per_transaction_limit_minor > policy.daily_limit_minor:
            raise ValueError("per-transaction limit cannot exceed daily limit")
        asset = policy.asset.upper()
        with closing(self._connect()) as db:
            existing = db.execute(
                """SELECT 1 FROM agent_spend_reservations
                   WHERE agent_id=? AND network=? AND asset=? AND status IN ('reserved','broadcast')""",
                (policy.agent_id, policy.network, asset),
            ).fetchone()
            if existing:
                raise ValueError("cannot replace policy while spend reservations are pending")
            import json
            db.execute(
                """INSERT INTO agent_spend_policies VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(agent_id,network,asset) DO UPDATE SET
                   daily_limit_minor=excluded.daily_limit_minor,
                   per_transaction_limit_minor=excluded.per_transaction_limit_minor,
                   allowed_destinations_json=excluded.allowed_destinations_json,
                   enabled=excluded.enabled, updated_at=excluded.updated_at""",
                (policy.agent_id, policy.network, asset, policy.daily_limit_minor,
                 policy.per_transaction_limit_minor, json.dumps(sorted(set(policy.allowed_destinations))),
                 int(policy.enabled), _iso(_now())),
            )

    def pause(self, agent_id: str, network: str, asset: str) -> None:
        with closing(self._connect()) as db:
            cur = db.execute(
                """UPDATE agent_spend_policies SET enabled=0, updated_at=?
                   WHERE agent_id=? AND network=? AND asset=?""",
                (_iso(_now()), agent_id, network, asset.upper()),
            )
            if cur.rowcount != 1:
                raise ValueError("spend policy not found")

    def reserve(self, agent_id: str, network: str, asset: str, destination: str,
                amount_minor: int, *, idempotency_key: str) -> SpendReservation:
        if not all(isinstance(v, str) and v.strip() for v in
                   (agent_id, network, asset, destination, idempotency_key)):
            raise ValueError("agent, network, asset, destination and idempotency key are required")
        if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
            raise ValueError("amount_minor must be a positive integer")
        asset = asset.upper()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM agent_spend_reservations WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if existing:
                if (existing["agent_id"], existing["network"], existing["asset"],
                    existing["destination"], existing["amount_minor"]) != (
                    agent_id, network, asset, destination, amount_minor
                ):
                    db.rollback()
                    raise ValueError("idempotency key already used for a different spend")
                db.commit()
                return SpendReservation(existing["reservation_id"], agent_id, network,
                                        asset, destination, amount_minor, existing["status"])
            policy = db.execute(
                """SELECT * FROM agent_spend_policies
                   WHERE agent_id=? AND network=? AND asset=?""",
                (agent_id, network, asset),
            ).fetchone()
            if not policy or not policy["enabled"]:
                db.rollback()
                raise ValueError("no enabled spend policy for this agent, network and asset")
            import json
            if destination not in json.loads(policy["allowed_destinations_json"]):
                db.rollback()
                raise ValueError("destination is not allowlisted")
            if amount_minor > policy["per_transaction_limit_minor"]:
                db.rollback()
                raise ValueError("spend exceeds per-transaction limit")
            start = _iso(_now().replace(hour=0, minute=0, second=0, microsecond=0))
            totals = db.execute(
                """SELECT COALESCE(SUM(amount_minor),0) AS total
                   FROM agent_spend_reservations
                   WHERE agent_id=? AND network=? AND asset=? AND created_at>=?
                     AND status IN ('reserved','broadcast','settled')""",
                (agent_id, network, asset, start),
            ).fetchone()
            if int(totals["total"]) + amount_minor > policy["daily_limit_minor"]:
                db.rollback()
                raise ValueError("spend exceeds remaining daily budget")
            reservation_id = "spend_" + uuid.uuid4().hex
            db.execute(
                """INSERT INTO agent_spend_reservations
                   VALUES(?,?,?,?,?,?,?,'reserved',NULL,?,NULL)""",
                (reservation_id, agent_id, network, asset, destination,
                 amount_minor, idempotency_key, _iso(_now())),
            )
            db.commit()
            return SpendReservation(reservation_id, agent_id, network, asset,
                                    destination, amount_minor, "reserved")

    def mark_broadcast(self, reservation_id: str, tx_hash: str) -> None:
        if not tx_hash.strip():
            raise ValueError("transaction hash is required")
        with closing(self._connect()) as db:
            cur = db.execute(
                """UPDATE agent_spend_reservations SET status='broadcast', tx_hash=?
                   WHERE reservation_id=? AND status='reserved'""",
                (tx_hash, reservation_id),
            )
            if cur.rowcount != 1:
                raise ValueError("reservation is not in reserved state or transaction hash is reused")

    def mark_settled(self, reservation_id: str, *, tx_hash: str,
                     verified: bool, source: str, destination: str,
                     amount_minor: int) -> None:
        if verified is not True:
            raise ValueError("settlement must be independently verified on-chain")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM agent_spend_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            if not row or row["status"] != "broadcast":
                db.rollback()
                raise ValueError("broadcast reservation not found")
            if (row["tx_hash"] != tx_hash or row["agent_id"] != source
                    or row["destination"] != destination
                    or row["amount_minor"] != amount_minor):
                db.rollback()
                raise ValueError("verified settlement does not match the reserved transfer")
            db.execute(
                """UPDATE agent_spend_reservations SET status='settled', settled_at=?
                   WHERE reservation_id=? AND status='broadcast'""",
                (_iso(_now()), reservation_id),
            )
            db.commit()

    def cancel(self, reservation_id: str) -> None:
        with closing(self._connect()) as db:
            cur = db.execute(
                """UPDATE agent_spend_reservations SET status='cancelled'
                   WHERE reservation_id=? AND status='reserved'""",
                (reservation_id,),
            )
            if cur.rowcount != 1:
                raise ValueError("only an unbroadcast reservation can be cancelled")

    def get_reservation(self, reservation_id: str) -> SpendReservation | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM agent_spend_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
        if not row:
            return None
        return SpendReservation(row["reservation_id"], row["agent_id"], row["network"],
                                row["asset"], row["destination"], row["amount_minor"],
                                row["status"])
