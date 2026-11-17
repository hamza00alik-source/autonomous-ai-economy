import base64
import tempfile
import unittest
from pathlib import Path

from economy.permissions import CapabilityStore
from economy.policy import ActionApprovalStore, PolicyEngine
from economy.delegation import DelegationStore
from economy.identity import ParticipantRegistry
from datetime import datetime, timedelta, timezone


class PolicyEngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "economy.sqlite3"
        self.secret = "owner-secret-" * 4
        self.capabilities = CapabilityStore(self.path)
        self.registry = ParticipantRegistry(self.path)
        self.subject_id = self.registry.create_human(
            "policy-agent", "Policy Agent"
        )["participant_id"]
        self.approvals = ActionApprovalStore(self.path)
        self.engine = PolicyEngine(
            self.capabilities, self.approvals, approval_secret=self.secret,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_low_risk_capability_allows_and_is_audited(self):
        self.capabilities.grant(self.subject_id, "owner", "task:submit", "project:1")
        result = self.engine.authorize(self.subject_id, "task:submit", "project:1")
        self.assertEqual(result["decision"], "allow")
        self.assertEqual(len(self.engine.audit(self.subject_id)), 1)

    def test_high_risk_requires_exact_single_use_owner_approval(self):
        self.capabilities.grant(
            self.subject_id, "owner", "spend", "treasury:main",
            max_amount_minor=1000, currency="USD",
        )
        missing = self.engine.authorize(
            self.subject_id, "spend", "treasury:main", amount_minor=250, currency="USD",
        )
        self.assertEqual(missing["decision"], "require_approval")
        token = ActionApprovalStore.create_token(
            self.subject_id, "spend", "treasury:main", self.secret,
            amount_minor=250, currency="USD",
        )
        approved = self.engine.authorize(
            self.subject_id, "spend", "treasury:main", amount_minor=250,
            currency="USD", approval_token=token,
        )
        self.assertEqual(approved["decision"], "allow")
        self.assertIn("no action executed", approved["reason"])
        replay = self.engine.authorize(
            self.subject_id, "spend", "treasury:main", amount_minor=250,
            currency="USD", approval_token=token,
        )
        self.assertEqual(replay["decision"], "require_approval")
        self.assertIn("already been used", replay["reason"])
        self.assertEqual(len(self.engine.audit(self.subject_id)), 3)

    def test_approval_is_bound_to_subject_action_resource_and_amount(self):
        self.capabilities.grant(
            self.subject_id, "owner", "spend", "treasury:main",
            max_amount_minor=1000, currency="USD",
        )
        token = ActionApprovalStore.create_token(
            self.subject_id, "spend", "treasury:main", self.secret,
            amount_minor=200, currency="USD",
        )
        result = self.engine.authorize(
            self.subject_id, "spend", "treasury:main", amount_minor=201,
            currency="USD", approval_token=token,
        )
        self.assertEqual(result["decision"], "require_approval")

    def test_policy_composes_signed_delegation_with_owner_approval(self):
        registry = ParticipantRegistry(self.path)
        owner = registry.create_human("owner", "Owner")
        owner_key = base64.urlsafe_b64encode(b"o" * 32).decode().rstrip("=")
        agent_key = base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")
        challenge = registry.begin_agent_enrollment("worker", "Worker", agent_key)
        agent = registry.complete_agent_enrollment(
            challenge["challenge_id"], "proof", verifier=lambda *_: True
        )
        delegations = DelegationStore(
            self.path, trusted_roots={owner["participant_id"]: owner_key},
            verifier=lambda key, payload, signature: signature == "valid",
        )
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        delegations.create(
            delegation_id="spend-delegation", delegator_id=owner["participant_id"],
            delegate_id=agent["participant_id"], action="spend",
            resource="treasury:main", expires_at=expiry, signature="valid",
            max_amount_minor=500, currency="USD",
        )
        engine = PolicyEngine(
            self.capabilities, self.approvals, approval_secret=self.secret,
            delegations=delegations,
        )
        pending = engine.authorize(
            agent["participant_id"], "spend", "treasury:main",
            amount_minor=100, currency="USD", delegation_id="spend-delegation",
        )
        self.assertEqual(pending["decision"], "require_approval")
        token = ActionApprovalStore.create_token(
            agent["participant_id"], "spend", "treasury:main", self.secret,
            amount_minor=100, currency="USD",
        )
        approved = engine.authorize(
            agent["participant_id"], "spend", "treasury:main",
            amount_minor=100, currency="USD", delegation_id="spend-delegation",
            approval_token=token,
        )
        self.assertEqual(approved["decision"], "allow")

    def test_financial_approval_requires_amount_and_currency(self):
        with self.assertRaisesRegex(ValueError, "amount and currency"):
            ActionApprovalStore.create_token(
                self.subject_id, "transfer", "wallet:1", self.secret,
            )

    def test_approval_does_not_replace_missing_capability(self):
        token = ActionApprovalStore.create_token(
            self.subject_id, "spend", "treasury:main", self.secret,
            amount_minor=50, currency="USD",
        )
        result = self.engine.authorize(
            self.subject_id, "spend", "treasury:main", amount_minor=50,
            currency="USD", approval_token=token,
        )
        self.assertEqual(result["decision"], "deny")


if __name__ == "__main__":
    unittest.main()
