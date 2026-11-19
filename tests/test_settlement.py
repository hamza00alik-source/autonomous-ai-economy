import tempfile
import unittest
from pathlib import Path

from economy.financial_ledger import (
    DoubleEntryLedger,
    FinancialLedgerError,
    IdempotencyConflict,
)


class SimulatedSettlementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = DoubleEntryLedger(Path(self.tmp.name) / "journal.sqlite3")
        self.ledger.record_simulated_receipt(
            source_reference="provider-ref-1",
            agent_id="agent-a",
            currency="USD",
            expected_gross_minor=1050,
            expected_fee_minor=50,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_pending_receipt_is_not_spendable_or_reconcilable(self):
        receipt = self.ledger.simulated_receipt("provider-ref-1")
        self.assertEqual(receipt["status"], "pending")
        self.assertEqual(self.ledger.balance_minor("treasury:available"), 0)
        with self.assertRaisesRegex(FinancialLedgerError, "confirmed"):
            self.ledger.reconcile_simulated_receipt(source_reference="provider-ref-1")

    def test_mismatched_amount_or_fee_cannot_be_confirmed(self):
        with self.assertRaisesRegex(FinancialLedgerError, "does not match"):
            self.ledger.confirm_simulated_receipt(
                source_reference="provider-ref-1",
                received_gross_minor=1050,
                received_fee_minor=49,
            )
        self.assertEqual(self.ledger.simulated_receipt("provider-ref-1")["status"], "pending")

    def test_confirmed_receipt_reconciles_net_and_fee_once(self):
        self.ledger.confirm_simulated_receipt(
            source_reference="provider-ref-1",
            received_gross_minor=1050,
            received_fee_minor=50,
        )
        journal_id = self.ledger.reconcile_simulated_receipt(source_reference="provider-ref-1")
        self.assertEqual(self.ledger.balance_minor("treasury:available"), 1000)
        self.assertEqual(self.ledger.balance_minor("payment-fees:expense"), 50)
        self.assertEqual(self.ledger.balance_minor("external-clearing"), -1050)
        self.assertEqual(self.ledger.simulated_receipt("provider-ref-1")["status"], "reconciled")
        self.assertEqual(
            self.ledger.reconcile_simulated_receipt(source_reference="provider-ref-1"),
            journal_id,
        )
        self.assertEqual(self.ledger.balance_minor("treasury:available"), 1000)

    def test_duplicate_registration_is_idempotent_and_changed_terms_rejected(self):
        first = self.ledger.simulated_receipt("provider-ref-1")["settlement_id"]
        again = self.ledger.record_simulated_receipt(
            source_reference="provider-ref-1",
            agent_id="agent-a",
            currency="USD",
            expected_gross_minor=1050,
            expected_fee_minor=50,
        )
        self.assertEqual(first, again)
        with self.assertRaises(IdempotencyConflict):
            self.ledger.record_simulated_receipt(
                source_reference="provider-ref-1",
                agent_id="agent-b",
                currency="USD",
                expected_gross_minor=1050,
                expected_fee_minor=50,
            )

    def test_confirm_is_idempotent_after_confirmation(self):
        self.ledger.confirm_simulated_receipt(
            source_reference="provider-ref-1",
            received_gross_minor=1050,
            received_fee_minor=50,
        )
        self.ledger.confirm_simulated_receipt(
            source_reference="provider-ref-1",
            received_gross_minor=1050,
            received_fee_minor=50,
        )
        self.assertEqual(self.ledger.simulated_receipt("provider-ref-1")["status"], "confirmed")

    def test_invalid_gross_fee_and_zero_net_are_rejected(self):
        for gross, fee in ((0, 0), (100, 100), (100, -1), (True, 0), (2**63, 0)):
            with self.subTest(gross=gross, fee=fee):
                with self.assertRaises(FinancialLedgerError):
                    self.ledger.record_simulated_receipt(
                        source_reference=f"bad-{gross}-{fee}",
                        agent_id="agent-a", currency="USD",
                        expected_gross_minor=gross, expected_fee_minor=fee,
                    )


if __name__ == "__main__":
    unittest.main()
