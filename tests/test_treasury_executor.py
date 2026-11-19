import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import VerifiedTransfer
from economy.collective_treasury import CollectiveTreasuryStore, TreasuryWallet
from economy.treasury_executor import CollectiveTreasuryPaymentExecutor


class FakeSigner:
    def __init__(self, fail=False):
        self.calls = 0
        self.fail = fail
    async def transfer_usdc(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise TimeoutError("ambiguous provider timeout")
        return "0x" + "2" * 64


class FakeVerifier:
    def __init__(self, fail=False):
        self.fail = fail
    async def verify_transfer(self, *, network, asset, tx_hash, source_address,
                              destination_address, amount_minor):
        if self.fail:
            raise RuntimeError("not finalized yet")
        return VerifiedTransfer(network, asset, tx_hash, "log:0", destination_address,
                                amount_minor, 12, True, source=source_address)


class CollectiveTreasuryExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CollectiveTreasuryStore(Path(self.tmp.name) / "treasury.sqlite3")
        self.treasury_address = "0x" + "a" * 40
        self.destination = "0x" + "b" * 40
        self.store.register_treasury_wallet(TreasuryWallet(
            "coinbase-cdp", "wallet-1", "base-sepolia", "USDC", self.treasury_address
        ))
        self.store.add_agent("agent-x", "base-sepolia", "USDC",
                             daily_limit_minor=5000, per_tx_limit_minor=3000,
                             allowed_destinations=(self.destination,))
        self.store.record_receipt(VerifiedTransfer(
            "base-sepolia", "USDC", "0x" + "1" * 64, "log:1",
            self.treasury_address, 4000, 12, True, source="0x" + "c" * 40,
        ), period_id="p1", agent_id="agent-x", attribution_ref="invoice:p1")

    def tearDown(self):
        self.tmp.cleanup()

    def reservation(self, key="pay-1"):
        return self.store.reserve_spend(
            "agent-x", "base-sepolia", "USDC", self.destination, 1000,
            idempotency_key=key, period_id="p1",
        )

    async def test_executes_from_one_treasury_and_settles_only_verified_transfer(self):
        reservation = self.reservation()
        signer = FakeSigner()
        executor = CollectiveTreasuryPaymentExecutor(self.store, signer, FakeVerifier())
        result = await executor.execute(reservation)
        self.assertEqual(result["status"], "settled")
        self.assertEqual(signer.calls, 1)
        self.assertEqual(self.store.balance("agent:agent-x", "base-sepolia", "USDC"), 3000)

    async def test_ambiguous_provider_failure_is_held_and_never_blindly_retried(self):
        reservation = self.reservation()
        signer = FakeSigner(fail=True)
        executor = CollectiveTreasuryPaymentExecutor(self.store, signer, FakeVerifier())
        result = await executor.execute(reservation)
        self.assertEqual(result["status"], "uncertain")
        with self.assertRaisesRegex(ValueError, "fresh reserved"):
            await executor.execute(reservation)
        self.assertEqual(signer.calls, 1)

    async def test_unfinalized_transfer_remains_uncertain(self):
        reservation = self.reservation()
        executor = CollectiveTreasuryPaymentExecutor(self.store, FakeSigner(), FakeVerifier(fail=True))
        result = await executor.execute(reservation)
        self.assertEqual(result["status"], "uncertain")
        db = self.store._connect()
        try:
            row = db.execute("SELECT status FROM treasury_spend_reservations WHERE reservation_id=?",
                             (reservation,)).fetchone()
        finally:
            db.close()
        self.assertEqual(row["status"], "uncertain")


if __name__ == "__main__":
    unittest.main()