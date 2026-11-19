import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import AgentFinanceStore, VerifiedTransfer, Wallet


class AgentFinanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AgentFinanceStore(Path(self.tmp.name) / "finance.sqlite3")
        self.store.register_wallet(Wallet("master", "master", "base", "USDC", "0xMaster"))

    def tearDown(self):
        self.tmp.cleanup()

    def transfer(self, tx, amount, destination="0xAgent", verified=True):
        return VerifiedTransfer("base", "USDC", tx, "0", destination,
                                 amount, 12, verified)

    def test_receipt_requires_verified_chain_proof_and_registered_destination(self):
        with self.assertRaisesRegex(ValueError, "verified"):
            self.store.record_receipt("agent-a", self.transfer("tx1", 100, verified=False), period_id="2026-11")
        with self.assertRaisesRegex(ValueError, "destination"):
            self.store.record_receipt("agent-a", self.transfer("tx2", 100, "0xAttacker"), period_id="2026-11")
        bad_expense = VerifiedTransfer("base", "USDC", "tx3", "0", "0xVendor",
                                       100, 12, True, source="0xAttacker")
        with self.assertRaisesRegex(ValueError, "source"):
            self.store.record_expense("agent-a", bad_expense, period_id="2026-11")

    def test_duplicate_chain_transfer_is_rejected(self):
        transfer = self.transfer("tx1", 100)
        self.store.record_receipt("agent-a", transfer, period_id="2026-11")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.store.record_receipt("agent-a", transfer, period_id="2026-11")

    def test_profit_is_calculated_after_expenses_and_reserve(self):
        self.store.record_receipt("agent-a", self.transfer("income", 100_000), period_id="nov")
        # Expenses are represented as independently verified outgoing transfer events.
        # For this initial ledger, the chain adapter binds the agent's wallet as the
        # account whose balance decreased and supplies its normalized transfer proof.
        self.store.register_wallet(Wallet("agent-a", "agent", "base", "USDC", "0xAgent"))
        expense = VerifiedTransfer("base", "USDC", "expense", "0", "0xVendor",
                                   20_000, 12, True, source="0xAgent")
        self.store.record_expense("agent-a", expense, period_id="nov")
        result = self.store.close_profit_period(
            "agent-a", "master", network="base", asset="USDC", period_id="nov",
            reserve_bps=1000, owner_share_bps=5000,
        )
        self.assertEqual(result["gross_income_minor"], 100_000)
        self.assertEqual(result["expenses_minor"], 20_000)
        self.assertEqual(result["operating_profit_minor"], 80_000)
        self.assertEqual(result["reserve_minor"], 8_000)
        self.assertEqual(result["master_due_minor"], 36_000)
        self.assertEqual(result["agent_retained_minor"], 36_000)
        self.assertEqual(result["status"], "pending_payout")

    def test_period_close_is_idempotent(self):
        self.store.record_receipt("agent-a", self.transfer("income", 1000), period_id="nov")
        first = self.store.close_profit_period(
            "agent-a", "master", network="base", asset="USDC", period_id="nov",
            reserve_bps=0, owner_share_bps=5000,
        )
        second = self.store.close_profit_period(
            "agent-a", "master", network="base", asset="USDC", period_id="nov",
            reserve_bps=9000, owner_share_bps=1000,
        )
        self.assertEqual(first, second)

    def test_owner_payout_requires_verified_transfer_to_master_wallet(self):
        self.store.record_receipt("agent-a", self.transfer("income", 1000), period_id="nov")
        self.store.close_profit_period(
            "agent-a", "master", network="base", asset="USDC", period_id="nov",
            reserve_bps=0, owner_share_bps=5000,
        )
        unverified = VerifiedTransfer("base", "USDC", "out1", "0", "0xMaster",
                                      500, 12, False, source="0xAgent")
        with self.assertRaisesRegex(ValueError, "verified"):
            self.store.mark_owner_distribution_paid(
                "agent-a", "base", "USDC", "nov", transfer=unverified,
            )
        wrong_destination = VerifiedTransfer("base", "USDC", "out1", "0", "0xAttacker",
                                              500, 12, True, source="0xAgent")
        with self.assertRaisesRegex(ValueError, "destination"):
            self.store.mark_owner_distribution_paid(
                "agent-a", "base", "USDC", "nov", transfer=wrong_destination,
            )
        wrong_amount = VerifiedTransfer("base", "USDC", "out1", "0", "0xMaster",
                                         499, 12, True, source="0xAgent")
        with self.assertRaisesRegex(ValueError, "amount"):
            self.store.mark_owner_distribution_paid(
                "agent-a", "base", "USDC", "nov", transfer=wrong_amount,
            )
        payout = VerifiedTransfer("base", "USDC", "out1", "0", "0xMaster",
                                  500, 12, True, source="0xAgent")
        self.store.mark_owner_distribution_paid(
            "agent-a", "base", "USDC", "nov", transfer=payout,
        )
        self.assertEqual(self.store.get_profit_period("agent-a", "base", "USDC", "nov")["status"], "paid")


if __name__ == "__main__":
    unittest.main()
