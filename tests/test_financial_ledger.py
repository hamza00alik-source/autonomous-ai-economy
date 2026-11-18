import tempfile
import unittest
from pathlib import Path

from economy.financial_ledger import (
    DoubleEntryLedger,
    FinancialLedgerError,
    IdempotencyConflict,
)


class DoubleEntryLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = DoubleEntryLedger(Path(self.tmp.name) / "journal.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def posting(self, key="receipt-1", amount=1250):
        return self.ledger.post(
            idempotency_key=key,
            description="Simulated settled receipt allocation",
            currency="USD",
            lines=[
                {"account_id": "external-clearing", "direction": "debit",
                 "amount_minor": amount, "reference": "test-payment"},
                {"account_id": "agent-earned:agent-a", "direction": "credit",
                 "amount_minor": amount, "reference": "agent-a"},
            ],
        )

    def test_balanced_posting_is_atomic_and_visible_in_both_accounts(self):
        transaction_id = self.posting()
        self.assertEqual(self.ledger.balance_minor("external-clearing"), 1250)
        self.assertEqual(self.ledger.balance_minor("agent-earned:agent-a"), -1250)
        record = self.ledger.transaction(transaction_id)
        self.assertTrue(record["simulated"])
        self.assertEqual(len(record["lines"]), 2)

    def test_identical_idempotent_retry_returns_same_transaction(self):
        first = self.posting()
        retry = self.posting()
        self.assertEqual(first, retry)
        self.assertEqual(self.ledger.balance_minor("external-clearing"), 1250)

    def test_changed_terms_cannot_reuse_idempotency_key(self):
        self.posting()
        with self.assertRaises(IdempotencyConflict):
            self.posting(amount=1500)

    def test_unbalanced_posting_is_rejected(self):
        with self.assertRaisesRegex(FinancialLedgerError, "not balanced"):
            self.ledger.post(
                idempotency_key="bad-1", description="bad", currency="USD",
                lines=[
                    {"account_id": "cash", "direction": "debit", "amount_minor": 100},
                    {"account_id": "income", "direction": "credit", "amount_minor": 99},
                ],
            )

    def test_boolean_float_zero_and_negative_amounts_are_rejected(self):
        for amount in (True, 1.5, 0, -1):
            with self.subTest(amount=amount):
                with self.assertRaises(FinancialLedgerError):
                    self.ledger.post(
                        idempotency_key=f"bad-{amount!r}", description="bad",
                        currency="USD",
                        lines=[
                            {"account_id": "cash", "direction": "debit", "amount_minor": amount},
                            {"account_id": "income", "direction": "credit", "amount_minor": amount},
                        ],
                    )

    def test_real_money_posting_is_rejected(self):
        with self.assertRaisesRegex(FinancialLedgerError, "disabled"):
            self.ledger.post(
                idempotency_key="real-1", description="not allowed",
                currency="USD", simulated=False,
                lines=[
                    {"account_id": "cash", "direction": "debit", "amount_minor": 100},
                    {"account_id": "income", "direction": "credit", "amount_minor": 100},
                ],
            )

    def test_currency_accounts_are_separate(self):
        self.posting()
        self.assertEqual(self.ledger.balance_minor("external-clearing", "EUR"), 0)

    def test_missing_transaction_returns_none(self):
        self.assertIsNone(self.ledger.transaction("missing"))


if __name__ == "__main__":
    unittest.main()
