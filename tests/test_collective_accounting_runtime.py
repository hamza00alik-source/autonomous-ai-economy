import tempfile
import unittest
from pathlib import Path

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

    def test_canonical_receipt_remains_healthy(self):
        guard = CollectiveTreasuryReorgGuard(self.monitor, Verifier(canonical=True))
        result = guard.reconcile_once(network="base-sepolia", asset="USDC")
        self.assertEqual(result["reorg_alerts"], 0)
        self.assertEqual(result["open_alerts"], 0)


class FakeReceiptMonitor:
    def __init__(self, events):
        self.events = events

    def poll_once(self, **kwargs):
        self.events.append("receipts")
        return {"allocated": 0}


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

    async def test_runtime_blocks_spending_when_reorg_alert_open(self):
        events = []
        runtime = CollectiveTreasuryAccountingRuntime(
            store=None, receipt_monitor=FakeReceiptMonitor(events),
            reorg_guard=FakeReorgGuard(events, open_alerts=1),
            balance_check=lambda: (events.append("balances") or {"fully_reconciled": True}),
            worker=FakeWorker(events), network="base-sepolia", asset="USDC",
        )
        result = await runtime.run_once(period_id="2026-11")
        self.assertEqual(result["status"], "payouts_blocked")
        self.assertEqual(events, ["receipts", "reorgs", "balances"])


if __name__ == "__main__":
    unittest.main()
