import asyncio
import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import VerifiedTransfer
from economy.collective_treasury import CollectiveTreasuryStore, TreasuryWallet
from economy.collective_owner_profit_worker import CollectiveOwnerProfitPayoutWorker


TREASURY = "0x" + "a" * 40
OWNER = "0x" + "b" * 40
PAYER = "0x" + "c" * 40


class FakeSigner:
    def __init__(self):
        self.calls = []

    async def transfer_usdc(self, *, destination, amount_minor, network="base-sepolia"):
        self.calls.append((destination, amount_minor, network))
        return "0x" + str(len(self.calls)) * 64


class FakeVerifier:
    def __init__(self, verified=True):
        self.verified = verified
        self.calls = []

    async def verify_transfer(self, *, network, asset, tx_hash, source_address,
                              destination_address, amount_minor):
        self.calls.append(tx_hash)
        return VerifiedTransfer(
            network, asset, tx_hash, "log:owner:" + tx_hash[-1],
            destination_address, amount_minor, 12, self.verified,
            source=source_address,
        )


class CollectiveOwnerProfitPayoutWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CollectiveTreasuryStore(
            Path(self.tmp.name) / "treasury.sqlite3",
            owner_principal_id="owner-principal",
        )
        self.store.register_treasury_wallet(TreasuryWallet(
            "coinbase-cdp", "shared-wallet", "base-sepolia", "USDC", TREASURY,
        ))
        self.store.add_agent(
            "agent-a", "base-sepolia", "USDC", daily_limit_minor=100_000,
            per_tx_limit_minor=50_000, allowed_destinations=(OWNER,),
        )
        self.store.configure_owner_payout_address(
            "base-sepolia", "USDC", OWNER,
            owner_principal_id="owner-principal", reason="test owner destination",
        )
        self._create_period("2026-11", 8000, "invoice:nov", "0x" + "1" * 64, "log:1")
        self.signer = FakeSigner()
        self.verifier = FakeVerifier()
        self.worker = CollectiveOwnerProfitPayoutWorker(
            self.store, self.signer, self.verifier,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _create_period(self, period, amount, attribution, tx_hash, transfer_ref):
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", amount,
            attribution_ref=attribution,
        )
        self.store.record_receipt(
            VerifiedTransfer(
                "base-sepolia", "USDC", tx_hash, transfer_ref, TREASURY,
                amount, 12, True, source=PAYER,
            ),
            period_id=period, agent_id="agent-a", attribution_ref=attribution,
        )
        return self.store.close_period(
            "agent-a", "base-sepolia", "USDC", period,
            reserve_bps=0, owner_share_bps=5000,
        )

    def test_pays_exact_50_percent_share_from_shared_wallet_once(self):
        result = asyncio.run(self.worker.run_once(network="base-sepolia"))
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["settled"], 1)
        self.assertEqual(self.signer.calls, [(OWNER, 4000, "base-sepolia")])
        self.assertEqual(self.store.balance("master:owner", "base-sepolia", "USDC"), 0)
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 4000)
        self.assertEqual(
            self.store.list_unsettled_owner_profit_closes("base-sepolia", "USDC"),
            [],
        )
        again = asyncio.run(self.worker.run_once(network="base-sepolia"))
        self.assertEqual(again["status"], "completed")
        self.assertEqual(self.signer.calls, [(OWNER, 4000, "base-sepolia")])

    def test_unverified_payout_stays_uncertain_and_retry_only_reconciles(self):
        self.verifier.verified = False
        first = asyncio.run(self.worker.run_once(network="base-sepolia"))
        self.assertEqual(first["status"], "pending")
        self.assertEqual(first["uncertain"], 1)
        self.assertEqual(len(self.signer.calls), 1)
        self.verifier.verified = True
        second = asyncio.run(self.worker.run_once(network="base-sepolia"))
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["settled"], 1)
        self.assertEqual(len(self.signer.calls), 1)
        self.assertEqual(len(self.verifier.calls), 2)

    def test_ambiguous_signer_timeout_is_not_rebroadcast_without_hash_reconciliation(self):
        class AmbiguousSigner:
            def __init__(self):
                self.calls = 0
            async def transfer_usdc(self, **kwargs):
                self.calls += 1
                raise TimeoutError("provider timed out after possible broadcast")

        signer = AmbiguousSigner()
        worker = CollectiveOwnerProfitPayoutWorker(self.store, signer, self.verifier)
        first = asyncio.run(worker.run_once(network="base-sepolia"))
        second = asyncio.run(worker.run_once(network="base-sepolia"))
        self.assertEqual(first["status"], "pending")
        self.assertEqual(second["status"], "pending")
        self.assertEqual(signer.calls, 1)
        self.assertEqual(self.verifier.calls, [])

    def test_callback_does_not_report_success_while_more_periods_remain(self):
        self._create_period(
            "2026-12", 2000, "invoice:dec", "0x" + "2" * 64, "log:2",
        )
        callback = self.worker.runtime_callback(
            network="base-sepolia", limit=1,
        )
        result = asyncio.run(callback())
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["settled"], 1)
        self.assertEqual(result["pending"], 1)
        self.assertTrue(result["backlog"])

    def test_missing_owner_destination_fails_closed(self):
        self.store = CollectiveTreasuryStore(
            Path(self.tmp.name) / "without-owner-destination.sqlite3",
            owner_principal_id="owner-principal",
        )
        self.store.register_treasury_wallet(TreasuryWallet(
            "coinbase-cdp", "shared-wallet-2", "base-sepolia", "USDC", "0x" + "d" * 40,
        ))
        self.store.add_agent(
            "agent-a", "base-sepolia", "USDC", daily_limit_minor=100_000,
            per_tx_limit_minor=50_000, allowed_destinations=(OWNER,),
        )
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 1000, attribution_ref="invoice:no-owner",
        )
        self.store.record_receipt(
            VerifiedTransfer(
                "base-sepolia", "USDC", "0x" + "3" * 64, "log:3", "0x" + "d" * 40,
                1000, 12, True, source=PAYER,
            ),
            period_id="2026-11", agent_id="agent-a",
            attribution_ref="invoice:no-owner",
        )
        self.store.close_period(
            "agent-a", "base-sepolia", "USDC", "2026-11",
            reserve_bps=0, owner_share_bps=5000,
        )
        worker = CollectiveOwnerProfitPayoutWorker(
            self.store, self.signer, self.verifier,
        )
        result = asyncio.run(worker.run_once(network="base-sepolia"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"], 1)
        self.assertEqual(self.signer.calls, [])


if __name__ == "__main__":
    unittest.main()
