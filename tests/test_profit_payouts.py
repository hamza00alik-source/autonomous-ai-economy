import tempfile
import unittest
from pathlib import Path

from economy.agent_finance import AgentFinanceStore, VerifiedTransfer, Wallet
from economy.profit_payouts import ProfitPayoutWorker


class FakeSigner:
    def __init__(self):
        self.calls = []

    def transfer(self, **kwargs):
        self.calls.append(kwargs)
        return "0xpayout"


class FakeVerifier:
    def __init__(self, *, verified=True, amount=500):
        self.verified = verified
        self.amount = amount

    def verify_transfer(self, *, network, asset, tx_hash, source_address,
                        destination_address, amount_minor):
        return VerifiedTransfer(
            network, asset, tx_hash, "0", destination_address, self.amount,
            12, self.verified, source=source_address,
        )


class ProfitPayoutWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = AgentFinanceStore(Path(self.tmp.name) / "finance.sqlite3")
        self.store.register_wallet(Wallet("agent", "agent", "base", "USDC", "0xAgent"))
        self.store.register_wallet(Wallet("master", "master", "base", "USDC", "0xMaster"))
        receipt = VerifiedTransfer("base", "USDC", "income", "0", "0xAgent",
                                   1000, 12, True, source="0xCustomer")
        self.store.record_receipt("agent", receipt, period_id="p1")
        self.store.close_profit_period(
            "agent", "master", network="base", asset="USDC", period_id="p1",
            reserve_bps=0, owner_share_bps=5000,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_worker_sends_exact_share_and_marks_paid(self):
        signer = FakeSigner()
        worker = ProfitPayoutWorker(self.store, signer, FakeVerifier())
        result = worker.process_pending()
        self.assertEqual(result[0]["status"], "paid")
        self.assertEqual(signer.calls[0]["amount_minor"], 500)
        self.assertEqual(signer.calls[0]["destination_address"], "0xMaster")
        self.assertEqual(signer.calls[0]["idempotency_key"], "master-profit:agent:base:USDC:p1")

    def test_failed_verification_keeps_distribution_pending(self):
        worker = ProfitPayoutWorker(self.store, FakeSigner(), FakeVerifier(verified=False))
        result = worker.process_pending()
        self.assertEqual(result[0]["status"], "pending")
        self.assertEqual(self.store.list_pending_distributions()[0]["status"], "pending_payout")

    def test_wrong_amount_keeps_distribution_pending(self):
        worker = ProfitPayoutWorker(self.store, FakeSigner(), FakeVerifier(amount=499))
        result = worker.process_pending()
        self.assertEqual(result[0]["status"], "pending")
        self.assertEqual(self.store.list_pending_distributions()[0]["status"], "pending_payout")


if __name__ == "__main__":
    unittest.main()
