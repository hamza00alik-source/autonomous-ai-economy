"""Collective treasury reorganization guard and Accounting Agent cycle.

The guard never reverses accounting automatically. A canonicality mismatch opens
an auditable incident and freezes agent spending for the affected pool. The
runtime orders reconciliation before payout execution and fails closed whenever
receipt intake, reorg checks, or on-chain balance reconciliation fail.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import closing
from datetime import datetime, timezone
from typing import Awaitable, Callable, Protocol

from .collective_treasury_monitor import CollectiveTreasuryReceiptMonitor
from .treasury_worker import CollectiveTreasuryWorker


class CollectiveCanonicalVerifier(Protocol):
    def finalized_block_number(self) -> int: ...

    def is_transfer_canonical(
        self, *, network: str, token_contract: str, tx_hash: str,
        transfer_ref: str, expected_block_number: int, expected_block_hash: str,
        source: str, destination: str, amount_minor: int,
    ) -> bool: ...


class CollectiveTreasuryReorgGuard:
    """Continuously recheck finalized collective receipts within a rolling window."""

    def __init__(self, monitor: CollectiveTreasuryReceiptMonitor,
                 verifier: CollectiveCanonicalVerifier, *,
                 lookback_blocks: int = 2048, batch_size: int = 500) -> None:
        if isinstance(lookback_blocks, bool) or not isinstance(lookback_blocks, int) or lookback_blocks < 1:
            raise ValueError("lookback_blocks must be a positive integer")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 5000:
            raise ValueError("batch_size must be between 1 and 5000")
        self.monitor, self.verifier = monitor, verifier
        self.lookback_blocks, self.batch_size = lookback_blocks, batch_size
        with closing(monitor.store._connect()) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS treasury_reorg_guard_cursors (
                    network TEXT NOT NULL, asset TEXT NOT NULL,
                    block_number INTEGER NOT NULL, tx_hash TEXT NOT NULL,
                    transfer_ref TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(network, asset)
                )
            """)

    def reconcile_once(self, *, network: str, asset: str) -> dict:
        finalized = self.verifier.finalized_block_number()
        if isinstance(finalized, bool) or not isinstance(finalized, int) or finalized < 0:
            raise ValueError("verifier returned invalid finalized block")
        floor = max(0, finalized - self.lookback_blocks + 1)
        wallet = self.monitor.store.treasury_wallet(network, asset)
        if not wallet:
            raise ValueError("collective treasury wallet is not registered")
        with closing(self.monitor.store._connect()) as db:
            cursor = db.execute(
                """SELECT block_number,tx_hash,transfer_ref
                   FROM treasury_reorg_guard_cursors WHERE network=? AND asset=?""",
                (network, asset.upper()),
            ).fetchone()
            last = (cursor["block_number"], cursor["tx_hash"], cursor["transfer_ref"]) if cursor else None
            if last and last[0] < floor:
                last = None
            base_sql = """SELECT e.tx_hash,e.transfer_ref,e.block_hash,e.block_number,
                                 r.source_address,r.destination_address,r.amount_minor
                          FROM treasury_receipt_monitor_events e
                          JOIN treasury_receipts r
                            ON r.network=e.network AND r.tx_hash=e.tx_hash
                           AND r.transfer_ref=e.transfer_ref AND r.asset=?
                          WHERE e.network=? AND e.status IN ('allocated','unallocated')
                            AND (e.block_number=0 OR (e.block_number>=? AND e.block_number<=?))"""
            params = [asset.upper(), network, floor, finalized]
            if last:
                base_sql += """ AND (e.block_number>? OR (e.block_number=? AND
                               (e.tx_hash>? OR (e.tx_hash=? AND e.transfer_ref>?))))"""
                params.extend([last[0], last[0], last[1], last[1], last[2]])
            rows = db.execute(
                base_sql + " ORDER BY e.block_number,e.tx_hash,e.transfer_ref LIMIT ?",
                (*params, self.batch_size + 1),
            ).fetchall()
        has_more = len(rows) > self.batch_size
        rows = rows[:self.batch_size]
        checked = alerts = legacy_unknown = 0
        for row in rows:
            checked += 1
            if row["block_number"] <= 0:
                legacy_unknown += 1
                self.monitor._raise_reorg_alert(
                    network=network, asset=asset, tx_hash=row["tx_hash"],
                    transfer_ref=row["transfer_ref"],
                    expected_block_hash=row["block_hash"],
                    observed_block_hash=None,
                    reason="legacy credited receipt has no recorded block number",
                )
                alerts += 1
                continue
            canonical = self.verifier.is_transfer_canonical(
                network=network, token_contract=self.monitor.token_contract,
                tx_hash=row["tx_hash"], transfer_ref=row["transfer_ref"],
                expected_block_number=row["block_number"],
                expected_block_hash=row["block_hash"],
                source=row["source_address"], destination=row["destination_address"],
                amount_minor=row["amount_minor"],
            )
            if canonical is not True:
                self.monitor._raise_reorg_alert(
                    network=network, asset=asset, tx_hash=row["tx_hash"],
                    transfer_ref=row["transfer_ref"],
                    expected_block_hash=row["block_hash"],
                    observed_block_hash=None,
                    reason="canonical verifier reports credited transfer missing or changed",
                )
                alerts += 1
        with closing(self.monitor.store._connect()) as db:
            if rows and has_more:
                tail = rows[-1]
                db.execute(
                    """INSERT INTO treasury_reorg_guard_cursors
                       (network,asset,block_number,tx_hash,transfer_ref)
                       VALUES(?,?,?,?,?)
                       ON CONFLICT(network,asset) DO UPDATE SET
                         block_number=excluded.block_number,tx_hash=excluded.tx_hash,
                         transfer_ref=excluded.transfer_ref,updated_at=CURRENT_TIMESTAMP""",
                    (network, asset.upper(), tail["block_number"], tail["tx_hash"], tail["transfer_ref"]),
                )
            else:
                db.execute(
                    "DELETE FROM treasury_reorg_guard_cursors WHERE network=? AND asset=?",
                    (network, asset.upper()),
                )
        return {
            "checked": checked, "reorg_alerts": alerts,
            "legacy_receipts_without_block_number": legacy_unknown,
            "from_block": floor, "finalized_block": finalized,
            "open_alerts": self.monitor.open_reorg_alerts(network=network, asset=asset),
            "has_more": has_more,
        }


class CollectiveTreasuryAccountingRuntime:
    """One accounting cycle: ingest, reorg-check, reconcile, then execute spends."""

    def __init__(self, receipt_monitor: CollectiveTreasuryReceiptMonitor,
                 reorg_guard: CollectiveTreasuryReorgGuard,
                 balance_check: Callable[[], dict],
                 worker: CollectiveTreasuryWorker, *,
                 network: str, asset: str,
                 owner_overflow_sweep_cycle: Callable[[], Awaitable[dict]] | None = None,
                 owner_profit_payout_cycle: Callable[[], Awaitable[dict]] | None = None) -> None:
        self.receipt_monitor = receipt_monitor
        self.reorg_guard, self.balance_check, self.worker = reorg_guard, balance_check, worker
        self.network, self.asset = network, asset.upper()
        # These callbacks must close over the authenticated owner-configured
        # payout address and the exact current period/idempotency keys.
        self.owner_overflow_sweep_cycle = owner_overflow_sweep_cycle
        self.owner_profit_payout_cycle = owner_profit_payout_cycle

    async def run_once(self, *, period_id: str, spend_limit: int = 25) -> dict:
        receipts = self.receipt_monitor.poll_once(
            network=self.network, asset=self.asset, period_id=period_id,
        )
        reorgs = self.reorg_guard.reconcile_once(
            network=self.network, asset=self.asset,
        )
        balances = self.balance_check()
        if not isinstance(balances, dict) or balances.get("fully_reconciled") is not True:
            return {
                "status": "payouts_blocked", "reason": "treasury balance reconciliation is not fully healthy",
                "receipts": receipts, "reorgs": reorgs, "balances": balances,
                "spending": None,
            }
        if reorgs.get("open_alerts", 0) > 0:
            return {
                "status": "payouts_blocked", "reason": "open treasury reorganization alerts require operator review",
                "receipts": receipts, "reorgs": reorgs, "balances": balances,
                "spending": None,
            }
        if reorgs.get("has_more") is True:
            return {
                "status": "payouts_blocked",
                "reason": "treasury reorganization scan is incomplete; remaining receipts must be checked before spending",
                "receipts": receipts, "reorgs": reorgs, "balances": balances,
                "spending": None,
            }
        owner_overflow = None
        owner_transfer_ran = False
        capacity = self.receipt_monitor.store.shared_wallet_capacity(
            self.network, self.asset,
        )
        if capacity["over_cap"]:
            if self.owner_overflow_sweep_cycle is None:
                return {
                    "status": "payouts_blocked",
                    "reason": "shared treasury is above its configured holding cap and no owner overflow worker is wired",
                    "receipts": receipts, "reorgs": reorgs, "balances": balances,
                    "owner_overflow": None, "owner_profit": None, "spending": None,
                }
            owner_overflow = await self.owner_overflow_sweep_cycle()
            owner_transfer_ran = True
            if (not isinstance(owner_overflow, dict)
                    or owner_overflow.get("status") not in {"settled", "not_needed"}
                    or owner_overflow.get("uncertain", 0) != 0
                    or owner_overflow.get("skipped", 0) != 0):
                return {
                    "status": "payouts_blocked",
                    "reason": "owner overflow worker did not confirm a clean settled/no-op result",
                    "receipts": receipts, "reorgs": reorgs, "balances": balances,
                    "owner_overflow": owner_overflow, "owner_profit": None, "spending": None,
                }
            capacity = self.receipt_monitor.store.shared_wallet_capacity(
                self.network, self.asset,
            )
            if capacity["over_cap"]:
                return {
                    "status": "payouts_blocked",
                    "reason": "owner overflow sweep did not bring the shared treasury within its configured cap",
                    "receipts": receipts, "reorgs": reorgs, "balances": balances,
                    "owner_overflow": owner_overflow, "owner_profit": None, "spending": None,
                }

        owner_profit = None
        if self.owner_profit_payout_cycle is not None:
            owner_profit = await self.owner_profit_payout_cycle()
            owner_transfer_ran = True
            # Fail closed on every status except an explicit clean completion.
            # A new/unknown status must never silently authorize agent spending.
            if (not isinstance(owner_profit, dict)
                    or owner_profit.get("status") not in {
                        "completed", "paid", "no_distribution", "not_needed"
                    }
                    or owner_profit.get("uncertain", 0) != 0
                    or owner_profit.get("pending", 0) != 0
                    or owner_profit.get("blocked", 0) != 0
                    or owner_profit.get("failed", 0) != 0):
                return {
                    "status": "payouts_blocked",
                    "reason": "owner profit payout did not confirm a clean completed/no-op result",
                    "receipts": receipts, "reorgs": reorgs, "balances": balances,
                    "owner_overflow": owner_overflow, "owner_profit": owner_profit,
                    "spending": None,
                }

        # Owner transfers change the physical pool. Re-read on-chain balances
        # before any agent spend is allowed to proceed in the same cycle.
        if owner_transfer_ran:
            balances = self.balance_check()
            if not isinstance(balances, dict) or balances.get("fully_reconciled") is not True:
                return {
                    "status": "payouts_blocked",
                    "reason": "treasury balance reconciliation after owner payouts is not fully healthy",
                    "receipts": receipts, "reorgs": reorgs, "balances": balances,
                    "owner_overflow": owner_overflow, "owner_profit": owner_profit,
                    "spending": None,
                }
        capacity = self.receipt_monitor.store.shared_wallet_capacity(
            self.network, self.asset,
        )
        if capacity["over_cap"]:
            return {
                "status": "payouts_blocked",
                "reason": "shared treasury remains above its configured holding cap",
                "receipts": receipts, "reorgs": reorgs, "balances": balances,
                "owner_overflow": owner_overflow, "owner_profit": owner_profit,
                "spending": None,
            }
        spending = await self.worker.run_once(limit=spend_limit)
        return {
            "status": "completed", "receipts": receipts, "reorgs": reorgs,
            "balances": balances, "owner_overflow": owner_overflow,
            "owner_profit": owner_profit, "spending": spending,
        }

    async def run_forever(self, *, interval_seconds: float = 30.0,
                          spend_limit: int = 25,
                          stop_event: asyncio.Event | None = None) -> None:
        """Run guarded cycles until the host asks the service to stop.

        Deploy under a process supervisor. A failed cycle is logged and retried
        only on the next interval; it never skips the safety gates to execute spends.
        """
        if isinstance(interval_seconds, bool) or not isinstance(interval_seconds, (int, float)) or interval_seconds < 1:
            raise ValueError("interval_seconds must be at least one second")
        if stop_event is None:
            stop_event = asyncio.Event()
        logger = logging.getLogger("aae.collective_accounting")
        while not stop_event.is_set():
            period_id = datetime.now(timezone.utc).strftime("%Y-%m")
            try:
                result = await self.run_once(period_id=period_id, spend_limit=spend_limit)
                logger.info("collective accounting cycle: %s", result)
            except Exception:
                logger.exception("collective accounting cycle failed; payouts were not advanced past failed safety gate")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=float(interval_seconds))
            except asyncio.TimeoutError:
                pass


__all__ = [
    "CollectiveTreasuryAccountingRuntime",
    "CollectiveTreasuryReorgGuard",
    "CollectiveCanonicalVerifier",
]
