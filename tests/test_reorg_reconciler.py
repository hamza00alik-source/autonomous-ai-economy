import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import AgentFinanceStore, Wallet
from economy.chain_monitor import ChainMonitor, ChainTransferObservation, MonitoredAsset, TransferPage
from economy.reorg_reconciler import ChainReorgReconciler


class Source:
    def fetch_transfers(self, **kwargs):
        return TransferPage((ChainTransferObservation(
            network="testnet", asset="USDC", token_contract="0xToken",
            tx_hash="0xTx", transfer_ref="log:1", source="0xCustomer",
            destination="0xAgent", amount_minor=123, block_number=100,
            block_hash="0xBlock", confirmations=20, canonical=True,
            finalized=True, block_timestamp="2026-11-19T10:00:00+00:00",
        ),), None)


class Verifier:
    def __init__(self, canonical=True):
        self.canonical = canonical
        self.calls = []
    def finalized_block_number(self):
        return 120
    def is_transfer_canonical(self, **kwargs):
        self.calls.append(kwargs)
        return self.canonical


class ReorgReconcilerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.finance = AgentFinanceStore(Path(self.tmp.name) / "finance.sqlite3")
        self.finance.register_wallet(Wallet("agent-a", "agent", "testnet", "USDC", "0xAgent"))
        ChainMonitor(self.finance, Source(), MonitoredAsset("testnet", "USDC", "0xToken", 10)).poll_once(period_id="2026-11")

    def tearDown(self):
        self.tmp.cleanup()

    def test_disappeared_transfer_creates_alert(self):
        verifier = Verifier(canonical=False)
        result = ChainReorgReconciler(
            self.finance, verifier, network="testnet", token_contract="0xToken",
            lookback_blocks=50,
        ).reconcile_once()
        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["reorg_alerts"], 1)
        self.assertEqual(len(verifier.calls), 1)
        with self.finance._connect() as db:
            status = db.execute("SELECT status FROM chain_monitor_events").fetchone()["status"]
        self.assertEqual(status, "reorg_alert")

    def test_canonical_transfer_stays_credited(self):
        result = ChainReorgReconciler(
            self.finance, Verifier(True), network="testnet", token_contract="0xToken",
            lookback_blocks=50,
        ).reconcile_once()
        self.assertEqual(result["reorg_alerts"], 0)
        with self.finance._connect() as db:
            status = db.execute("SELECT status FROM chain_monitor_events").fetchone()["status"]
        self.assertEqual(status, "credited")

    def test_rpc_error_fails_closed_without_changing_status(self):
        class Broken(Verifier):
            def is_transfer_canonical(self, **kwargs):
                raise RuntimeError("RPC unavailable")
        with self.assertRaisesRegex(RuntimeError, "RPC unavailable"):
            ChainReorgReconciler(
                self.finance, Broken(), network="testnet", token_contract="0xToken",
            ).reconcile_once()
        with self.finance._connect() as db:
            status = db.execute("SELECT status FROM chain_monitor_events").fetchone()["status"]
        self.assertEqual(status, "credited")

    def test_old_transfer_outside_rolling_window_is_not_queried(self):
        verifier = Verifier()
        result = ChainReorgReconciler(
            self.finance, verifier, network="testnet", token_contract="0xToken",
            lookback_blocks=10,
        ).reconcile_once()
        self.assertEqual(result["checked"], 0)
        self.assertEqual(verifier.calls, [])


if __name__ == "__main__":
    unittest.main()
