import tempfile
import unittest
from pathlib import Path

from economy.permissions import CapabilityStore
from economy.policy import ActionApprovalStore, PolicyEngine


class PolicyEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "economy.sqlite3"
        self.secret = "owner-secret-" * 4
        self.capabilities = CapabilityStore(self.path)
        self.approvals = ActionApprovalStore(self.path)
        self.engine = PolicyEngine(
            self.capabilities, self.approvals, approval_secret=self.secret,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_low_risk_capability_allows_and_is_audited(self):
        self.capabilities.grant("agent-1", "owner", "task:submit", "project:1")
        result = self.engine.authorize("agent-1", "task:submit", "project:1")
        self.assertEqual(result["decision"], "allow")
        self.assertEqual(len(self.engine.audit("agent-1")), 1)

    def test_high_risk_requires_exact_single_use_owner_approval(self):
        self.capabilities.grant(
            "agent-1", "owner", "spend", "treasury:main",
            max_amount_minor=1000, currency="USD",
        )
        missing = self.engine.authorize(
            "agent-1", "spend", "treasury:main", amount_minor=250, currency="USD",
        )
        self.assertEqual(missing["decision"], "require_approval")
        token = ActionApprovalStore.create_token(
            "agent-1", "spend", "treasury:main", self.secret,
            amount_minor=250, currency="USD",
        )
        approved = self.engine.authorize(
            "agent-1", "spend", "treasury:main", amount_minor=250,
            currency="USD", approval_token=token,
        )
        self.assertEqual(approved["decision"], "allow")
        self.assertIn("no action executed", approved["reason"])
        replay = self.engine.authorize(
            "agent-1", "spend", "treasury:main", amount_minor=250,
            currency="USD", approval_token=token,
        )
        self.assertEqual(replay["decision"], "require_approval")
        self.assertIn("already been used", replay["reason"])
        self.assertEqual(len(self.engine.audit("agent-1")), 4)

    def test_approval_is_bound_to_subject_action_resource_and_amount(self):
        self.capabilities.grant(
            "agent-1", "owner", "spend", "treasury:main",
            max_amount_minor=1000, currency="USD",
        )
        token = ActionApprovalStore.create_token(
            "agent-1", "spend", "treasury:main", self.secret,
            amount_minor=200, currency="USD",
        )
        result = self.engine.authorize(
            "agent-1", "spend", "treasury:main", amount_minor=201,
            currency="USD", approval_token=token,
        )
        self.assertEqual(result["decision"], "require_approval")

    def test_financial_approval_requires_amount_and_currency(self):
        with self.assertRaisesRegex(ValueError, "amount and currency"):
            ActionApprovalStore.create_token(
                "agent-1", "transfer", "wallet:1", self.secret,
            )

    def test_approval_does_not_replace_missing_capability(self):
        token = ActionApprovalStore.create_token(
            "agent-1", "spend", "treasury:main", self.secret,
            amount_minor=50, currency="USD",
        )
        result = self.engine.authorize(
            "agent-1", "spend", "treasury:main", amount_minor=50,
            currency="USD", approval_token=token,
        )
        self.assertEqual(result["decision"], "deny")


if __name__ == "__main__":
    unittest.main()
