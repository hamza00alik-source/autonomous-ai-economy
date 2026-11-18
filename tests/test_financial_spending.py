import base64
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from economy.financial_ledger import DoubleEntryLedger
from economy.financial_policy import FinancialPolicyStore, _canonical
from economy.financial_spending import AgentSpending, FinancialSpendingError


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class Registry:
    def __init__(self, public_key):
        self.records = {
            "owner": {"participant_id": "owner", "participant_type": "human",
                      "status": "active", "public_key": public_key},
            "agent": {"participant_id": "agent", "participant_type": "agent",
                      "status": "active", "public_key": "agent-key", "operator_id": "owner"},
        }

    def get(self, participant_id):
        return self.records.get(participant_id)


class AgentSpendingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ledger = DoubleEntryLedger(root / "ledger.sqlite3")
        self.key = Ed25519PrivateKey.generate()
        public = b64(self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw))
        self.registry = Registry(public)
        self.policies = FinancialPolicyStore(self.registry, root / "policies.sqlite3")
        self.payload = self.policies.payload(
            policy_id="ops", version=1, owner_id="owner", agent_id="agent",
            currency="USD", per_transaction_limit_minor=500,
            daily_spend_limit_minor=800,
            allowed_destinations=["service:compute", "service:storage"],
        )
        signature = b64(self.key.sign(_canonical(self.payload)))
        self.policies.save(self.payload, signature)
        self.ledger.post(
            idempotency_key="fund-agent-budget", description="Simulated budget funding",
            currency="USD", lines=[
                {"account_id": "agent-budget:agent", "direction": "debit",
                 "amount_minor": 1000, "reference": "allocation"},
                {"account_id": "treasury:available", "direction": "credit",
                 "amount_minor": 1000, "reference": "allocation"},
            ])
        self.spending = AgentSpending(self.ledger, self.policies, root / "spending.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def reserve(self, **changes):
        args = {"agent_id": "agent", "policy_id": "ops",
                "destination": "service:compute", "currency": "USD",
                "amount_minor": 300, "idempotency_key": "expense-1"}
        args.update(changes)
        return self.spending.reserve(**args)

    def test_reservation_is_durable_and_does_not_spend_until_settlement(self):
        reservation = self.reserve()
        self.assertEqual(reservation["status"], "reserved")
        self.assertEqual(self.ledger.balance_minor("agent-budget:agent"), 1000)
        self.assertEqual(self.spending.reserve(
            agent_id="agent", policy_id="ops", destination="service:compute",
            currency="USD", amount_minor=300, idempotency_key="expense-1")["reservation_id"],
            reservation["reservation_id"])

    def test_idempotency_key_rejects_changed_terms(self):
        self.reserve()
        with self.assertRaisesRegex(FinancialSpendingError, "changed"):
            self.reserve(amount_minor=301)

    def test_allowlist_currency_and_per_transaction_limit_are_enforced(self):
        for changes, message in [
            ({"destination": "service:unknown"}, "allowlisted"),
            ({"currency": "EUR"}, "currency"),
            ({"amount_minor": 501}, "per-transaction"),
        ]:
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(FinancialSpendingError, message):
                    self.reserve(**changes)

    def test_reservations_prevent_overspending_and_daily_limit_exhaustion(self):
        self.reserve()
        self.reserve(amount_minor=500, idempotency_key="expense-2")
        with self.assertRaisesRegex(FinancialSpendingError, "unreserved"):
            self.reserve(amount_minor=300, idempotency_key="expense-3")
        with self.assertRaisesRegex(FinancialSpendingError, "daily"):
            self.reserve(amount_minor=1, idempotency_key="expense-4")

    def test_settlement_posts_expense_once_and_reduces_budget(self):
        reservation = self.reserve()
        settled = self.spending.settle(reservation["reservation_id"])
        self.assertEqual(settled["status"], "settled")
        self.assertEqual(self.ledger.balance_minor("agent-budget:agent"), 700)
        self.assertEqual(self.ledger.balance_minor("operating-expense:service:compute"), 300)
        retry = self.spending.settle(reservation["reservation_id"])
        self.assertEqual(retry["journal_transaction_id"], settled["journal_transaction_id"])
        self.assertEqual(self.ledger.balance_minor("agent-budget:agent"), 700)

    def test_release_restores_reservable_capacity_without_spending(self):
        reservation = self.reserve()
        self.spending.release(reservation["reservation_id"])
        self.assertEqual(self.ledger.balance_minor("agent-budget:agent"), 1000)
        next_reservation = self.reserve(amount_minor=500, idempotency_key="expense-2")
        self.assertEqual(next_reservation["status"], "reserved")

    def test_key_rotation_invalidates_policy_and_blocks_settlement(self):
        reservation = self.reserve()
        replacement = Ed25519PrivateKey.generate()
        self.registry.records["owner"]["public_key"] = b64(
            replacement.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw))
        with self.assertRaisesRegex(FinancialSpendingError, "authorized"):
            self.spending.settle(reservation["reservation_id"])

    def test_superseding_policy_blocks_old_reservation(self):
        reservation = self.reserve()
        payload = self.policies.payload(
            policy_id="ops", version=2, owner_id="owner", agent_id="agent",
            currency="USD", per_transaction_limit_minor=400,
            daily_spend_limit_minor=700, allowed_destinations=["service:compute"])
        self.policies.save(payload, b64(self.key.sign(_canonical(payload))))
        with self.assertRaisesRegex(FinancialSpendingError, "superseded"):
            self.spending.settle(reservation["reservation_id"])

    def test_suspended_agent_blocks_new_reservations(self):
        self.registry.records["agent"]["status"] = "suspended"
        with self.assertRaisesRegex(FinancialSpendingError, "authorized"):
            self.reserve()

    def test_live_money_is_not_an_option(self):
        with self.assertRaises(TypeError):
            self.spending.reserve(agent_id="agent", policy_id="ops",
                destination="service:compute", currency="USD", amount_minor=1,
                idempotency_key="live", simulated=False)


if __name__ == "__main__":
    unittest.main()
