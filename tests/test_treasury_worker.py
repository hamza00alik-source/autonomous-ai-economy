import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import VerifiedTransfer
from economy.collective_treasury import CollectiveTreasuryStore, TreasuryWallet
from economy.treasury_executor import CollectiveTreasuryPaymentExecutor
from economy.treasury_worker import CollectiveTreasuryWorker


class Signer:
    def __init__(self):
        self.calls = 0

    async def transfer_usdc(self, **kwargs):
        self.calls += 1
        return "0x" + format(self.calls, "064x")


class Verifier:
    async def verify_transfer(self, *, network, asset, tx_hash, source_address,
                              destination_address, amount_minor):
        return VerifiedTransfer(
            network, asset, tx_hash, f"log:{self.calls if hasattr(self, 'calls') else 0}",
            destination_address, amount_minor, 12, True, source=source_address,
        )


class CollectiveTreasuryWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CollectiveTreasuryStore(Path(self.tmp.name) / "treasury.sqlite3")
        self.address = "0x" + "a" * 40
        self.destination = "0x" + "b" * 40
        self.store.register_treasury_wallet(TreasuryWallet(
            "coinbase-cdp", "wallet-1", "base-sepolia", "USDC", self.address
        ))
        self.store.add_agent(
            "agent-a", "base-sepolia", "USDC", daily_limit_minor=5000,
            per_tx_limit_minor=2000, allowed_destinations=(self.destination,),
        )
        self.store.create_payment_intent(
            "agent-a", "base-sepolia", "USDC", 4000, attribution_ref="worker-invoice"
        )
        self.store.record_receipt(VerifiedTransfer(
            "base-sepolia", "USDC", "0x" + "1" * 64, "log:1",
            self.address, 4000, 12, True, source="0x" + "c" * 40,
        ), period_id="p1", agent_id="agent-a", attribution_ref="worker-invoice")

    def tearDown(self):
        self.tmp.cleanup()

    def queue_spend(self, key):
        return self.store.reserve_spend(
            "agent-a", "base-sepolia", "USDC", self.destination, 1000,
            idempotency_key=key, period_id="p1",
        )

    async def test_one_shot_worker_processes_only_reserved_spends_with_limit(self):
        self.queue_spend("worker-1")
        self.queue_spend("worker-2")
        signer = Signer()
        executor = CollectiveTreasuryPaymentExecutor(self.store, signer, Verifier())
        worker = CollectiveTreasuryWorker(self.store, executor)

        first = await worker.run_once(limit=1)
        self.assertEqual(first["examined"], 1)
        self.assertEqual(first["settled"], 1)
        self.assertEqual(signer.calls, 1)

        second = await worker.run_once(limit=10)
        self.assertEqual(second["examined"], 1)
        self.assertEqual(second["settled"], 1)
        self.assertEqual(signer.calls, 2)

        third = await worker.run_once()
        self.assertEqual(third["examined"], 0)

    async def test_worker_rejects_unsafe_batch_limits(self):
        worker = CollectiveTreasuryWorker(
            self.store,
            CollectiveTreasuryPaymentExecutor(self.store, Signer(), Verifier()),
        )
        with self.assertRaisesRegex(ValueError, "between 1 and 500"):
            await worker.run_once(limit=0)


if __name__ == "__main__":
    unittest.main()
