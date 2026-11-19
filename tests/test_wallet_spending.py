import tempfile
import unittest
from pathlib import Path

from economy.wallet_spending import SpendPolicy, WalletSpendController


class WalletSpendControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.controller = WalletSpendController(Path(self.tmp.name) / "spend.sqlite3")
        self.controller.configure_policy(SpendPolicy(
            agent_id="agent-1", network="base", asset="USDC",
            daily_limit_minor=10_000, per_transaction_limit_minor=4_000,
            allowed_destinations=("0xCompute", "0xData"),
        ))

    def tearDown(self):
        self.tmp.cleanup()

    def test_allowlisted_spend_is_reserved_without_per_transaction_approval(self):
        result = self.controller.reserve("agent-1", "base", "USDC", "0xCompute", 2500,
                                         idempotency_key="job-1")
        self.assertEqual(result.status, "reserved")

    def test_rejects_unallowlisted_destination_and_limits(self):
        with self.assertRaisesRegex(ValueError, "allowlisted"):
            self.controller.reserve("agent-1", "base", "USDC", "0xAttacker", 100,
                                     idempotency_key="job-1")
        with self.assertRaisesRegex(ValueError, "per-transaction"):
            self.controller.reserve("agent-1", "base", "USDC", "0xCompute", 5000,
                                     idempotency_key="job-2")

    def test_daily_budget_counts_pending_and_settled_spends(self):
        first = self.controller.reserve("agent-1", "base", "USDC", "0xCompute", 4000,
                                         idempotency_key="job-1")
        self.controller.mark_broadcast(first.reservation_id, "0xtx1")
        self.controller.mark_settled(first.reservation_id, tx_hash="0xtx1",
                                     verified=True, source="agent-1",
                                     destination="0xCompute", amount_minor=4000)
        self.controller.reserve("agent-1", "base", "USDC", "0xData", 4000,
                                idempotency_key="job-2")
        with self.assertRaisesRegex(ValueError, "daily budget"):
            self.controller.reserve("agent-1", "base", "USDC", "0xData", 3000,
                                    idempotency_key="job-3")

    def test_settlement_must_match_exact_reservation(self):
        item = self.controller.reserve("agent-1", "base", "USDC", "0xCompute", 500,
                                        idempotency_key="job-1")
        self.controller.mark_broadcast(item.reservation_id, "0xtx")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.controller.mark_settled(item.reservation_id, tx_hash="0xtx",
                                         verified=True, source="agent-1",
                                         destination="0xAttacker", amount_minor=500)
        with self.assertRaisesRegex(ValueError, "verified"):
            self.controller.mark_settled(item.reservation_id, tx_hash="0xtx",
                                         verified=False, source="agent-1",
                                         destination="0xCompute", amount_minor=500)

    def test_idempotency_key_cannot_be_reused_for_different_request(self):
        self.controller.reserve("agent-1", "base", "USDC", "0xCompute", 500,
                                idempotency_key="job-1")
        with self.assertRaisesRegex(ValueError, "different spend"):
            self.controller.reserve("agent-1", "base", "USDC", "0xData", 500,
                                    idempotency_key="job-1")

    def test_pause_blocks_new_spend(self):
        self.controller.pause("agent-1", "base", "USDC")
        with self.assertRaisesRegex(ValueError, "enabled spend policy"):
            self.controller.reserve("agent-1", "base", "USDC", "0xCompute", 100,
                                    idempotency_key="job-1")


if __(!"__main__"):
    unittest.main()
