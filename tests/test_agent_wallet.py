import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import VerifiedTransfer
from economy.agent_wallet import AgentTreasuryWallet
from economy.collective_treasury import CollectiveTreasuryStore, TreasuryWallet


class FakeReceiptMonitor:
    def __init__(self):
        self.bindings = {}

    def bind_payer(self, attribution_ref, payer_address):
        if attribution_ref in self.bindings and self.bindings[attribution_ref] != payer_address:
            raise ValueError("payer binding is immutable")
        self.bindings[attribution_ref] = payer_address


class AgentTreasuryWalletTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CollectiveTreasuryStore(Path(self.tmp.name) / "treasury.sqlite3")
        self.address = "0x" + "a" * 40
        self.destination = "0x" + "b" * 40
        self.payer = "0x" + "d" * 40
        self.store.register_treasury_wallet(TreasuryWallet(
            "coinbase-cdp", "treasury", "base-sepolia", "USDC", self.address
        ))
        self.store.add_agent(
            "agent-a", "base-sepolia", "USDC",
            daily_limit_minor=10_000, per_tx_limit_minor=5_000,
            allowed_destinations=(self.destination,),
        )
        self.monitor = FakeReceiptMonitor()
        self.agent = AgentTreasuryWallet(
            self.store, agent_id="agent-a", network="base-sepolia",
            receipt_monitor=self.monitor,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_agent_gets_real_shared_address_and_receive_instruction(self):
        instruction = self.agent.prepare_receive(
            2_500, attribution_ref="invoice:agent-a:1", payer_address=self.payer,
        )
        self.assertEqual(instruction["address"], self.address)
        self.assertEqual(instruction["expected_amount_minor"], 2_500)
        self.assertEqual(self.monitor.bindings["invoice:agent-a:1"], self.payer)
        self.assertEqual(self.agent.wallet()["max_balance_usd"], 500)

    def test_agent_can_request_spend_without_receiving_signer(self):
        self.agent.prepare_receive(
            5_000, attribution_ref="invoice:agent-a:2", payer_address=self.payer,
        )
        transfer = VerifiedTransfer(
            "base-sepolia", "USDC", "0x" + "1" * 64, "log:1",
            self.address, 5_000, 12, True, source=self.payer,
        )
        self.store.record_receipt(
            transfer, period_id="2026-11", attribution_ref="invoice:agent-a:2",
            agent_id="agent-a",
        )
        reservation = self.agent.request_spend(
            self.destination, 2_000, idempotency_key="agent-a:job:1",
            period_id="2026-11",
        )
        self.assertTrue(reservation.startswith("spend_"))
        self.assertEqual(self.agent.wallet()["available_minor"], 3_000)
        self.assertFalse(hasattr(self.agent, "signer"))
        self.assertFalse(hasattr(self.agent, "private_key"))

    def test_agent_facade_is_bound_to_its_own_identity(self):
        self.store.add_agent(
            "agent-b", "base-sepolia", "USDC",
            daily_limit_minor=10_000, per_tx_limit_minor=5_000,
            allowed_destinations=(self.destination,),
        )
        self.assertEqual(self.agent.wallet()["agent_id"], "agent-a")


if __name__ == "__main__":
    unittest.main()
