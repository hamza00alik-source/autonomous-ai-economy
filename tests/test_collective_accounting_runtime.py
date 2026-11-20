import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import VerifiedTransfer
from economy.chain_monitor import ChainTransferObservation, TransferPage
from economy.collective_treasury import CollectiveTreasuryStore, TreasuryWallet
from economy.collective_treasury_monitor import CollectiveTreasuryReceiptMonitor
from economy.collective_accounting_runtime import (
    CollectiveTreasuryAccountingRuntime, CollectiveTreasuryReorgGuard,
)


WALLET = "0x" + "a" * 40
PAYER = "0x" + "b" * 40
TOKEN = "0x" + "1" * 40
TX = "0x" + "c" * 64
BLOCK = "0x" + "d" * 64


class Source:
    def __init__(self, item):
        self.item = item

    def fetch_transfers(self, **kwargs):
        return TransferPage((self.item,), "cursor-1")


class Verifier:
    def __init__(self, canonical=True):
        self.canonical = canonical
        self.calls = []

    def finalized_block_number(self):
        return 200

    def is_transfer_canonical(self, **kwargs):
        self.calls.append(kwargs)
        return self.canonical


class CollectiveTreasuryReorgGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CollectiveTreasuryStore(Path(self.tmp.name) / "treasury.sqlite3")
        self.store.register_treasury_wallet(TreasuryWallet(
            "test-provider", "wallet-1", "base-sepolia", "USDC", WALLET
        ))
        self.store.add_agent(
            "agent-a", "base-sepolia", "USDC", daily_limit_minor=10000,
            per_tx_limit_minor=5000, allowed_destinations=("0x" + "e" * 40,),
        )
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 5000, attribution_ref="invoice:guard"
        )
        self.item = ChainTransferObservation(
            "base-sepolia", "USDC", TOKEN, TX, "log:0", PAYER, WALLET,
            5000, 100, BLOCK, 20, True, True, "2026-11-19T12:00:00+00:00",
        )
        self.monitor = CollectiveTreasuryReceiptMonitor(
            self.store, Source(self.item), token_contract=TOKEN
        )
        self.monitor.bind_payer("invoice:guard", PAYER)
        self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_noncanonical_credited_receipt_opens_alert_and_pauses_agents(self):
        verifier = Verifier(canonical=False)
        guard = CollectiveTreasuryReorgGuard(self.monitor, verifier)
        result = guard.reconcile_once(network="base-sepolia", asset="USDC")
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["reorg_alerts"], 1)
        self.assertEqual(result["open_alerts"], 1)
        self.assertEqual(verifier.calls[0]["expected_block_number"], 100)
        with self.assertRaisesRegex(ValueError, "disabled"):
            self.store.reserve_spend(
                "agent-a", "base-sepolia", "USDC", "0x" + "e" * 40, 100,
                idempotency_key="blocked-by-guard", period_id="2026-11",
            )

    def test_reorg_guard_persists_batch_cursor_until_scan_finishes(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 1000, attribution_ref="invoice:second"
        )
        self.monitor.bind_payer("invoice:second", PAYER)
        second_item = ChainTransferObservation(
            "base-sepolia", "USDC", TOKEN, "0x" + "e" * 64, "log:1",
            PAYER, WALLET, 1000, 101, "0x" + "f" * 64, 20, True, True,
            "2026-11-19T12:01:00+00:00",
        )
        self.monitor.source = Source(second_item)
        self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        guard = CollectiveTreasuryReorgGuard(
            self.monitor, Verifier(canonical=True), batch_size=1
        )
        first = guard.reconcile_once(network="base-sepolia", asset="USDC")
        self.assertEqual(first["checked"], 1)
        self.assertTrue(first["has_more"])
        second = guard.reconcile_once(network="base-sepolia", asset="USDC")
        self.assertEqual(second["checked"], 1)
        self.assertFalse(second["has_more"])

    def test_canonical_receipt_remains_healthy(self):
        guard = CollectiveTreasuryReorgGuard(self.monitor, Verifier(canonical=True))
        result = guard.reconcile_once(network="base-sepolia", asset="USDC")
        self.assertEqual(result["reorg_alerts"], 0)
        self.assertEqual(result["open_alerts"], 0)


class FakeTreasuryStore:
    def __init__(self, over_cap=False):
        self.over_cap = over_cap

    def shared_wallet_capacity(self, network, asset):
        return {"over_cap": self.over_cap}


class FakeReceiptMonitor:
    def __init__(self, events):
        self.events = events
        self.store = FakeTreasuryStore()

    def poll_once(self, **kwargs):
        self.events.append("receipts")
        return {"allocated": 0, "pending": 0, "orphaned": 0,
                "cursor_held": False, "has_more": False}


class FakeReorgGuard:
    def __init__(self, events, open_alerts=0):
        self.events, self.open_alerts = events, open_alerts

    def reconcile_once(self, **kwargs):
        self.events.append("reorgs")
        return {"open_alerts": self.open_alerts}


class FakeWorker:
    def __init__(self, events):
        self.events = events

    async def run_once(self, *, limit):
        self.events.append("spend")
        return {"settled": 1}


class CollectiveAccountingRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_blocks_owner_actions_while_receipt_scan_is_incomplete(self):
        events = []
        monitor = FakeReceiptMonitor(events)
        monitor.poll_once = lambda **kwargs: (
            events.append("receipts") or {
                "allocated": 0, "pending": 1, "orphaned": 0,
                "cursor_held": True, "has_more": True,
            }
        )
        async def close_period():
            events.append("profit-close")
            return {"status": "completed"}
        async def owner_profit():
            events.append("owner-profit")
            return {"status": "completed"}
        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=monitor, reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
            profit_period_close_cycle=close_period,
            owner_profit_payout_cycle=owner_profit,
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "payouts_blocked")
        self.assertIn("receipt intake", result["reason"])
        self.assertEqual(events, ["receipts", "reorgs", "balances"])

    async def test_runtime_closes_profit_period_before_owner_payout_and_spending(self):
        events = []
        async def close_period():
            events.append("profit-close")
            return {"status": "completed", "closed": 2, "blocked": 0,
                    "pending": 0, "uncertain": 0, "failed": 0}
        async def owner_profit():
            events.append("owner-profit")
            return {"status": "completed", "settled": 1, "pending": 0,
                    "blocked": 0, "failed": 0, "uncertain": 0}
        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=FakeReceiptMonitor(events),
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
            profit_period_close_cycle=close_period,
            owner_profit_payout_cycle=owner_profit,
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(events, [
            "receipts", "reorgs", "balances", "profit-close",
            "owner-profit", "balances", "spend",
        ])

    async def test_runtime_blocks_when_any_agent_period_cannot_be_closed(self):
        events = []
        async def close_period():
            events.append("profit-close")
            return {"status": "blocked", "closed": 1, "blocked": 1,
                    "pending": 0, "uncertain": 0, "failed": 1}
        async def owner_profit():
            events.append("owner-profit")
            return {"status": "completed"}
        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=FakeReceiptMonitor(events),
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
            profit_period_close_cycle=close_period,
            owner_profit_payout_cycle=owner_profit,
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "payouts_blocked")
        self.assertIsNone(result["spending"])
        self.assertEqual(events, ["receipts", "reorgs", "balances", "profit-close"])

    def test_runtime_requires_owner_payout_worker_when_auto_closing_periods(self):
        events = []
        with self.assertRaisesRegex(ValueError, "requires the owner-profit payout worker"):
            CollectiveTreasuryAccountingRuntime(
                receipt_monitor=FakeReceiptMonitor(events),
                reorg_guard=FakeReorgGuard(events),
                balance_check=lambda: {"fully_reconciled": True},
                worker=FakeWorker(events), network="base-sepolia", asset="USDC",
                profit_period_close_cycle=lambda: None,
            )

    async def test_runtime_reconciles_before_spending(self):
        events = []
        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=FakeReceiptMonitor(events),
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(events, ["receipts", "reorgs", "balances", "spend"])

    async def test_runtime_runs_owner_overflow_before_agent_spending_and_reconciles_again(self):
        events = []
        monitor = FakeReceiptMonitor(events)
        monitor.store.over_cap = True

        async def owner_sweep():
            events.append("owner-overflow")
            monitor.store.over_cap = False
            return {"status": "settled"}

        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=monitor,
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
            owner_overflow_sweep_cycle=owner_sweep,
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(events, [
            "receipts", "reorgs", "balances", "owner-overflow", "balances", "spend"
        ])

    async def test_runtime_blocks_over_cap_when_owner_sweep_is_not_wired(self):
        events = []
        monitor = FakeReceiptMonitor(events)
        monitor.store.over_cap = True
        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=monitor,
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "payouts_blocked")
        self.assertIn("no owner overflow worker", result["reason"])
        self.assertEqual(events, ["receipts", "reorgs", "balances"])

    async def test_runtime_blocks_spending_when_balance_check_fails(self):
        events = []
        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=FakeReceiptMonitor(events),
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": False}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "payouts_blocked")
        self.assertEqual(events, ["receipts", "reorgs", "balances"])

    async def test_runtime_blocks_spending_when_reorg_scan_has_more_batches(self):
        events = []
        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=FakeReceiptMonitor(events),
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
        )
        runtime.reorg_guard.reconcile_once = lambda **kwargs: (
            events.append("reorgs") or {"open_alerts": 0, "has_more": True}
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "payouts_blocked")
        self.assertIn("incomplete", result["reason"])
        self.assertEqual(events, ["receipts", "reorgs", "balances"])

    async def test_runtime_blocks_spending_when_reorg_alert_open(self):
        events = []
        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=FakeReceiptMonitor(events),
            reorg_guard=FakeReorgGuard(events, open_alerts=1),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "payouts_blocked")
        self.assertEqual(events, ["receipts", "reorgs", "balances"])


    async def test_runtime_fails_closed_on_unrecognized_owner_profit_result(self):
        events = []

        async def owner_profit():
            events.append("owner-profit")
            return {"status": "failed"}

        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=FakeReceiptMonitor(events),
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
            owner_profit_payout_cycle=owner_profit,
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "payouts_blocked")
        self.assertIn("did not confirm", result["reason"])
        self.assertIsNone(result["spending"])
        self.assertEqual(events, ["receipts", "reorgs", "balances", "owner-profit"])

    async def test_runtime_fails_closed_on_malformed_owner_profit_result(self):
        events = []

        async def owner_profit():
            events.append("owner-profit")
            return []

        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=FakeReceiptMonitor(events),
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
            owner_profit_payout_cycle=owner_profit,
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "payouts_blocked")
        self.assertIsNone(result["spending"])
        self.assertEqual(events, ["receipts", "reorgs", "balances", "owner-profit"])

    async def test_runtime_fails_closed_on_unclean_overflow_worker_result(self):
        events = []
        monitor = FakeReceiptMonitor(events)
        monitor.store.over_cap = True

        async def owner_sweep():
            events.append("owner-overflow")
            monitor.store.over_cap = False
            return {"status": "pending", "uncertain": 1}

        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=monitor,
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
            owner_overflow_sweep_cycle=owner_sweep,
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "payouts_blocked")
        self.assertIsNone(result["spending"])
        self.assertEqual(events, ["receipts", "reorgs", "balances", "owner-overflow"])


    async def test_runtime_accepts_clean_owner_profit_completion_and_reconciles_again(self):
        events = []

        async def owner_profit():
            events.append("owner-profit")
            return {"status": "completed", "paid": 1, "pending": 0, "blocked": 0}

        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=FakeReceiptMonitor(events),
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
            owner_profit_payout_cycle=owner_profit,
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(events, [
            "receipts", "reorgs", "balances", "owner-profit", "balances", "spend"
        ])

    async def test_runtime_rejects_success_status_with_pending_owner_profit_count(self):
        events = []

        async def owner_profit():
            events.append("owner-profit")
            return {"status": "completed", "pending": 1}

        runtime = CollectiveTreasuryAccountingRuntime(
            receipt_monitor=FakeReceiptMonitor(events),
            reorg_guard=FakeReorgGuard(events),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
            owner_profit_payout_cycle=owner_profit,
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "payouts_blocked")
        self.assertIsNone(result["spending"])
        self.assertEqual(events, ["receipts", "reorgs", "balances", "owner-profit"])


if __name__ == "__main__":
    unittest.main()
