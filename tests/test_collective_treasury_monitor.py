import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import VerifiedTransfer
from economy.chain_monitor import ChainTransferObservation, TransferPage
from economy.collective_treasury import CollectiveTreasuryStore, TreasuryWallet
from economy.collective_treasury_monitor import CollectiveTreasuryReceiptMonitor


WALLET = "0x" + "a" * 40
PAYER = "0x" + "b" * 40
TOKEN = "0x" + "1" * 40
TX = "0x" + "c" * 64


def observation(*, tx=TX, amount=5000, source=PAYER, finalized=True, canonical=True):
    return ChainTransferObservation(
        "base-sepolia", "USDC", TOKEN, tx, "log:0", source, WALLET,
        amount, 100, "0x" + "d" * 64, 12 if finalized else 1,
        canonical, finalized, "2026-11-19T12:00:00+00:00",
    )


class FakeSource:
    def __init__(self, transfers=()):
        self.transfers = tuple(transfers)
        self.calls = []

    def fetch_transfers(self, **kwargs):
        self.calls.append(kwargs)
        return TransferPage(self.transfers, "120")


class CollectiveTreasuryReceiptMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CollectiveTreasuryStore(Path(self.tmp.name) / "treasury.sqlite3")
        self.store.register_treasury_wallet(TreasuryWallet(
            "test-provider", "wallet-1", "base-sepolia", "USDC", WALLET
        ))
        self.store.add_agent(
            "agent-a", "base-sepolia", "USDC",
            daily_limit_minor=10000, per_tx_limit_minor=5000,
            allowed_destinations=("0x" + "e" * 40,),
        )
        self.source = FakeSource([observation()])
        self.monitor = CollectiveTreasuryReceiptMonitor(
            self.store, self.source, token_contract=TOKEN
        )

    def tearDown(self):
        self.tmp.cleanup()

    def intent(self, ref="invoice:1", amount=5000):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", amount, attribution_ref=ref
        )

    def test_exact_payer_and_amount_routes_to_agent(self):
        self.intent()
        self.monitor.bind_payer("invoice:1", PAYER)
        result = self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        self.assertEqual(result["allocated"], 1)
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 5000)

    def test_unmatched_payer_or_amount_goes_to_suspense(self):
        self.intent()
        self.monitor.bind_payer("invoice:1", "0x" + "f" * 40)
        result = self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        self.assertEqual(result["unallocated"], 1)
        self.assertEqual(self.store.balance("treasury:unallocated", "base-sepolia", "USDC"), 5000)

    def test_ambiguous_identical_intents_go_to_suspense(self):
        self.intent("invoice:1")
        self.intent("invoice:2")
        self.monitor.bind_payer("invoice:1", PAYER)
        self.monitor.bind_payer("invoice:2", PAYER)
        result = self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        self.assertEqual(result["unallocated"], 1)
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 0)

    def test_unfinalized_or_noncanonical_observation_is_not_credited(self):
        self.source.transfers = (observation(finalized=False),)
        pending = self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        self.assertEqual(pending["pending"], 1)
        self.source.transfers = (observation(tx="0x" + "f" * 64, canonical=False),)
        orphaned = self.monitor.poll_once(
            network="base-sepolia", asset="USDC", period_id="2026-11"
        )
        self.assertEqual(orphaned["orphaned"], 1)
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 0)

    def test_binding_cannot_be_changed_after_creation(self):
        self.intent()
        self.monitor.bind_payer("invoice:1", PAYER)
        with self.assertRaisesRegex(ValueError, "already bound"):
            self.monitor.bind_payer("invoice:1", "0x" + "f" * 40)

    def test_page_replay_does_not_double_credit(self):
        self.intent()
        self.monitor.bind_payer("invoice:1", PAYER)
        self.monitor.poll_once(network="base-sepolia", asset="USDC", period_id="2026-11")
        result = self.monitor.poll_once(network="base-sepolia", asset="USDC", period_id="2026-11")
        self.assertEqual(result["allocated"], 1)
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 5000)
        self.assertEqual(self.store.balance("agent:agent-a", "base-sepolia", "USDC"), 5000)


if __name__ == "__main__":
    unittest.main()
