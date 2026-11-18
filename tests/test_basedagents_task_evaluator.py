import json
import unittest

from economy.basedagents_marketplace import BasedAgentsPublicTasks
from economy.basedagents_task_evaluator import PaidTaskCapabilityEvaluator


class BasedAgentsTaskDetailTests(unittest.TestCase):
    def test_get_task_fetches_only_requested_task_and_unwraps(self):
        seen = []
        def fetch(url, timeout):
            seen.append(url)
            return json.dumps({"task": {
                "task_id": "task_123", "title": "Report", "status": "open",
            }}).encode()
        task = BasedAgentsPublicTasks(fetcher=fetch).get_task("task_123")
        self.assertEqual(task["title"], "Report")
        self.assertTrue(seen[0].endswith("/v1/tasks/task_123"))

    def test_get_task_rejects_path_injection(self):
        provider = BasedAgentsPublicTasks(fetcher=lambda *_: b"{}")
        with self.assertRaises(ValueError):
            provider.get_task("../agents")


class PaidTaskCapabilityEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.lead = {
            "task_id": "task_123", "title": "Research report",
            "description": "Produce a cited research report",
            "category": "research", "bounty_usdc": "5.00",
            "network": "eip155:8453", "status": "open", "claimable": True,
        }
        self.detail = {
            "task_id": "task_123", "title": "Research report", "status": "open",
            "description": "Produce a cited research report",
            "expected_output": "A 1,000-word report in Markdown",
            "acceptance_criteria": ["At least five primary sources", "Citations for factual claims"],
            "bounty": {"amount_display": "5.00", "network": "eip155:8453"},
        }
        self.evaluator = PaidTaskCapabilityEvaluator()

    def test_explicit_scope_can_be_qualified_for_local_draft_only(self):
        result = self.evaluator.evaluate(self.lead, self.detail)
        self.assertEqual(result.state, "qualified_for_local_draft")
        self.assertFalse(result.claim_allowed)
        self.assertEqual(len(result.acceptance_criteria), 2)

    def test_missing_acceptance_criteria_stays_in_review(self):
        detail = dict(self.detail, acceptance_criteria=[])
        result = self.evaluator.evaluate(self.lead, detail)
        self.assertEqual(result.state, "needs_review")
        self.assertIn("explicit_acceptance_criteria_missing", result.reasons)

    def test_unsupported_network_and_bounty_are_blocked(self):
        detail = dict(self.detail, bounty={"amount_display": "0.01", "network": "eip155:1"})
        result = self.evaluator.evaluate(self.lead, detail)
        self.assertEqual(result.state, "needs_review")
        self.assertIn("bounty_below_minimum", result.reasons)
        self.assertIn("unsupported_or_missing_network", result.reasons)

    def test_no_evaluation_ever_authorizes_claim(self):
        result = self.evaluator.evaluate(self.lead, self.detail)
        self.assertFalse(result.to_dict()["claim_allowed"])


if __name__ == "__main__":
    unittest.main()
