import base64
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from economy.financial_ledger import DoubleEntryLedger
from economy.allocation import AllocationPolicy, AllocationShare, allocate_reconciled_receipt
from economy.financial_policy import FinancialPolicyStore, _canonical
from economy.financial_spending import AgentSpending
from economy.expense_scheduler import AgentExpenseScheduler, ExpenseScheduleError


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


class ExpenseSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ledger = DoubleEntryLedger(root / "ledger.sqlite3")
        self.key = Ed25519PrivateKey.generate()
        public = b64(self.key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw))
        self.registry = Registry(public)
        self.policies = FinancialPolicyStore(self.registry, root / "policies.sqlite3")
        payload = self.policies.payload(
            policy_id="ops", version=1, owner_id="owner", agent_id="agent",
            currency="USD", per_transaction_limit_minor=300,
            daily_spend_limit_minor=600, allowed_destinations=["service:compute"])
        self.policies.save(payload, b64(self.key.sign(_canonical(payload))))
        self.ledger.post(
            idempotency_key="initial-agent-budget", description="Simulated initial budget",
            currency="USD", lines=[
                {"account_id": "agent-budget:agent", "direction": "debit",
                 "amount_minor": 1000, "reference": "allocation"},
                {"account_id": "external-clearing", "direction": "credit",
                 "amount_minor": 1000, "reference": "allocation"},
            ])
        self.spending = AgentSpending(self.ledger, self.policies, root / "spending.sqlite3")
        self.scheduler = AgentExpenseScheduler(self.spending, root / "schedules.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, **changes):
        args = {"agent_id": "agent", "policy_id": "ops", "destination": "service:compute",
                "currency": "USD", "amount_minor": 200, "interval_seconds": 3600,
                "idempotency_key": "schedule-1",
                "start_at": datetime.now(timezone.utc) - timedelta(seconds=10)}
        args.update(changes)
        return self.scheduler.create(**args)

    def test_due_schedule_settles_once_and_advances(self):
        schedule = self.create()
        now = datetime.now(timezone.utc)
        first = self.scheduler.run_due(now=now)
        self.assertEqual(first, {"settled": 1, "blocked": 0})
        balance = self.ledger.balance_minor("agent-budget:agent")
        second = self.scheduler.run_due(now=now)
        self.assertEqual(second, {"settled": 0, "blocked": 0})
        self.assertEqual(self.ledger.balance_minor("agent-budget:agent"), balance)
        updated = self.scheduler.get(schedule["schedule_id"])
        self.assertGreater(datetime.fromisoformat(updated["next_run_at"]), now)

    def test_schedule_retries_blocked_due_occurrence_after_budget_replenishment(self):
        self.ledger.post(
            idempotency_key="deplete-budget", description="Simulated budget depletion",
            currency="USD", lines=[
                {"account_id": "operating-expense:bootstrap", "direction": "debit",
                 "amount_minor": 900, "reference": "bootstrap"},
                {"account_id": "agent-budget:agent", "direction": "credit",
                 "amount_minor": 900, "reference": "bootstrap"},
            ])
        schedule = self.create()
        now = datetime.now(timezone.utc)
        self.assertEqual(self.scheduler.run_due(now=now), {"settled": 0, "blocked": 1})
        self.ledger.record_simulated_receipt(
            source_reference="earned-revenue-1", agent_id="agent", currency="USD",
            expected_gross_minor=600, expected_fee_minor=100)
        self.ledger.confirm_simulated_receipt(
            source_reference="earned-revenue-1", received_gross_minor=600,
            received_fee_minor=100)
        self.ledger.reconcile_simulated_receipt(source_reference="earned-revenue-1")
        allocation_policy = AllocationPolicy(
            policy_id="agent-budget", version=1,
            shares=(AllocationShare("agent-budget:{agent_id}", 10_000),))
        allocate_reconciled_receipt(
            self.ledger, agent_id="agent", net_amount_minor=500, currency="USD",
            source_reference="earned-revenue-1", policy=allocation_policy)
        self.assertEqual(self.scheduler.run_due(now=now), {"settled": 1, "blocked": 0})

    def test_daily_limit_blocks_repeated_occurrence_without_skipping_due(self):
        schedule = self.create(amount_minor=300)
        now = datetime.now(timezone.utc)
        self.assertEqual(self.scheduler.run_due(now=now), {"settled": 1, "blocked": 0})
        # Move next occurrence due; second transaction would exceed daily cap.
        with __import__("sqlite3").connect(self.scheduler.path) as db:
            db.execute("UPDATE agent_expense_schedules SET next_run_at=? WHERE schedule_id=?",
                       ((now - timedelta(seconds=2)).isoformat(), schedule["schedule_id"]))
        # The second occurrence reaches exactly the daily cap; the third must block.
        self.assertEqual(self.scheduler.run_due(now=now), {"settled": 1, "blocked": 0})
        with __import__("sqlite3").connect(self.scheduler.path) as db:
            db.execute("UPDATE agent_expense_schedules SET next_run_at=? WHERE schedule_id=?",
                       ((now - timedelta(seconds=3)).isoformat(), schedule["schedule_id"]))
        self.assertEqual(self.scheduler.run_due(now=now), {"settled": 0, "blocked": 1})
        self.assertEqual(datetime.fromisoformat(self.scheduler.get(schedule["schedule_id"])["next_run_at"]), now - timedelta(seconds=3))

    def test_pause_resume_cancel_controls(self):
        schedule = self.create()
        self.scheduler.pause(schedule["schedule_id"])
        self.assertEqual(self.scheduler.run_due(now=datetime.now(timezone.utc)), {"settled": 0, "blocked": 0})
        self.scheduler.resume(schedule["schedule_id"])
        self.scheduler.cancel(schedule["schedule_id"])
        with self.assertRaisesRegex(ExpenseScheduleError, "cannot be reactivated"):
            self.scheduler.resume(schedule["schedule_id"])

    def test_schedule_requires_exact_policy_authorization(self):
        with self.assertRaisesRegex(ExpenseScheduleError, "not authorized"):
            self.create(destination="service:other")
        with self.assertRaisesRegex(ExpenseScheduleError, "per-transaction"):
            self.create(amount_minor=301)
        with self.assertRaisesRegex(ExpenseScheduleError, "1 hour"):
            self.create(interval_seconds=60)

    def test_idempotency_key_rejects_changed_schedule_terms(self):
        self.create()
        with self.assertRaisesRegex(ExpenseScheduleError, "changed terms"):
            self.create(amount_minor=201)

    def test_immediate_schedule_creation_is_idempotent_without_explicit_start(self):
        args = {"agent_id": "agent", "policy_id": "ops", "destination": "service:compute",
                "currency": "USD", "amount_minor": 100, "interval_seconds": 3600,
                "idempotency_key": "immediate-schedule"}
        first = self.scheduler.create(**args)
        retry = self.scheduler.create(**args)
        self.assertEqual(first["schedule_id"], retry["schedule_id"])

    def test_policy_supersession_blocks_existing_recurring_schedule(self):
        schedule = self.create()
        payload = self.policies.payload(
            policy_id="ops", version=2, owner_id="owner", agent_id="agent",
            currency="USD", per_transaction_limit_minor=300,
            daily_spend_limit_minor=600, allowed_destinations=["service:compute"])
        self.policies.save(payload, b64(self.key.sign(_canonical(payload))))
        now = datetime.now(timezone.utc)
        self.assertEqual(self.scheduler.run_due(now=now), {"settled": 0, "blocked": 1})
        self.assertEqual(datetime.fromisoformat(self.scheduler.get(schedule["schedule_id"])["next_run_at"]),
                         datetime.fromisoformat(schedule["next_run_at"]))

    def test_timezone_is_required(self):
        with self.assertRaisesRegex(ExpenseScheduleError, "timezone"):
            self.create(start_at=datetime(2026, 1, 1))


if __name__ == "__main__":
    unittest.main()
