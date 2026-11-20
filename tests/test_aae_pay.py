import tempfile
import unittest
from pathlib import Path

from economy.aae_pay import AaePay, AaePayError
from economy.financial_ledger import DoubleEntryLedger, IdempotencyConflict


class AaePaySimulationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ledger = DoubleEntryLedger(root / "journal.sqlite3")
        self.pay = AaePay(root / "aae-pay.sqlite3", self.ledger)

    def tearDown(self):
        self.tmp.cleanup()

    def invoice(self, *, key="invoice-1", gross=1000, fee=100):
        return self.pay.create_invoice(
            idempotency_key=key, agent_id="agent-a", currency="USD",
            gross_minor=gross, fee_minor=fee,
        )

    def settle(self, invoice):
        self.pay.record_simulated_observation(
            invoice_id=invoice["invoice_id"], observation_id="obs-1",
            gross_minor=invoice["gross_minor"], currency=invoice["currency"],
        )
        self.pay.verify_simulated_settlement(invoice["invoice_id"])
        return self.pay.reconcile(invoice["invoice_id"])

    def test_invoice_creation_is_idempotent_and_terms_are_immutable(self):
        first = self.invoice()
        retry = self.invoice()
        self.assertEqual(first["invoice_id"], retry["invoice_id"])
        with self.assertRaises(IdempotencyConflict):
            self.invoice(gross=1200)

    def test_observation_must_match_invoice_and_cannot_be_reused(self):
        invoice = self.invoice()
        with self.assertRaisesRegex(AaePayError, "does not match"):
            self.pay.record_simulated_observation(
                invoice_id=invoice["invoice_id"], observation_id="obs-bad",
                gross_minor=999, currency="USD",
            )
        self.pay.record_simulated_observation(
            invoice_id=invoice["invoice_id"], observation_id="obs-1",
            gross_minor=1000, currency="USD",
        )
        other = self.invoice(key="invoice-2")
        with self.assertRaisesRegex(AaePayError, "already been used"):
            self.pay.record_simulated_observation(
                invoice_id=other["invoice_id"], observation_id="obs-1",
                gross_minor=1000, currency="USD",
            )

    def test_unobserved_invoice_cannot_be_verified_or_reconciled(self):
        invoice = self.invoice()
        with self.assertRaisesRegex(AaePayError, "observed simulated"):
            self.pay.verify_simulated_settlement(invoice["invoice_id"])
        with self.assertRaisesRegex(AaePayError, "verified simulated"):
            self.pay.reconcile(invoice["invoice_id"])

    def test_reconciliation_posts_balanced_simulated_entries_once(self):
        invoice = self.invoice()
        settled = self.settle(invoice)
        self.assertEqual(settled["status"], "reconciled")
        journal = self.ledger.transaction(settled["journal_transaction_id"])
        self.assertTrue(journal["simulated"])
        self.assertEqual(sum(
            line["amount_minor"] if line["direction"] == "debit"
            else -line["amount_minor"] for line in journal["lines"]
        ), 0)
        self.assertEqual(self.ledger.balance_minor("treasury:simulated-clearing"), 1000)
        self.assertEqual(self.ledger.balance_minor("platform-fees:simulated"), -100)
        self.assertEqual(self.ledger.balance_minor("agent-payable:simulated:agent-a"), -900)
        self.assertEqual(self.pay.reconcile(invoice["invoice_id"])["journal_transaction_id"],
                         settled["journal_transaction_id"])

    def test_zero_fee_reconciliation_omits_zero_value_journal_line(self):
        invoice = self.invoice(key="zero-fee", fee=0)
        settled = self.settle(invoice)
        journal = self.ledger.transaction(settled["journal_transaction_id"])
        self.assertEqual(len(journal["lines"]), 2)
        self.assertEqual(self.ledger.balance_minor("agent-payable:simulated:agent-a"), -1000)

    def test_delivery_requires_reconciliation_and_is_idempotent(self):
        invoice = self.invoice()
        with self.assertRaisesRegex(AaePayError, "requires reconciled"):
            self.pay.mark_delivered(invoice["invoice_id"])
        settled = self.settle(invoice)
        delivered = self.pay.mark_delivered(invoice["invoice_id"])
        self.assertEqual(delivered["status"], "delivered")
        self.assertEqual(self.pay.mark_delivered(invoice["invoice_id"])["status"], "delivered")

    def test_reversal_is_append_only_and_idempotent(self):
        invoice = self.invoice()
        settled = self.settle(invoice)
        reversed_invoice = self.pay.reverse(invoice["invoice_id"], reason="test correction")
        self.assertEqual(reversed_invoice["status"], "reversed")
        self.assertNotEqual(reversed_invoice["reversal_transaction_id"],
                            settled["journal_transaction_id"])
        reversal = self.ledger.transaction(reversed_invoice["reversal_transaction_id"])
        self.assertTrue(reversal["simulated"])
        self.assertEqual(sum(
            line["amount_minor"] if line["direction"] == "debit"
            else -line["amount_minor"] for line in reversal["lines"]
        ), 0)
        self.assertEqual(self.ledger.balance_minor("treasury:simulated-clearing"), 0)
        self.assertEqual(self.ledger.balance_minor("platform-fees:simulated"), 0)
        self.assertEqual(self.ledger.balance_minor("agent-payable:simulated:agent-a"), 0)
        self.assertEqual(self.pay.reverse(invoice["invoice_id"], reason="retry")["status"],
                         "reversed")

    def test_invalid_amounts_currency_and_list_limit_are_rejected(self):
        for amount in (True, 0, -1, 1.25, 9_223_372_036_854_775_808):
            with self.subTest(amount=amount), self.assertRaises(AaePayError):
                self.invoice(key=f"bad-{amount!r}", gross=amount, fee=0)
        with self.assertRaises(AaePayError):
            self.pay.create_invoice(
                idempotency_key="bad-currency", agent_id="agent-a",
                currency="US€", gross_minor=100, fee_minor=0,
            )
        with self.assertRaises(AaePayError):
            self.pay.list_invoices(limit=0)


if __name__ == "__main__":
    unittest.main()
