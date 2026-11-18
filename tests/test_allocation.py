import tempfile
import unittest
from pathlib import Path

from economy.allocation import (
    AllocationPolicy,
    AllocationShare,
    allocate_reconciled_receipt,
)
from economy.financial_ledger import DoubleEntryLedger, FinancialLedgerError


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = DoubleEntryLedger(Path(self.tmp.name) / "journal.sqlite3")
        self.policy = AllocationPolicy(
            policy_id="pilot-policy",
            version=1,
            shares=(
                AllocationShare("agent-budget:{agent_id}", 5000),
                AllocationShare("treasury:reserve", 3000),
                AllocationShare("owner-distribution:payable", 2000),
            ),
        )
        self.ledger.post(
            idempotency_key="receipt-1",
            description="Simulated reconciled receipt",
            currency="USD",
            lines=[
                {"account_id": "treasury:available", "direction": "debit",
                 "amount_minor": 101, "reference": "receipt-1"},
                {"account_id": "revenue:clearing", "direction": "credit",
                 "amount_minor": 101, "reference": "receipt-1"},
            ],
        )

    def tearDown(self):
        self.tmp.cleanup()

    def allocate(self, **overrides):
        args = {
            "agent_id": "agent-a",
            "net_amount_minor": 101,
            "currency": "USD",
            "source_reference": "receipt-1",
            "settlement_state": "reconciled",
            "policy": self.policy,
        }
        args.update(overrides)
        return allocate_reconciled_receipt(self.ledger, **args)

    def test_exact_allocation_conserves_minor_units(self):
        transaction_id = self.allocate()
        self.assertEqual(self.ledger.balance_minor("treasury:available"), 0)
        self.assertEqual(self.ledger.balance_minor("agent-budget:agent-a"), 51)
        self.assertEqual(self.ledger.balance_minor("treasury:reserve"), 30)
        self.assertEqual(self.ledger.balance_minor("owner-distribution:payable"), 20)
        record = self.ledger.transaction(transaction_id)
        debits = sum(x["amount_minor"] for x in record["lines"] if x["direction"] == "debit")
        credits = sum(x["amount_minor"] for x in record["lines"] if x["direction"] == "credit")
        self.assertEqual(debits, credits)

    def test_pending_or_unreconciled_receipt_cannot_be_allocated(self):
        with self.assertRaisesRegex(FinancialLedgerError, "reconciled"):
            self.allocate(settlement_state="pending")

    def test_insufficient_treasury_balance_fails_closed(self):
        with self.assertRaisesRegex(FinancialLedgerError, "insufficient"):
            self.allocate(net_amount_minor=102)

    def test_repeated_allocation_is_idempotent(self):
        first = self.allocate()
        second = self.allocate()
        self.assertEqual(first, second)
        self.assertEqual(self.ledger.balance_minor("agent-budget:agent-a"), 51)

    def test_live_money_allocation_is_disabled(self):
        with self.assertRaisesRegex(FinancialLedgerError, "disabled"):
            self.allocate(simulated=False)

    def test_policy_must_conserve_100_percent(self):
        with self.assertRaisesRegex(ValueError, "10000"):
            AllocationPolicy(
                policy_id="bad", version=1,
                shares=(AllocationShare("agent", 9000),),
            )


if __name__ == "__main__":
    unittest.main()
