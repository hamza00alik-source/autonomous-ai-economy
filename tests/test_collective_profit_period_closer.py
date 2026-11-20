import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from economy.agent_finance import VerifiedTransfer
from economy.collective_treasury import CollectiveTreasuryStore, TreasuryWallet
from economy.collective_profit_period_closer import CollectiveProfitPeriodCloser


WALLET = "0x" + "a" * 40
PAYER = "0x" + "b" * 40


class CollectiveProfitPeriodCloserTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CollectiveTreasuryStore(
            Path(self.tmp.name) / "treasury.sqlite3",
            owner_principal_id="owner-principal",
        )
        self.store.register_treasury_wallet(TreasuryWallet(
            "provider", "shared", "base-sepolia", "USDC", WALLET,
        ))
        self.store.add_agent(
            "agent-a", "base-sepolia", "USDC", daily_limit_minor=100_000,
            per_tx_limit_minor=50_000, allowed_destinations=("0x" + "c" * 40,),
        )
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 8000,
            attribution_ref="invoice:october",
        )
        self.store.record_receipt(
            VerifiedTransfer(
                "base-sepolia", "USDC", "0x" + "d" * 64, "log:1",
                WALLET, 8000, 12, True, source=PAYER,
            ),
            period_id="2026-10", agent_id="agent-a",
            attribution_ref="invoice:october",
        )
        self.closer = CollectiveProfitPeriodCloser(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_closes_every_agent_period_with_fixed_50_percent_owner_share(self):
        result = asyncio.run(self.closer.run_once(
            network="base-sepolia", asset="USDC", period_id="2026-10",
        ))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["closed"], 1)
        close = self.store.get_period_close(
            "agent-a", "base-sepolia", "USDC", "2026-10",
        )
        self.assertEqual(close["owner_share_minor"], 4000)
        self.assertEqual(close["agent_retained_minor"], 4000)
        self.assertEqual(self.store.balance("master:owner", "base-sepolia", "USDC"), 4000)
        again = asyncio.run(self.closer.run_once(
            network="base-sepolia", asset="USDC", period_id="2026-10",
        ))
        self.assertEqual(again["status"], "completed")
        self.assertEqual(self.store.balance("master:owner", "base-sepolia", "USDC"), 4000)

    def test_refuses_to_close_the_current_utc_month(self):
        current_period = datetime.now(timezone.utc).strftime("%Y-%m")
        with self.assertRaisesRegex(ValueError, "completed prior UTC month"):
            asyncio.run(self.closer.run_once(
                network="base-sepolia", asset="USDC", period_id=current_period,
            ))

    def test_unresolved_agent_spend_blocks_period_close(self):
        self.store.reserve_spend(
            "agent-a", "base-sepolia", "USDC", "0x" + "c" * 40, 1000,
            idempotency_key="open-expense", period_id="2026-10",
        )
        result = asyncio.run(self.closer.run_once(
            network="base-sepolia", asset="USDC", period_id="2026-10",
        ))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"], 1)
        self.assertIsNone(self.store.get_period_close(
            "agent-a", "base-sepolia", "USDC", "2026-10",
        ))

    def test_default_runtime_callback_targets_previous_utc_month(self):
        callback = self.closer.runtime_callback(network="base-sepolia")
        result = asyncio.run(callback())
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
