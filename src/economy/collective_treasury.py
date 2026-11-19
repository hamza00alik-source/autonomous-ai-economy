"""Single-wallet treasury with agent-level virtual sub-ledgers.

The blockchain wallet belongs to the AAE treasury, not to individual agents.
Agents receive internal balances; every external movement is reconciled against
verified chain evidence. This module never stores private keys or trusts LLM claims.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .agent_finance import VerifiedTransfer


@dataclass(frozen=True)
class TreasuryWallet:
    provider: str
    provider_wallet_id: str
    network: str
    asset: str
    address: str


class CollectiveTreasuryStore:
    """One on-chain wallet per network/asset, with isolated virtual agent balances."""

    def __init__(self, path: str | Path = "./data/collective_treasury.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS treasury_wallets (
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    provider_wallet_id TEXT NOT NULL,
                    address TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(network, asset),
                    UNIQUE(network, asset, address)
                );
                CREATE TABLE IF NOT EXISTS treasury_agents (
                    agent_id TEXT NOT NULL,
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    daily_limit_minor INTEGER NOT NULL CHECK(daily_limit_minor > 0),
                    per_tx_limit_minor INTEGER NOT NULL CHECK(per_tx_limit_minor > 0),
                    allowed_destinations_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
                    PRIMARY KEY(agent_id, network, asset)
                );
                CREATE TABLE IF NOT EXISTS treasury_entries (
                    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    entry_type TEXT NOT NULL CHECK(entry_type IN
                        ('receipt','expense','attribution_out','attribution_in','owner_share','reserve')),
                    direction TEXT NOT NULL CHECK(direction IN ('credit','debit')),
                    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                    tx_hash TEXT,
                    transfer_ref TEXT,
                    period_id TEXT NOT NULL,
                    memo TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_treasury_chain_event
                    ON treasury_entries(network, tx_hash, transfer_ref, entry_type)
                    WHERE tx_hash IS NOT NULL AND transfer_ref IS NOT NULL
                      AND entry_type='receipt';
                CREATE TABLE IF NOT EXISTS treasury_receipts (
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    tx_hash TEXT NOT NULL,
                    transfer_ref TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                    source_address TEXT NOT NULL,
                    destination_address TEXT NOT NULL,
                    attribution_ref TEXT,
                    attributed_agent_id TEXT,
                    status TEXT NOT NULL CHECK(status IN ('unallocated','allocated')),
                    period_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(network, tx_hash, transfer_ref)
                );
                CREATE TABLE IF NOT EXISTS treasury_pool_events (
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    tx_hash TEXT NOT NULL,
                    transfer_ref TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN ('receipt','expense')),
                    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(network, asset, tx_hash, transfer_ref, event_type)
                );
                CREATE TABLE IF NOT EXISTS treasury_payment_intents (
                    attribution_ref TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    expected_amount_minor INTEGER NOT NULL CHECK(expected_amount_minor > 0),
                    status TEXT NOT NULL CHECK(status IN ('pending','settled')),
                    settled_tx_hash TEXT,
                    settled_transfer_ref TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS treasury_spend_reservations (
                    reservation_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL CHECK(status IN ('reserved','broadcast','settled','cancelled','uncertain')),
                    tx_hash TEXT UNIQUE,
                    period_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS idx_treasury_spend_daily
                    ON treasury_spend_reservations(agent_id, network, asset, created_at, status);
                CREATE TABLE IF NOT EXISTS treasury_period_closes (
                    close_key TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    period_id TEXT NOT NULL,
                    income_minor INTEGER NOT NULL,
                    expenses_minor INTEGER NOT NULL,
                    net_profit_minor INTEGER NOT NULL,
                    reserve_minor INTEGER NOT NULL,
                    owner_share_minor INTEGER NOT NULL,
                    agent_retained_minor INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(agent_id, network, asset, period_id)
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=20000")
        return db

    @staticmethod
    def _required(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} is required")
        return value.strip()

    def register_treasury_wallet(self, wallet: TreasuryWallet) -> None:
        network = self._required(wallet.network, "network")
        asset = self._required(wallet.asset, "asset").upper()
        provider = self._required(wallet.provider, "provider")
        wallet_id = self._required(wallet.provider_wallet_id, "provider_wallet_id")
        address = self._required(wallet.address, "address")
        with closing(self._connect()) as db:
            existing = db.execute(
                "SELECT * FROM treasury_wallets WHERE network=? AND asset=?",
                (network, asset),
            ).fetchone()
            if existing:
                if (existing["provider"], existing["provider_wallet_id"], existing["address"]) != (
                    provider, wallet_id, address
                ):
                    raise ValueError("a different collective treasury wallet is already registered")
                return
            db.execute(
                "INSERT INTO treasury_wallets(network,asset,provider,provider_wallet_id,address) VALUES(?,?,?,?,?)",
                (network, asset, provider, wallet_id, address),
            )

    def treasury_wallet(self, network: str, asset: str) -> TreasuryWallet | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM treasury_wallets WHERE network=? AND asset=?",
                (network, asset.upper()),
            ).fetchone()
        return TreasuryWallet(row["provider"], row["provider_wallet_id"], row["network"],
                              row["asset"], row["address"]) if row else None

    def add_agent(self, agent_id: str, network: str, asset: str, *,
                  daily_limit_minor: int, per_tx_limit_minor: int,
                  allowed_destinations: tuple[str, ...]) -> None:
        agent_id = self._required(agent_id, "agent_id")
        network = self._required(network, "network")
        asset = self._required(asset, "asset").upper()
        if not self.treasury_wallet(network, asset):
            raise ValueError("collective treasury wallet must be registered first")
        for field, amount in (("daily_limit_minor", daily_limit_minor),
                              ("per_tx_limit_minor", per_tx_limit_minor)):
            if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
                raise ValueError(f"{field} must be a positive integer")
        if per_tx_limit_minor > daily_limit_minor:
            raise ValueError("per-transaction limit cannot exceed daily limit")
        if not allowed_destinations or any(not isinstance(v, str) or not v.strip()
                                            for v in allowed_destinations):
            raise ValueError("explicit destination allowlist is required")
        with closing(self._connect()) as db:
            db.execute(
                """INSERT INTO treasury_agents VALUES(?,?,?,?,?,?,1)
                   ON CONFLICT(agent_id,network,asset) DO UPDATE SET
                   daily_limit_minor=excluded.daily_limit_minor,
                   per_tx_limit_minor=excluded.per_tx_limit_minor,
                   allowed_destinations_json=excluded.allowed_destinations_json""",
                (agent_id, network, asset, daily_limit_minor, per_tx_limit_minor,
                 json.dumps(sorted(set(allowed_destinations)))),
            )

    def pause_agent(self, agent_id: str, network: str, asset: str) -> None:
        with closing(self._connect()) as db:
            cur = db.execute(
                "UPDATE treasury_agents SET enabled=0 WHERE agent_id=? AND network=? AND asset=?",
                (agent_id, network, asset.upper()),
            )
            if cur.rowcount != 1:
                raise ValueError("agent treasury policy not found")

    def _insert_entry(self, db: sqlite3.Connection, account_id: str, network: str,
                      asset: str, entry_type: str, direction: str, amount: int,
                      period_id: str, memo: str, tx_hash: str | None = None,
                      transfer_ref: str | None = None) -> None:
        db.execute(
            """INSERT INTO treasury_entries
               (account_id,network,asset,entry_type,direction,amount_minor,tx_hash,transfer_ref,period_id,memo)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (account_id, network, asset, entry_type, direction, amount, tx_hash,
             transfer_ref, period_id, memo),
        )

    @staticmethod
    def _validate_transfer(transfer: VerifiedTransfer) -> None:
        if transfer.verified is not True:
            raise ValueError("transfer must be independently verified and finalized")
        if not all(isinstance(v, str) and v.strip() for v in
                   (transfer.network, transfer.asset, transfer.tx_hash,
                    transfer.transfer_ref, transfer.destination)):
            raise ValueError("verified transfer identity and destination are required")
        if isinstance(transfer.amount_minor, bool) or not isinstance(transfer.amount_minor, int) or transfer.amount_minor <= 0:
            raise ValueError("transfer amount must be a positive integer")
        if isinstance(transfer.confirmations, bool) or not isinstance(transfer.confirmations, int) or transfer.confirmations < 1:
            raise ValueError("transfer must have at least one confirmation")

    def create_payment_intent(self, agent_id: str, network: str, asset: str,
                              expected_amount_minor: int, *, attribution_ref: str) -> None:
        """Create the trusted internal mapping needed to attribute a shared-wallet deposit."""
        if isinstance(expected_amount_minor, bool) or not isinstance(expected_amount_minor, int) or expected_amount_minor <= 0:
            raise ValueError("expected_amount_minor must be a positive integer")
        agent_id = self._required(agent_id, "agent_id")
        network = self._required(network, "network")
        asset = self._required(asset, "asset").upper()
        attribution_ref = self._required(attribution_ref, "attribution_ref")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            agent = db.execute(
                "SELECT 1 FROM treasury_agents WHERE agent_id=? AND network=? AND asset=?",
                (agent_id, network, asset),
            ).fetchone()
            if not agent:
                db.rollback()
                raise ValueError("agent has no virtual treasury account")
            existing = db.execute(
                "SELECT * FROM treasury_payment_intents WHERE attribution_ref=?",
                (attribution_ref,),
            ).fetchone()
            if existing:
                expected = (existing["agent_id"], existing["network"], existing["asset"],
                            existing["expected_amount_minor"])
                actual = (agent_id, network, asset, expected_amount_minor)
                if expected != actual:
                    db.rollback()
                    raise ValueError("payment intent reference already belongs to different terms")
                db.commit()
                return
            db.execute(
                """INSERT INTO treasury_payment_intents
                   (attribution_ref,agent_id,network,asset,expected_amount_minor,status)
                   VALUES(?,?,?,?,?,'pending')""",
                (attribution_ref, agent_id, network, asset, expected_amount_minor),
            )
            db.commit()

    def record_receipt(self, transfer: VerifiedTransfer, *, period_id: str,
                       agent_id: str | None = None, attribution_ref: str | None = None) -> str:
        """Credit a verified deposit, or hold it in suspense until its intent is matched.

        A shared EVM address has no memo field. Agent credit therefore requires a
        pre-created internal payment intent with exact agent, network, asset and
        amount. Unmatched transfers remain unallocated; caller-supplied labels alone
        are never sufficient proof of ownership.
        """
        self._validate_transfer(transfer)
        period_id = self._required(period_id, "period_id")
        wallet = self.treasury_wallet(transfer.network, transfer.asset)
        if not wallet or transfer.destination.lower() != wallet.address.lower():
            raise ValueError("incoming transfer destination is not the collective treasury")
        if agent_id and not (isinstance(attribution_ref, str) and attribution_ref.strip()):
            raise ValueError("verified payment intent reference is required for direct agent credit")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                intent = None
                if attribution_ref:
                    intent = db.execute(
                        "SELECT * FROM treasury_payment_intents WHERE attribution_ref=?",
                        (attribution_ref,),
                    ).fetchone()
                    if (not intent or intent["network"] != transfer.network
                            or intent["asset"] != transfer.asset.upper()
                            or intent["expected_amount_minor"] != transfer.amount_minor
                            or intent["status"] != "pending"):
                        raise ValueError("receipt does not match a pending verified payment intent")
                    if agent_id and intent["agent_id"] != agent_id:
                        raise ValueError("payment intent belongs to a different agent")
                if agent_id:
                    account = db.execute(
                        "SELECT 1 FROM treasury_agents WHERE agent_id=? AND network=? AND asset=?",
                        (agent_id, transfer.network, transfer.asset.upper()),
                    ).fetchone()
                    if not account:
                        raise ValueError("agent has no virtual treasury account")
                    status = "allocated"
                    account_id = f"agent:{agent_id}"
                else:
                    status = "unallocated"
                    account_id = "treasury:unallocated"
                db.execute(
                    """INSERT INTO treasury_receipts
                       (network,asset,tx_hash,transfer_ref,amount_minor,source_address,
                        destination_address,attribution_ref,attributed_agent_id,status,period_id)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (transfer.network, transfer.asset.upper(), transfer.tx_hash,
                     transfer.transfer_ref, transfer.amount_minor, transfer.source,
                     transfer.destination, attribution_ref, agent_id, status, period_id),
                )
                self._insert_entry(db, account_id, transfer.network, transfer.asset.upper(),
                                   "receipt", "credit", transfer.amount_minor, period_id,
                                   "Verified on-chain treasury receipt", transfer.tx_hash,
                                   transfer.transfer_ref)
                db.execute(
                    """INSERT INTO treasury_pool_events
                       (network,asset,tx_hash,transfer_ref,event_type,amount_minor)
                       VALUES(?,?,?,?, 'receipt', ?)""",
                    (transfer.network, transfer.asset.upper(), transfer.tx_hash,
                     transfer.transfer_ref, transfer.amount_minor),
                )
                if agent_id and intent:
                    db.execute(
                        """UPDATE treasury_payment_intents
                           SET status='settled',settled_tx_hash=?,settled_transfer_ref=?
                           WHERE attribution_ref=? AND status='pending'""",
                        (transfer.tx_hash, transfer.transfer_ref, attribution_ref),
                    )
                db.commit()
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise ValueError("duplicate or conflicting treasury receipt") from exc
            except Exception:
                db.rollback()
                raise
        return "allocated" if agent_id else "unallocated"

    def attribute_receipt(self, network: str, asset: str, tx_hash: str,
                          transfer_ref: str, agent_id: str, *,
                          expected_attribution_ref: str) -> None:
        """Allocate suspense only to the agent named by the exact pending intent."""
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            receipt = db.execute(
                """SELECT * FROM treasury_receipts
                   WHERE network=? AND asset=? AND tx_hash=? AND transfer_ref=?""",
                (network, asset.upper(), tx_hash, transfer_ref),
            ).fetchone()
            intent = db.execute(
                "SELECT * FROM treasury_payment_intents WHERE attribution_ref=?",
                (expected_attribution_ref,),
            ).fetchone()
            if not receipt or receipt["status"] != "unallocated":
                db.rollback()
                raise ValueError("unallocated receipt not found")
            if (not intent or intent["status"] != "pending"
                    or intent["agent_id"] != agent_id
                    or intent["network"] != network
                    or intent["asset"] != asset.upper()
                    or intent["expected_amount_minor"] != receipt["amount_minor"]
                    or receipt["attribution_ref"] != expected_attribution_ref):
                db.rollback()
                raise ValueError("receipt does not match this agent's pending payment intent")
            self._insert_entry(db, "treasury:unallocated", network, asset.upper(),
                               "attribution_out", "debit", receipt["amount_minor"],
                               receipt["period_id"], "Receipt assigned from suspense",
                               tx_hash, transfer_ref)
            self._insert_entry(db, f"agent:{agent_id}", network, asset.upper(),
                               "attribution_in", "credit", receipt["amount_minor"],
                               receipt["period_id"], "Receipt attributed to agent",
                               tx_hash, transfer_ref)
            db.execute(
                """UPDATE treasury_receipts SET attributed_agent_id=?,status='allocated'
                   WHERE network=? AND asset=? AND tx_hash=? AND transfer_ref=?""",
                (agent_id, network, asset.upper(), tx_hash, transfer_ref),
            )
            db.execute(
                """UPDATE treasury_payment_intents
                   SET status='settled',settled_tx_hash=?,settled_transfer_ref=?
                   WHERE attribution_ref=? AND status='pending'""",
                (tx_hash, transfer_ref, expected_attribution_ref),
            )
            db.commit()

    def balance(self, account_id: str, network: str, asset: str) -> int:
        with closing(self._connect()) as db:
            row = db.execute(
                """SELECT COALESCE(SUM(CASE WHEN direction='credit' THEN amount_minor ELSE -amount_minor END),0) AS balance
                   FROM treasury_entries WHERE account_id=? AND network=? AND asset=?""",
                (account_id, network, asset.upper()),
            ).fetchone()
            reserved = 0
            if account_id.startswith("agent:"):
                agent_id = account_id.split(":", 1)[1]
                reserved_row = db.execute(
                    """SELECT COALESCE(SUM(amount_minor),0) AS amount
                       FROM treasury_spend_reservations
                       WHERE agent_id=? AND network=? AND asset=? AND status IN ('reserved','broadcast','uncertain')""",
                    (agent_id, network, asset.upper()),
                ).fetchone()
                reserved = int(reserved_row["amount"])
        return int(row["balance"]) - reserved

    def reserve_spend(self, agent_id: str, network: str, asset: str,
                      destination: str, amount_minor: int, *, idempotency_key: str,
                      period_id: str) -> str:
        if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
            raise ValueError("amount_minor must be a positive integer")
        if not all(isinstance(v, str) and v.strip() for v in
                   (agent_id, network, asset, destination, idempotency_key, period_id)):
            raise ValueError("agent, network, asset, destination, idempotency key and period are required")
        asset = asset.upper()
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT * FROM treasury_spend_reservations WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if old:
                if (old["agent_id"], old["network"], old["asset"], old["destination"], old["amount_minor"]) != (
                    agent_id, network, asset, destination, amount_minor
                ):
                    db.rollback()
                    raise ValueError("idempotency key reused for a different spend")
                db.commit()
                return old["reservation_id"]
            policy = db.execute(
                "SELECT * FROM treasury_agents WHERE agent_id=? AND network=? AND asset=?",
                (agent_id, network, asset),
            ).fetchone()
            if not policy or not policy["enabled"]:
                db.rollback()
                raise ValueError("agent treasury spending is disabled")
            if destination not in json.loads(policy["allowed_destinations_json"]):
                db.rollback()
                raise ValueError("destination is not allowlisted")
            if amount_minor > policy["per_tx_limit_minor"]:
                db.rollback()
                raise ValueError("spend exceeds per-transaction limit")
            balance_row = db.execute(
                """SELECT COALESCE(SUM(CASE WHEN direction='credit' THEN amount_minor ELSE -amount_minor END),0) AS amount
                   FROM treasury_entries WHERE account_id=? AND network=? AND asset=?""",
                (f"agent:{agent_id}", network, asset),
            ).fetchone()
            pending = db.execute(
                """SELECT COALESCE(SUM(amount_minor),0) AS amount
                   FROM treasury_spend_reservations WHERE agent_id=? AND network=? AND asset=?
                     AND status IN ('reserved','broadcast','uncertain')""",
                (agent_id, network, asset),
            ).fetchone()
            available = int(balance_row["amount"]) - int(pending["amount"])
            if amount_minor > available:
                db.rollback()
                raise ValueError("insufficient agent virtual balance")
            daily = db.execute(
                """SELECT COALESCE(SUM(amount_minor),0) AS amount
                   FROM treasury_spend_reservations
                   WHERE agent_id=? AND network=? AND asset=?
                     AND date(created_at)=date('now')
                     AND status IN ('reserved','broadcast','settled','uncertain')""",
                (agent_id, network, asset),
            ).fetchone()
            if int(daily["amount"]) + amount_minor > policy["daily_limit_minor"]:
                db.rollback()
                raise ValueError("daily spending limit exceeded")
            reservation_id = "spend_" + os.urandom(16).hex()
            db.execute(
                """INSERT INTO treasury_spend_reservations
                   (reservation_id,agent_id,network,asset,destination,amount_minor,
                    idempotency_key,status,period_id)
                   VALUES(?,?,?,?,?,?,?,'reserved',?)""",
                (reservation_id, agent_id, network, asset, destination,
                 amount_minor, idempotency_key, period_id),
            )
            db.commit()
        return reservation_id

    def mark_broadcast(self, reservation_id: str, tx_hash: str) -> None:
        if not tx_hash.strip():
            raise ValueError("transaction hash is required")
        with closing(self._connect()) as db:
            cur = db.execute(
                """UPDATE treasury_spend_reservations SET status='broadcast',tx_hash=?
                   WHERE reservation_id=? AND status='reserved'""",
                (tx_hash, reservation_id),
            )
            if cur.rowcount != 1:
                raise ValueError("only a reserved spend can be marked broadcast")

    def mark_uncertain(self, reservation_id: str, tx_hash: str | None = None) -> None:
        """Hold funds after ambiguous submission; optionally persist its known tx hash."""
        with closing(self._connect()) as db:
            cur = db.execute(
                """UPDATE treasury_spend_reservations SET status='uncertain',
                       tx_hash=COALESCE(?,tx_hash)
                   WHERE reservation_id=? AND status IN ('reserved','broadcast','uncertain')""",
                (tx_hash, reservation_id),
            )
            if cur.rowcount != 1:
                raise ValueError("spend reservation cannot enter uncertain state")

    def cancel_reservation(self, reservation_id: str) -> None:
        with closing(self._connect()) as db:
            cur = db.execute(
                """UPDATE treasury_spend_reservations SET status='cancelled'
                   WHERE reservation_id=? AND status='reserved'""",
                (reservation_id,),
            )
            if cur.rowcount != 1:
                raise ValueError("only an unbroadcast reservation can be cancelled")

    def settle_spend(self, reservation_id: str, transfer: VerifiedTransfer) -> None:
        self._validate_transfer(transfer)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            reservation = db.execute(
                "SELECT * FROM treasury_spend_reservations WHERE reservation_id=?",
                (reservation_id,),
            ).fetchone()
            wallet = db.execute(
                "SELECT address FROM treasury_wallets WHERE network=? AND asset=?",
                (transfer.network, transfer.asset.upper()),
            ).fetchone()
            if not reservation or reservation["status"] not in {"broadcast", "uncertain"}:
                db.rollback()
                raise ValueError("spend must be broadcast or uncertain before settlement")
            if not wallet or transfer.source.lower() != wallet["address"].lower():
                db.rollback()
                raise ValueError("verified spend source is not the collective treasury")
            if (reservation["network"], reservation["asset"], reservation["destination"],
                reservation["amount_minor"]) != (
                transfer.network, transfer.asset.upper(), transfer.destination,
                transfer.amount_minor
            ):
                db.rollback()
                raise ValueError("verified settlement does not match the exact reservation")
            if reservation["tx_hash"] and reservation["tx_hash"] != transfer.tx_hash:
                db.rollback()
                raise ValueError("verified transaction hash does not match recorded broadcast hash")
            try:
                self._insert_entry(db, f"agent:{reservation['agent_id']}", transfer.network,
                                   transfer.asset.upper(), "expense", "debit",
                                   transfer.amount_minor, reservation["period_id"],
                                   "Verified treasury payment for agent expense",
                                   transfer.tx_hash, transfer.transfer_ref)
                db.execute(
                    """INSERT INTO treasury_pool_events
                       (network,asset,tx_hash,transfer_ref,event_type,amount_minor)
                       VALUES(?,?,?,?, 'expense', ?)""",
                    (transfer.network, transfer.asset.upper(), transfer.tx_hash,
                     transfer.transfer_ref, transfer.amount_minor),
                )
                db.execute(
                    """UPDATE treasury_spend_reservations SET status='settled',tx_hash=?
                       WHERE reservation_id=?""",
                    (transfer.tx_hash, reservation_id),
                )
                db.commit()
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise ValueError("duplicate or conflicting treasury settlement") from exc

    def pool_balance(self, network: str, asset: str) -> int:
        """Ledger-tracked pooled cash: verified receipts minus verified external spends."""
        with closing(self._connect()) as db:
            row = db.execute(
                """SELECT COALESCE(SUM(CASE WHEN event_type='receipt'
                           THEN amount_minor ELSE -amount_minor END),0) AS amount
                   FROM treasury_pool_events WHERE network=? AND asset=?""",
                (network, asset.upper()),
            ).fetchone()
        return int(row["amount"])

    def reconciliation_snapshot(self, network: str, asset: str) -> dict:
        """Compare pooled cash events with the sum of all agent/treasury virtual accounts."""
        with closing(self._connect()) as db:
            row = db.execute(
                """SELECT COALESCE(SUM(CASE WHEN direction='credit'
                           THEN amount_minor ELSE -amount_minor END),0) AS amount
                   FROM treasury_entries WHERE network=? AND asset=?""",
                (network, asset.upper()),
            ).fetchone()
            counts = db.execute(
                """SELECT
                     COALESCE(SUM(CASE WHEN event_type='receipt' THEN amount_minor ELSE 0 END),0) AS receipts,
                     COALESCE(SUM(CASE WHEN event_type='expense' THEN amount_minor ELSE 0 END),0) AS expenses
                   FROM treasury_pool_events WHERE network=? AND asset=?""",
                (network, asset.upper()),
            ).fetchone()
        pool = int(counts["receipts"]) - int(counts["expenses"])
        virtual = int(row["amount"])
        return {
            "network": network, "asset": asset.upper(),
            "verified_receipts_minor": int(counts["receipts"]),
            "verified_external_expenses_minor": int(counts["expenses"]),
            "pool_balance_minor": pool,
            "virtual_accounts_total_minor": virtual,
            "difference_minor": pool - virtual,
            "balanced": pool == virtual,
        }

    def close_period(self, agent_id: str, network: str, asset: str, period_id: str, *,
                     reserve_bps: int, owner_share_bps: int,
                     master_account: str = "master:owner") -> dict:
        for name, value in (("reserve_bps", reserve_bps), ("owner_share_bps", owner_share_bps)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
                raise ValueError(f"{name} must be between 0 and 10000 basis points")
        key = f"{agent_id}:{network}:{asset.upper()}:{period_id}"
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM treasury_period_closes WHERE close_key=?", (key,)).fetchone()
            if existing:
                db.commit()
                return dict(existing)
            pending = db.execute(
                """SELECT 1 FROM treasury_spend_reservations
                   WHERE agent_id=? AND network=? AND asset=? AND period_id=?
                     AND status IN ('reserved','broadcast','uncertain') LIMIT 1""",
                (agent_id, network, asset.upper(), period_id),
            ).fetchone()
            if pending:
                db.rollback()
                raise ValueError("cannot close period while agent spend reservations are unresolved")
            totals = db.execute(
                """SELECT
                    COALESCE(SUM(CASE WHEN entry_type='receipt' OR entry_type='attribution_in' THEN amount_minor ELSE 0 END),0) AS income,
                    COALESCE(SUM(CASE WHEN entry_type='expense' THEN amount_minor ELSE 0 END),0) AS expenses
                   FROM treasury_entries WHERE account_id=? AND network=? AND asset=? AND period_id=?""",
                (f"agent:{agent_id}", network, asset.upper(), period_id),
            ).fetchone()
            income, expenses = int(totals["income"]), int(totals["expenses"])
            profit = max(0, income - expenses)
            reserve = profit * reserve_bps // 10_000
            distributable = profit - reserve
            owner = distributable * owner_share_bps // 10_000
            retained = distributable - owner
            available_row = db.execute(
                """SELECT COALESCE(SUM(CASE WHEN direction='credit' THEN amount_minor ELSE -amount_minor END),0) AS amount
                   FROM treasury_entries WHERE account_id=? AND network=? AND asset=?""",
                (f"agent:{agent_id}", network, asset.upper()),
            ).fetchone()
            if int(available_row["amount"]) < owner + reserve:
                db.rollback()
                raise ValueError("agent balance is insufficient to allocate owner share and reserve")
            if owner:
                self._insert_entry(db, f"agent:{agent_id}", network, asset.upper(),
                                   "owner_share", "debit", owner, period_id,
                                   "Master share allocated from net realized profit")
                self._insert_entry(db, master_account, network, asset.upper(),
                                   "owner_share", "credit", owner, period_id,
                                   f"Owner share from {agent_id}")
            if reserve:
                self._insert_entry(db, f"agent:{agent_id}", network, asset.upper(),
                                   "reserve", "debit", reserve, period_id,
                                   "Operating reserve allocation")
                self._insert_entry(db, f"treasury:reserve:{agent_id}", network, asset.upper(),
                                   "reserve", "credit", reserve, period_id,
                                   "Reserved operating capital")
            db.execute(
                """INSERT INTO treasury_period_closes
                   (close_key,agent_id,network,asset,period_id,income_minor,expenses_minor,
                    net_profit_minor,reserve_minor,owner_share_minor,agent_retained_minor)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (key, agent_id, network, asset.upper(), period_id, income, expenses,
                 profit, reserve, owner, retained),
            )
            db.commit()
            return dict(self.get_period_close(agent_id, network, asset, period_id))

    def get_period_close(self, agent_id: str, network: str, asset: str, period_id: str) -> dict | None:
        key = f"{agent_id}:{network}:{asset.upper()}:{period_id}"
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM treasury_period_closes WHERE close_key=?", (key,)).fetchone()
        return dict(row) if row else None


class CDPServerTreasuryWallet:
    """Coinbase CDP server-managed EVM treasury wallet adapter.

    Requires CDP_API_KEY_ID, CDP_API_KEY_SECRET and CDP_WALLET_SECRET in the
    runtime environment, plus an account policy ID. Secrets are never persisted.
    """
    provider_name = "coinbase-cdp"

    def __init__(self, *, account_name: str = "AAE_MASTER_TREASURY",
                 account_policy_id: str | None = None,
                 client_factory: Callable[[], object] | None = None) -> None:
        self.account_name = account_name
        self.account_policy_id = account_policy_id or os.getenv("AAE_CDP_ACCOUNT_POLICY_ID")
        self.client_factory = client_factory
        if not self.account_policy_id:
            raise ValueError("AAE_CDP_ACCOUNT_POLICY_ID must reference a restrictive CDP account policy")

    async def _client(self):
        if self.client_factory:
            return self.client_factory()
        try:
            from cdp import CdpClient
        except ImportError as exc:
            raise RuntimeError("install the optional 'cdp' extra: pip install .[cdp]") from exc
        required = ("CDP_API_KEY_ID", "CDP_API_KEY_SECRET", "CDP_WALLET_SECRET")
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            raise RuntimeError("missing CDP runtime secrets: " + ", ".join(missing))
        return CdpClient()

    async def _get_policy_bound_account(self, cdp):
        account = await cdp.evm.get_or_create_account(name=self.account_name)
        if self.client_factory:
            update = {"account_policy": self.account_policy_id}
        else:
            from cdp.update_account_types import UpdateAccountOptions
            update = UpdateAccountOptions(account_policy=self.account_policy_id)
        # Reapplying the same account policy is safe and makes the boundary
        # explicit even when the named account was created before AAE started.
        await cdp.evm.update_account(address=account.address, update=update)
        return account

    async def ensure_wallet(self, *, network: str = "base-sepolia") -> TreasuryWallet:
        if network not in {"base-sepolia", "base"}:
            raise ValueError("first CDP treasury adapter supports only base-sepolia or base")
        client = await self._client()
        async with client as cdp:
            account = await self._get_policy_bound_account(cdp)
            address = str(account.address)
            wallet_id = str(getattr(account, "id", address))
        return TreasuryWallet(self.provider_name, wallet_id, network, "USDC", address)

    async def transfer_usdc(self, *, destination: str, amount_minor: int,
                            network: str = "base-sepolia") -> str:
        """Broadcast one exact USDC transfer; caller must reconcile before retrying.

        amount_minor is USDC's six-decimal atomic unit. This method deliberately
        does not auto-retry an ambiguous timeout because the SDK transfer API does
        not expose an idempotency key at this adapter boundary.
        """
        if network not in {"base-sepolia", "base"}:
            raise ValueError("first CDP treasury adapter supports only base-sepolia or base")
        if not isinstance(destination, str) or not destination.startswith("0x") or len(destination) != 42:
            raise ValueError("destination must be an EVM address")
        if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
            raise ValueError("amount_minor must be a positive integer")
        client = await self._client()
        async with client as cdp:
            account = await self._get_policy_bound_account(cdp)
            tx_hash = await account.transfer(
                to=destination, amount=amount_minor, token="usdc", network=network
            )
        return str(tx_hash)
