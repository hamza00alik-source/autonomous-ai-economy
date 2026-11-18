import json
import tempfile
import unittest
from pathlib import Path

from economy.basedagents_marketplace import PaidTaskLead
from economy.basedagents_opportunities import (
    BasedAgentsOpportunityScanner, PaidOpportunityStore,
)


class BasedAgentsOpportunityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = PaidOpportunityStore(Path(self.tmp.name) / "leads.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def lead(self, **overrides):
        data = dict(task_id="task-1", title="Research report",
                    description="Produce a sourced report", category="research",
                    bounty_usdc="5.00", network="eip155:8453",
                    status="open", claimable=True)
        data.update(overrides)
        return PaidTaskLead(**data)

    def test_supported_paid_task_requires_review(self):
        result = self.store.save(self.lead())
        self.assertEqual(result["fit_score"], 100)
        self.assertEqual(result["state"], "review_required")
        rows = self.store.list_review_required()
        self.assertEqual(rows[0]["external_task_id"], "task-1")
        self.assertFalse(rows[0]["payload"]["payment_verified"])

    def test_unpaid_unsupported_or_unclaimable_task_rejected(self):
        for lead in (
            self.lead(task_id="free", bounty_usdc=None),
            self.lead(task_id="wrong-category", category="other"),
            self.lead(task_id="wrong-network", network="eip155:1"),
            self.lead(task_id="not-claimable", claimable=False),
        ):
            self.assertEqual(self.store.save(lead)["state"], "rejected")

    def test_upsert_deduplicates_external_task(self):
        self.store.save(self.lead())
        self.store.save(self.lead(title="Updated title", bounty_usdc="7.00"))
        self.assertEqual(len(self.store.list_review_required()), 1)
        self.assertEqual(self.store.list_review_required()[0]["payload"]["title"], "Updated title")

    def test_scanner_is_read_only_and_reports_no_external_actions(self):
        lead = self.lead()
        class Provider:
            def search(self, *, limit):
                return [lead]
        result = BasedAgentsOpportunityScanner(self.store, Provider()).scan_once()
        self.assertEqual(result["fetched"], 1)
        self.assertEqual(result["review_required"], 1)
        self.assertEqual(result["external_claims"], 0)
        self.assertEqual(result["payments"], 0)

    def test_evaluations_are_persisted_and_upserted(self):
        evaluation = {
            "task_id": "task-1", "state": "qualified_for_local_draft",
            "score": 100, "claim_allowed": False,
        }
        self.store.save_evaluation(evaluation)
        self.store.save_evaluation({**evaluation, "score": 90})
        rows = self.store.list_evaluations()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["score"], 90)
        self.assertFalse(rows[0]["claim_allowed"])

    def test_evaluation_rejects_unsafe_state(self):
        with self.assertRaises(ValueError):
            self.store.save_evaluation({"task_id": "task-1", "state": "submitted"})

    def test_rejects_invalid_limits(self):
        with self.assertRaises(ValueError):
            self.store.list_review_required(0)


if __name__ == "__main__":
    unittest.main()
