"""Agent-native wallet attribution and profit-sharing ledger.

This module is deliberately chain-agnostic. A chain adapter must independently
verify receipts/transactions before calling this store. It never handles private
keys, signs transactions, or pretends database records are on-chain money.
"""
from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bps(value: int, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10_000:
        raise ValueError(f"{field} must be an integer from 0 to 10000")


@dataclass(frozen=True)
class Wallet:
    participant_id: str
    role: Literal["agent", "master"]
    network: str
    asset: str
    address: str


@dataclass(frozen=True)
class VerifiedTransfer:
    """A normalized transfer supplied by a trusted chain adapter.

    verified must mean the adapter checked chain, token contract, destination,
    amount, transaction inclusion, finality/confirmation policy and reorg status.
    """
    network: str
    asset: str
    tx_hash: str
    transfer_ref: str
    destination: str
    amount_minor: int
    confirmations: int
    verified: bool
    source: str = ""


class AgentFinanceStore:
    """SQLite wallet registry, verified cashflow ledger and profit allocations.

    The store is an accounting/control component, not a wallet or custody service.
    Wallet addresses are public. Private keys must remain in an external signer.
    """

    def __init__(self, path: str | Path = "./data/agent_finance.sqlite3") -> None:
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS finance_wallets (
                    participant_id TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('agent','master')),
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    address TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(participant_id, network, asset, role),
                    UNIQUE(network, asset, address, role)
                );
                CREATE TABLE IF NOT EXISTS finance_events (
                    event_id TEXT PRIMARY KEY,
                    participant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL CHECK(event_type IN ('income','expense')),
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                    tx_hash TEXT NOT NULL,
                    transfer_ref TEXT NOT NULL,
                    period_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(network, tx_hash, transfer_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_finance_events_period
                    ON finance_events(participant_id, network, asset, period_id);
                CREATE TABLE IF NOT EXISTS profit_periods (
                    period_key TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    master_id TEXT NOT NULL,
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    period_id TEXT NOT NULL,
                    gross_income_minor INTEGER NOT NULL,
                    expenses_minor INTEGER NOT NULL,
                    operating_profit_minor INTEGER NOT NULL,
                    reserve_minor INTEGER NOT NULL,
                    distributable_minor INTEGER NOT NULL,
                    owner_share_bps INTEGER NOT NULL,
                    master_due_minor INTEGER NOT NULL,
                    agent_retained_minor INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('no_distribution','pending_payout','paid')),
                    payout_tx_hash TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(agent_id, network, asset, period_id),
                    UNIQUE(network, payout_tx_hash)
                );
                CREATE TABLE IF NOT EXISTS finance_adjustments (
                    adjustment_id TEXT PRIMARY KEY,
                    participant_id TEXT NOT NULL,
                    network TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    adjustment_type TEXT NOT NULL CHECK(adjustment_type='income_reversal'),
                    amount_minor INTEGER NOT NULL CHECK(amount_minor > 0),
                    original_tx_hash TEXT NOT NULL,
                    original_transfer_ref TEXT NOT NULL,
                    adjustment_period_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    UNIQUE(network, original_tx_hash, original_transfer_ref)
                );
                CREATE INDEX IF NOT EXISTS idx_finance_adjustments_period
                    ON finance_adjustments(participant_id, network, asset, adjustment_period_id);
                CREATE TABLE IF NOT EXISTS reorg_alert_resolutions (
                    network TEXT NOT NULL,
                    tx_hash TEXT NOT NULL,
                    transfer_ref TEXT NOT NULL,
                    adjustment_id TEXT NOT NULL UNIQUE,
                    operator_id TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    evidence_ref TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    PRIMARY KEY(network, tx_hash, transfer_ref)
                );
            """)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        return db

    def register_wallet(self, wallet: Wallet) -> None:
        if not all(isinstance(v, str) and v.strip() for v in (
            wallet.participant_id, wallet.network, wallet.asset, wallet.address
        )):
            raise ValueError("participant, network, asset and address are required")
        if wallet.role not in {"agent", "master"}:
            raise ValueError("wallet role must be agent or master")
        with closing(self._connect()) as db:
            existing = db.execute(
                """SELECT address FROM finance_wallets
                   WHERE participant_id=? AND role=? AND network=? AND asset=?""",
                (wallet.participant_id, wallet.role, wallet.network, wallet.asset.upper()),
            ).fetchone()
            if existing and existing["address"] != wallet.address:
                raise ValueError("wallet already registered; use a reviewed rotation workflow")
            db.execute(
                """INSERT OR IGNORE INTO finance_wallets
                   VALUES(?,?,?,?,?,?)""",
                (wallet.participant_id, wallet.role, wallet.network,
                 wallet.asset.upper(), wallet.address, _now()),
            )

    def wallet(self, participant_id: str, role: str, network: str, asset: str) -> Wallet | None:
        with closing(self._connect()) as db:
            row = db.execute(
                """SELECT * FROM finance_wallets
                   WHERE participant_id=? AND role=? AND network=? AND asset=?""",
                (participant_id, role, network, asset.upper()),
            ).fetchone()
        return Wallet(row["participant_id"], row["role"], row["network"],
                      row["asset"], row["address"]) if row else None

    @staticmethod
    def _validate_transfer(transfer: VerifiedTransfer) -> None:
        if transfer.verified is not True:
            raise ValueError("transfer must be verified by a trusted chain adapter")
        if not all(isinstance(v, str) and v.strip() for v in (
            transfer.network, transfer.asset, transfer.tx_hash,
            transfer.transfer_ref, transfer.destination
        )):
            raise ValueError("network, asset, transaction, transfer reference and destination are required")
        if isinstance(transfer.amount_minor, bool) or not isinstance(transfer.amount_minor, int) or transfer.amount_minor <= 0:
            raise ValueError("amount_minor must be a positive integer")
        if isinstance(transfer.confirmations, bool) or not isinstance(transfer.confirmations, int) or transfer.confirmations < 1:
            raise ValueError("transfer must meet at least one confirmation")

    def _record_event(self, participant_id: str, event_type: str,
                      transfer: VerifiedTransfer, period_id: str) -> str:
        self._validate_transfer(transfer)
        if not participant_id.strip() or not period_id.strip():
            raise ValueError("participant_id and period_id are required")
        wallet = self.wallet(participant_id, "agent", transfer.network, transfer.asset)
        if wallet is None:
            raise ValueError("agent wallet is not registered")
        if event_type == "income" and wallet.address != transfer.destination:
            raise ValueError("receipt destination does not match the agent wallet")
        if event_type == "expense" and wallet.address != transfer.source:
            raise ValueError("expense source does not match the agent wallet")
        event_id = "fin_" + uuid.uuid4().hex
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            closed = db.execute(
                """SELECT 1 FROM profit_periods
                   WHERE agent_id=? AND network=? AND asset=? AND period_id=?""",
                (participant_id, transfer.network, transfer.asset.upper(), period_id),
            ).fetchone()
            if closed:
                db.rollback()
                raise ValueError("profit period is already closed; late events require an adjustment period")
            try:
                db.execute(
                    """INSERT INTO finance_events VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (event_id, participant_id, event_type, transfer.network,
                     transfer.asset.upper(), transfer.amount_minor, transfer.tx_hash,
                     transfer.transfer_ref, period_id, _now()),
                )
                db.commit()
            except sqlite3.IntegrityError as exc:
                db.rollback()
                raise ValueError("duplicate on-chain transfer or conflicting event") from exc
        return event_id

    def record_receipt(self, agent_id: str, transfer: VerifiedTransfer, *,
                       period_id: str) -> str:
        """Record agent revenue only after adapter-confirmed on-chain settlement."""
        return self._record_event(agent_id, "income", transfer, period_id)

    def record_expense(self, agent_id: str, transfer: VerifiedTransfer, *,
                       period_id: str) -> str:
        """Record an expense only when the verified sender is the agent wallet."""
        return self._record_event(agent_id, "expense", transfer, period_id)

    def close_profit_period(self, agent_id: str, master_id: str, *,
                            network: str, asset: str, period_id: str,
                            reserve_bps: int, owner_share_bps: int) -> dict:
        """Close a period once; reserve first, then split realized net profit.

        No profit means no owner distribution. A master payout wallet must be
        registered before a positive distribution can be created.
        """
        _bps(reserve_bps, "reserve_bps")
        _bps(owner_share_bps, "owner_share_bps")
        if not all(v.strip() for v in (agent_id, master_id, network, asset, period_id)):
            raise ValueError("agent, master, network, asset and period are required")
        asset = asset.upper()
        key = f"{agent_id}:{network}:{asset}:{period_id}"
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM profit_periods WHERE period_key=?", (key,)).fetchone()
            if existing:
                db.commit()
                return dict(existing)
            agent_wallet = db.execute(
                """SELECT 1 FROM finance_wallets
                   WHERE participant_id=? AND role='agent' AND network=? AND asset=?""",
                (agent_id, network, asset),
            ).fetchone()
            if not agent_wallet:
                db.rollback()
                raise ValueError("agent wallet is not registered")
            # If the chain monitor has flagged a previously credited transfer as
            # reorganized, do not finalize profit while its accounting is unresolved.
            monitor_table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chain_monitor_events'"
            ).fetchone()
            if monitor_table:
                unresolved_reorg = db.execute(
                    """SELECT 1 FROM chain_monitor_events c
                       WHERE c.participant_id=? AND c.period_id=? AND c.status='reorg_alert'
                         AND NOT EXISTS (
                           SELECT 1 FROM reorg_alert_resolutions r
                           WHERE r.network=c.network AND r.tx_hash=c.tx_hash
                             AND r.transfer_ref=c.transfer_ref
                         ) LIMIT 1""",
                    (agent_id, period_id),
                ).fetchone()
                if unresolved_reorg:
                    db.rollback()
                    raise ValueError("profit period is blocked by an unresolved chain reorganization alert")
            totals = db.execute(
                """SELECT
                    COALESCE(SUM(CASE WHEN event_type='income' THEN amount_minor ELSE 0 END),0) AS income,
                    COALESCE(SUM(CASE WHEN event_type='expense' THEN amount_minor ELSE 0 END),0) AS expenses
                   FROM finance_events
                   WHERE participant_id=? AND network=? AND asset=? AND period_id=?""",
                (agent_id, network, asset, period_id),
            ).fetchone()
            income, expenses = int(totals["income"]), int(totals["expenses"])
            reversals = db.execute(
                """SELECT COALESCE(SUM(amount_minor),0) AS amount
                   FROM finance_adjustments
                   WHERE participant_id=? AND network=? AND asset=? AND adjustment_period_id=?""",
                (agent_id, network, asset, period_id),
            ).fetchone()
            income_reversals = int(reversals["amount"])
            operating_profit = max(0, income - expenses - income_reversals)
            reserve = operating_profit * reserve_bps // 10_000
            distributable = operating_profit - reserve
            master_due = distributable * owner_share_bps // 10_000
            retained = distributable - master_due
            if master_due:
                master_wallet = db.execute(
                    """SELECT 1 FROM finance_wallets
                       WHERE participant_id=? AND role='master' AND network=? AND asset=?""",
                    (master_id, network, asset),
                ).fetchone()
                if not master_wallet:
                    db.rollback()
                    raise ValueError("master payout wallet must be registered before profit distribution")
            status = "pending_payout" if master_due else "no_distribution"
            db.execute(
                """INSERT INTO profit_periods VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (key, agent_id, master_id, network, asset, period_id, income,
                 expenses, operating_profit, reserve, distributable, owner_share_bps,
                 master_due, retained, status, None, _now()),
            )
            db.commit()
            return dict(self.get_profit_period(agent_id, network, asset, period_id))

    def record_reorg_adjustment(
        self, network: str, tx_hash: str, transfer_ref: str, *,
        adjustment_period_id: str, operator_id: str, reason: str,
        evidence_ref: str, reviewed: bool,
    ) -> dict:
        """Record a reviewed full reversal without rewriting the original receipt.

        The reversal is booked in the affected open period or a new open adjustment
        period when the original period is closed. The caller must enforce operator authorization and independently review the
        evidence before setting reviewed=True; this method records that audit
        assertion but is not an authentication system.
        """
        required = (network, tx_hash, transfer_ref, adjustment_period_id,
                    operator_id, reason, evidence_ref)
        if not all(isinstance(v, str) and v.strip() for v in required):
            raise ValueError("network, transfer identity, adjustment period, operator, reason and evidence are required")
        if len(reason.strip()) < 12:
            raise ValueError("reason must explain the adjustment (12+ characters)")
        if reviewed is not True:
            raise ValueError("an explicit reviewed=True confirmation is required")
        idempotency_key = f"reorg-income-reversal:{network}:{tx_hash}:{transfer_ref}"
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute(
                """SELECT a.*, r.operator_id, r.reason, r.evidence_ref
                   FROM finance_adjustments a
                   JOIN reorg_alert_resolutions r ON r.adjustment_id=a.adjustment_id
                   WHERE a.network=? AND a.original_tx_hash=? AND a.original_transfer_ref=?""",
                (network, tx_hash, transfer_ref),
            ).fetchone()
            if prior:
                if (prior["adjustment_period_id"] != adjustment_period_id
                        or prior["operator_id"] != operator_id
                        or prior["reason"] != reason.strip()
                        or prior["evidence_ref"] != evidence_ref.strip()):
                    db.rollback()
                    raise ValueError("reorg adjustment already exists with different audit details")
                db.commit()
                return dict(prior)
            alert = db.execute(
                """SELECT * FROM chain_monitor_events
                   WHERE network=? AND tx_hash=? AND transfer_ref=? AND status='reorg_alert'""",
                (network, tx_hash, transfer_ref),
            ).fetchone()
            if not alert:
                db.rollback()
                raise ValueError("an active reorganization alert is required")
            original = db.execute(
                """SELECT * FROM finance_events
                   WHERE network=? AND tx_hash=? AND transfer_ref=?""",
                (network, tx_hash, transfer_ref),
            ).fetchone()
            if (not original or original["participant_id"] != alert["participant_id"]
                    or original["event_type"] != "income"
                    or original["asset"].upper() != alert["asset"].upper()
                    or original["period_id"] != alert["period_id"]
                    or int(original["amount_minor"]) != int(alert["amount_minor"])):
                db.rollback()
                raise ValueError("alert does not match an original credited income event")
            original_period_closed = db.execute(
                """SELECT 1 FROM profit_periods
                   WHERE agent_id=? AND network=? AND asset=? AND period_id=?""",
                (alert["participant_id"], network, alert["asset"], alert["period_id"]),
            ).fetchone()
            if original_period_closed and adjustment_period_id == alert["period_id"]:
                db.rollback()
                raise ValueError("a closed period must be corrected in a separate adjustment period")
            if not original_period_closed and adjustment_period_id != alert["period_id"]:
                db.rollback()
                raise ValueError("an open period must be corrected in that same accounting period")
            closed = db.execute(
                """SELECT 1 FROM profit_periods
                   WHERE agent_id=? AND network=? AND asset=? AND period_id=?""",
                (alert["participant_id"], network, alert["asset"], adjustment_period_id),
            ).fetchone()
            if closed:
                db.rollback()
                raise ValueError("adjustment period is already closed")
            adjustment_id = "adj_" + uuid.uuid4().hex
            created_at = _now()
            db.execute(
                """INSERT INTO finance_adjustments
                   (adjustment_id,participant_id,network,asset,adjustment_type,amount_minor,
                    original_tx_hash,original_transfer_ref,adjustment_period_id,idempotency_key,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (adjustment_id, alert["participant_id"], network, alert["asset"],
                 "income_reversal", int(original["amount_minor"]), tx_hash, transfer_ref,
                 adjustment_period_id, idempotency_key, created_at),
            )
            db.execute(
                """INSERT INTO reorg_alert_resolutions
                   (network,tx_hash,transfer_ref,adjustment_id,operator_id,reason,evidence_ref,reviewed_at)
                   VALUES(?,?,?,?,?,?,?,?)""",
                (network, tx_hash, transfer_ref, adjustment_id, operator_id,
                 reason.strip(), evidence_ref.strip(), created_at),
            )
            db.commit()
            return {
                "adjustment_id": adjustment_id, "participant_id": alert["participant_id"],
                "network": network, "asset": alert["asset"], "adjustment_type": "income_reversal",
                "amount_minor": int(original["amount_minor"]), "original_tx_hash": tx_hash,
                "original_transfer_ref": transfer_ref, "adjustment_period_id": adjustment_period_id,
                "idempotency_key": idempotency_key, "operator_id": operator_id,
                "reason": reason.strip(), "evidence_ref": evidence_ref.strip(),
                "created_at": created_at,
            }

    def list_pending_distributions(self, limit: int = 100) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT * FROM profit_periods WHERE status='pending_payout'
                   ORDER BY created_at LIMIT ?""", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def get_profit_period(self, agent_id: str, network: str,
                          asset: str, period_id: str) -> dict | None:
        key = f"{agent_id}:{network}:{asset.upper()}:{period_id}"
        with closing(self._connect()) as db:
            row = db.execute("SELECT * FROM profit_periods WHERE period_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def mark_owner_distribution_paid(self, agent_id: str, network: str, asset: str,
                                     period_id: str, *, transfer: VerifiedTransfer) -> None:
        """Finalize only an exact, independently verified agent-to-master transfer."""
        self._validate_transfer(transfer)
        period = self.get_profit_period(agent_id, network, asset, period_id)
        if not period or period["status"] != "pending_payout":
            raise ValueError("no pending owner distribution exists")
        agent = self.wallet(agent_id, "agent", network, asset)
        master = self.wallet(period["master_id"], "master", network, asset)
        if transfer.network != network or transfer.asset.upper() != asset.upper():
            raise ValueError("payout network or asset does not match the profit period")
        if not agent or transfer.source != agent.address:
            raise ValueError("payout source does not match the agent wallet")
        if not master or master.address != transfer.destination:
            raise ValueError("payout destination does not match the registered master wallet")
        if transfer.amount_minor != period["master_due_minor"]:
            raise ValueError("payout amount does not match the master's calculated share")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            monitor_table = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chain_monitor_events'"
            ).fetchone()
            if monitor_table:
                blocked = db.execute(
                    """SELECT 1 FROM chain_monitor_events c
                       WHERE c.participant_id=? AND c.period_id=? AND c.status='reorg_alert'
                         AND (
                           NOT EXISTS (
                             SELECT 1 FROM reorg_alert_resolutions r
                             WHERE r.network=c.network AND r.tx_hash=c.tx_hash
                               AND r.transfer_ref=c.transfer_ref
                           )
                           OR EXISTS (
                             SELECT 1 FROM reorg_alert_resolutions r
                             JOIN finance_adjustments a ON a.adjustment_id=r.adjustment_id
                             WHERE r.network=c.network AND r.tx_hash=c.tx_hash
                               AND r.transfer_ref=c.transfer_ref
                               AND a.adjustment_period_id<>c.period_id
                           )
                         ) LIMIT 1""",
                    (agent_id, period_id),
                ).fetchone()
                if blocked:
                    db.rollback()
                    raise ValueError("master payout is held by a reorg or closed-period reconciliation")
            cur = db.execute(
                """UPDATE profit_periods SET status='paid', payout_tx_hash=?
                   WHERE period_key=? AND status='pending_payout'""",
                (transfer.tx_hash, period["period_key"]),
            )
            if cur.rowcount != 1:
                db.rollback()
                raise ValueError("distribution was already finalized or changed concurrently")
            db.commit()
