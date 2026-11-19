import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import VerifiedTransfer
from economy.collective_treasury import CollectiveTreasuryStore, TreasuryWallet
from economy.owner_overflow_worker import OwnerOverflowSweepWorker


class FakeSigner:
    def __init__(self, tx_hash):
        self.tx_hash = tx_hash
        self.calls = 0

    async def transfer_usdc(self, *, destination, amount_minor, network):
        self.calls += 1
        return self.tx_hash


class FakeVerifier:
    def __init__(self, transfer=None, error=None):
        self.transfer = transfer
        self.error = error
        self.calls = 0

    async def verify_transfer(self, **kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.transfer


class OwnerOverflowWorkerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CollectiveTreasuryStore(
            Path(self.tmp.name) / "treasury.sqlite3",
            owner_principal_id="owner-1",
        )
        self.wallet_address = "0x" + "a" * 40
        self.owner_address = "0x" + "e" * 40
        self.store.register_treasury_wallet(TreasuryWallet(
            "coinbase-cdp", "cdp-owner", "base-sepolia", "USDC",
            self.wallet_address,
        ))
        self.store.configure_owner_payout_address(
            "base-sepolia", "USDC", self.owner_address,
            owner_principal_id="owner-1", reason="test owner destination",
        )
        incoming = VerifiedTransfer(
            "base-sepolia", "USDC", "0x" + "1" * 64, "log:incoming",
            self.wallet_address, 600_000_000, 12, True,
            source="0x" + "d" * 40,
        )
        self.store.record_receipt(incoming, period_id="2026-11")

    def tearDown(self):
        self.tmp.cleanup()

    def reserve(self):
        return self.store.reserve_owner_overflow_sweep(
            "base-sepolia", "USDC", period_id="2026-11",
            idempotency_key="overflow:test",
        )

    async def test_worker_broadcasts_and_settles_only_exact_verified_sweep(self):
        sweep = self.reserve()
        tx_hash = "0x" + "9" * 64
        signer = FakeSigner(tx_hash)
        transfer = VerifiedTransfer(
            "base-sepolia", "USDC", tx_hash, "log:outgoing",
            self.owner_address, 100_000_000, 15, True,
            source=self.wallet_address,
        )
        verifier = FakeVerifier(transfer=transfer)
        worker = OwnerOverflowSweepWorker(self.store, signer, verifier)
        result = await worker.execute(sweep["sweep_id"])
        self.assertEqual(result["status"], "settled")
        self.assertEqual(signer.calls, 1)
        self.assertEqual(verifier.calls, 1)
        self.assertEqual(self.store.pool_balance("base-sepolia", "USDC"), 500_000_000)

    async def test_run_cycle_creates_and_processes_overflow_reservation(self):
        tx_hash = "0x" + "7" * 64
        transfer = VerifiedTransfer(
            "base-sepolia", "USDC", tx_hash, "log:cycle",
            self.owner_address, 100_000_000, 16, True,
            source=self.wallet_address,
        )
        signer = FakeSigner(tx_hash)
        worker = OwnerOverflowSweepWorker(
            self.store, signer, FakeVerifier(transfer=transfer),
        )
        result = await worker.run_cycle(
            network="base-sepolia", asset="USDC", period_id="2026-11",
        )
        self.assertEqual(result["status"], "settled")
        self.assertEqual(result["remaining_excess_minor"], 0)
        self.assertEqual(signer.calls, 1)

    async def test_unverified_transfer_stays_uncertain_and_is_never_rebroadcast(self):
        sweep = self.reserve()
        tx_hash = "0x" + "8" * 64
        signer = FakeSigner(tx_hash)
        verifier = FakeVerifier(error=RuntimeError("not finalized"))
        worker = OwnerOverflowSweepWorker(self.store, signer, verifier)
        result = await worker.execute(sweep["sweep_id"])
        self.assertEqual(result["status"], "uncertain")
        self.assertEqual(signer.calls, 1)
        with self.assertRaisesRegex(ValueError, "only a fresh reserved"):
            await worker.execute(sweep["sweep_id"])
        self.assertEqual(signer.calls, 1)
        verified = VerifiedTransfer(
            "base-sepolia", "USDC", tx_hash, "log:outgoing",
            self.owner_address, 100_000_000, 15, True,
            source=self.wallet_address,
        )
        worker.verifier = FakeVerifier(transfer=verified)
        recovered = await worker.reconcile(sweep["sweep_id"])
        self.assertEqual(recovered["status"], "settled")
        self.assertEqual(signer.calls, 1)


    async def test_runtime_callback_supplies_fresh_period_id_each_cycle(self):
        tx_hash = "0x" + "6" * 64
        transfer = VerifiedTransfer(
            "base-sepolia", "USDC", tx_hash, "log:callback",
            self.owner_address, 100_000_000, 17, True,
            source=self.wallet_address,
        )
        signer = FakeSigner(tx_hash)
        worker = OwnerOverflowSweepWorker(
            self.store, signer, FakeVerifier(transfer=transfer),
        )
        periods = iter(["2026-11", "2026-12"])
        callback = worker.runtime_callback(
            network="base-sepolia", period_id_provider=lambda: next(periods),
        )
        first = await callback()
        self.assertEqual(first["status"], "settled")
        self.assertEqual(signer.calls, 1)
        self.assertEqual(self.store.get_owner_overflow_sweep(
            "missing-sweep"
        ), None)


if __name__ == "__main__":
    unittest.main()
