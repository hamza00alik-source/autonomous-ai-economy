import tempfile
import unittest
from pathlib import Path

from economy.chain_monitor import ChainTransferObservation, TransferPage
from economy.collective_treasury import CollectiveTreasuryStore, TreasuryWallet
from economy.collective_treasury_monitor import CollectiveTreasuryReceiptMonitor
from economy.collective_accounting_runtime import CollectiveTreasuryReorgGuard


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


if __name__ == "__main__":
    unittest.main()
