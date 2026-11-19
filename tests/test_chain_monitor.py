import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import AgentFinanceStore, VerifiedTransfer, Wallet
from economy.chain_monitor import (
    ChainMonitor, ChainTransferObservation, MonitoredAsset, TransferPage,
)


class FakeChain:
    def __init__(self, transfers=()):
        self.transfers = tuple(transfers)
        self.calls = []

    def fetch_transfers(self, **kwargs):
        self.calls.append(kwargs)
        return TransferPage(self.transfers, "cursor-1")


def observation(**overrides):
    values = dict(
        network="testnet", asset="USDC", token_contract="0xToken",
        tx_hash="0xTx1", transfer_ref="log:0", source="0xCustomer",
        destination="0xAgent", amount_minor=2500, block_number=100,
        block_hash="0xBlock100", confirmations=12, canonical=True, finalized=True,
    )
    values.update(overrides)
    return ChainTransferObservation(**values)


class ChainMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.finance = AgentFinanceStore(Path(self.tmp.name) / "finance.sqlite3")
        self.finance.register_wallet(Wallet("agent-a", "agent", "testnet", "USDC", "0xAgent"))
        self.chain = FakeChain([observation()])
        self.monitor = ChainMonitor(
            self.finance, self.chain,
            MonitoredAsset("testnet", "USDC", "0xToken", 10),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_credits_only_finalized_matching_asset_once(self):
        result = self.monitor.poll_once(period_id="2026-11")
        self.assertEqual(result["credited"], 1)
        self.assertEqual(result["pending"], 0)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.finance.record_receipt(
                "agent-a",
                VerifiedTransfer(
                    "testnet", "USDC", "0xTx1", "log:0", "0xAgent", 2500, 12, True,
                    source="0xCustomer",
                ),
                period_id="2026-11",
            )
        self.assertEqual(self.monitor.poll_once(period_id="2026-11")["credited"], 0)

    def test_waits_for_confirmation_threshold_and_finality(self):
        self.chain.transfers = (observation(confirmations=3, finalized=False),)
        result = self.monitor.poll_once(period_id="2026-11")
        self.assertEqual(result["pending"], 1)
        self.assertEqual(result["credited"], 0)

    def test_wrong_contract_is_rejected(self):
        self.chain.transfers = (observation(token_contract="0xFake"),)
        with self.assertRaisesRegex(ValueError, "token contract"):
            self.monitor.poll_once(period_id="2026-11")

    def test_noncanonical_transfer_is_not_credited(self):
        self.chain.transfers = (observation(canonical=False),)
        result = self.monitor.poll_once(period_id="2026-11")
        self.assertEqual(result["orphaned"], 1)
        self.assertEqual(result["credited"], 0)

    def test_reorg_after_credit_creates_alert_not_silent_reversal(self):
        self.monitor.poll_once(period_id="2026-11")
        self.chain.transfers = (observation(canonical=False),)
        result = self.monitor.poll_once(period_id="2026-11")
        self.assertEqual(result["reorg_alerts"], 1)
        self.assertEqual(len(self.monitor.list_reorg_alerts()), 1)

    def test_block_hash_change_after_credit_creates_alert(self):
        self.monitor.poll_once(period_id="2026-11")
        self.chain.transfers = (observation(block_hash="0xDifferentBlock"),)
        result = self.monitor.poll_once(period_id="2026-11")
        self.assertEqual(result["reorg_alerts"], 1)


    def test_reorg_alert_blocks_profit_close_and_acknowledgement_does_not_clear_hold(self):
        self.monitor.poll_once(period_id="2026-11")
        self.chain.transfers = (observation(canonical=False),)
        self.monitor.poll_once(period_id="2026-11")
        with self.assertRaisesRegex(ValueError, "reorganization alert"):
            self.finance.close_profit_period(
                "agent-a", "master", network="testnet", asset="USDC",
                period_id="2026-11", reserve_bps=0, owner_share_bps=5000,
            )
        self.monitor.resolve_reorg_alert(
            "testnet", "0xTx1", "log:0",
            resolution_note="Reviewed explorer and opened manual ledger adjustment",
        )
        self.assertEqual(len(self.monitor.list_reorg_alerts()), 1)


    def test_period_resolver_assigns_each_transfer_by_block_timestamp(self):
        self.chain.transfers = (
            observation(block_timestamp="2026-10-31T23:59:00+00:00"),
        )
        monitor = ChainMonitor(
            self.finance, self.chain,
            MonitoredAsset("testnet", "USDC", "0xToken", 10),
            period_resolver=lambda timestamp: "2026-10" if timestamp.startswith("2026-10") else "2026-11",
        )
        monitor.poll_once(period_id="fallback")
        with self.finance._connect() as db:
            row = db.execute(
                "SELECT period_id FROM finance_events WHERE tx_hash='0xTx1'"
            ).fetchone()
        self.assertEqual(row["period_id"], "2026-10")

    def test_cursor_is_forwarded_and_persisted(self):
        self.monitor.poll_once(period_id="2026-11")
        self.monitor.poll_once(period_id="2026-11")
        self.assertEqual(self.chain.calls[1]["cursor"], "cursor-1")


if __name__ == "__main__":
    unittest.main()
