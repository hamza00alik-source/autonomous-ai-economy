import asyncio
import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import VerifiedTransfer
from economy.collective_treasury import CollectiveTreasuryStore, TreasuryWallet
from economy.owner_overflow_sweep import OwnerOverflowSweepWorker


TREASURY = "0x" + "a" * 40
OWNER = "0x" + "e" * 40
PAYER = "0x" + "d" * 40


class OwnerOverflowSweepTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CollectiveTreasuryStore(
            Path(self.tmp.name) / "treasury.sqlite3",
            owner_principal_id="authenticated-owner-1",
        )
        self.store.register_treasury_wallet(TreasuryWallet(
            "coinbase-cdp", "cdp-account", "base-sepolia", "USDC", TREASURY
        ))
        self.store.add_agent(
            "agent-a", "base-sepolia", "USDC", daily_limit_minor=100_000_000,
            per_tx_limit_minor=50_000_000, allowed_destinations=(OWNER,),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def receipt(self, tx_digit, log, amount):
        return VerifiedTransfer(
            "base-sepolia", "USDC", "0x" + tx_digit * 64, f"log:{log}",
            TREASURY, amount, 12, True, source=PAYER,
        )

    def test_owner_only_cap_increase_is_audited_and_monotonic(self):
        with self.assertRaises(PermissionError):
            self.store.increase_shared_wallet_cap(
                "base-sepolia", "USDC", 750_000_000,
                owner_principal_id="agent-a", reason="agent asks for more capacity",
            )
        result = self.store.increase_shared_wallet_cap(
            "base-sepolia", "USDC", 750_000_000,
            owner_principal_id="authenticated-owner-1",
            reason="verified retained earnings justify expansion",
        )
        self.assertEqual(result["old_cap_minor"], 500_000_000)
        self.assertEqual(result["new_cap_minor"], 750_000_000)
        with self.assertRaisesRegex(ValueError, "must be increases"):
            self.store.increase_shared_wallet_cap(
                "base-sepolia", "USDC", 600_000_000,
                owner_principal_id="authenticated-owner-1", reason="attempt to reduce",
            )

    def test_overflow_sweep_pays_only_unallocated_excess_and_reconciles(self):
        self.store.record_receipt(self.receipt("1", 1, 600_000_000), period_id="2026-11")
        with self.assertRaisesRegex(ValueError, "not configured"):
            self.store.reserve_owner_overflow_sweep(
                "base-sepolia", "USDC", period_id="2026-11",
                idempotency_key="overflow-1",
            )
        self.store.configure_owner_payout_address(
            "base-sepolia", "USDC", OWNER,
            owner_principal_id="authenticated-owner-1",
            reason="owner-controlled public payout destination",
        )
        sweep = self.store.reserve_owner_overflow_sweep(
            "base-sepolia", "USDC", period_id="2026-11",
            idempotency_key="overflow-1",
        )
        self.assertEqual(sweep["amount_minor"], 100_000_000)
        self.assertEqual(sweep["destination_address"], OWNER)
        self.assertTrue(self.store.claim_owner_overflow_sweep(sweep["sweep_id"]))
        tx_hash = "0x" + "2" * 64
        self.store.record_owner_overflow_sweep_tx(sweep["sweep_id"], tx_hash)
        verified = VerifiedTransfer(
            "base-sepolia", "USDC", tx_hash, "log:2", OWNER,
            100_000_000, 12, True, source=TREASURY,
        )
        self.store.settle_owner_overflow_sweep(sweep["sweep_id"], verified)
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 500_000_000)
        self.assertEqual(self.store.balance("treasury:unallocated", "base-sepolia", "USDC"),
                         500_000_000)
        self.assertTrue(self.store.reconciliation_snapshot(
            "base-sepolia", "USDC"
        )["balanced"])
        self.assertEqual(self.store.get_owner_overflow_sweep(sweep["sweep_id"])["status"],
                         "settled")

    def test_suspense_cannot_be_attributed_while_over_cap(self):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 400_000_000,
            attribution_ref="invoice:400",
        )
        self.store.record_receipt(self.receipt("3", 3, 400_000_000), period_id="2026-11")
        self.store.record_receipt(self.receipt("4", 4, 200_000_000), period_id="2026-11")
        with self.assertRaisesRegex(ValueError, "above its cap"):
            self.store.attribute_receipt(
                "base-sepolia", "USDC", "0x" + "3" * 64, "log:3",
                "agent-a", expected_attribution_ref="invoice:400",
            )

    def test_worker_does_not_retry_uncertain_submission(self):
        class Signer:
            async def transfer_usdc(self, **kwargs):
                return "0x" + "5" * 64

        class Verifier:
            async def verify_transfer(self, **kwargs):
                return VerifiedTransfer(
                    kwargs["network"], kwargs["asset"], kwargs["tx_hash"], "log:5",
                    kwargs["destination_address"], kwargs["amount_minor"], 12, True,
                    source=kwargs["source_address"],
                )

        self.store.record_receipt(self.receipt("6", 6, 600_000_000), period_id="2026-11")
        self.store.configure_owner_payout_address(
            "base-sepolia", "USDC", OWNER,
            owner_principal_id="authenticated-owner-1", reason="owner destination",
        )
        worker = OwnerOverflowSweepWorker(self.store, Signer(), Verifier())
        result = asyncio.run(worker.run_once(
            network="base-sepolia", asset="USDC", period_id="2026-11",
            idempotency_key="worker-overflow-1",
        ))
        self.assertEqual(result["status"], "settled")
        self.assertEqual(result["accounting_reason"], "owner_overflow_sweep")
        replay = asyncio.run(worker.run_once(
            network="base-sepolia", asset="USDC", period_id="2026-11",
            idempotency_key="worker-overflow-1",
        ))
        self.assertEqual(replay["status"], "settled")


    def test_owner_profit_share_is_a_separate_verified_real_payout(self):
        from economy.owner_overflow_sweep import OwnerProfitPayoutWorker

        self.store.configure_owner_payout_address(
            "base-sepolia", "USDC", OWNER,
            owner_principal_id="authenticated-owner-1",
            reason="owner-controlled profit destination",
        )
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 100_000_000,
            attribution_ref="invoice:profit",
        )
        self.store.record_receipt(
            self.receipt("7", 7, 100_000_000), period_id="2026-11",
            agent_id="agent-a", attribution_ref="invoice:profit",
        )
        close = self.store.close_period(
            "agent-a", "base-sepolia", "USDC", "2026-11",
            reserve_bps=0,
        )
        self.assertEqual(close["owner_share_minor"], 50_000_000)

        class Signer:
            async def transfer_usdc(self, **kwargs):
                return "0x" + "8" * 64

        class Verifier:
            async def verify_transfer(self, **kwargs):
                return VerifiedTransfer(
                    kwargs["network"], kwargs["asset"], kwargs["tx_hash"], "log:8",
                    kwargs["destination_address"], kwargs["amount_minor"], 12, True,
                    source=kwargs["source_address"],
                )

        worker = OwnerProfitPayoutWorker(self.store, Signer(), Verifier())
        result = asyncio.run(worker.run_once(
            agent_id="agent-a", network="base-sepolia", asset="USDC",
            period_id="2026-11", idempotency_key="owner-profit:agent-a:2026-11",
        ))
        self.assertEqual(result["status"], "settled")
        self.assertEqual(result["amount_minor"], 50_000_000)
        self.assertEqual(result["accounting_reason"], "owner_net_profit_share")
        self.assertEqual(self.store.balance("master:owner", "base-sepolia", "USDC"), 0)
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 50_000_000)
        self.assertTrue(self.store.reconciliation_snapshot(
            "base-sepolia", "USDC"
        )["balanced"])


if __name__ == "__main__":
    unittest.main()
