import tempfile
import unittest
from pathlib import Path

from economy.permissions import CapabilityStore
from economy.identity import ParticipantRegistry


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "participants.sqlite3"
        self.store = CapabilityStore(db_path)
        self.registry = ParticipantRegistry(db_path)
        self.agent_id = self.registry.create_human("agent-subject", "Agent Subject")["participant_id"]

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_deny(self):
        result = self.store.authorize(self.agent_id, "task:submit", "project:1")
        self.assertEqual(result["decision"], "deny")

    def test_missing_participant_registry_fails_closed(self):
        isolated = CapabilityStore(Path(self.tmp.name) / "isolated.sqlite3")
        isolated.grant("agent_missing", "owner_1", "task:submit", "project:1")
        result = isolated.authorize("agent_missing", "task:submit", "project:1")
        self.assertEqual(result["decision"], "deny")
        self.assertEqual(result["reason"], "participant registry is unavailable")

    def test_exact_scope_allows(self):
        self.store.grant(self.agent_id, "owner_1", "task:submit", "project:1")
        result = self.store.authorize(self.agent_id, "task:submit", "project:1")
        self.assertEqual(result["decision"], "allow")

    def test_wildcard_resource_is_explicit(self):
        self.store.grant(self.agent_id, "owner_1", "opportunity:discover", "*")
        self.assertEqual(
            self.store.authorize(self.agent_id, "opportunity:discover", "public")["decision"],
            "allow"
        )

    def test_high_risk_requires_approval_reference(self):
        self.store.grant(self.agent_id, "owner_1", "spend", "treasury", max_amount_minor=500, currency="USD")
        self.assertEqual(
            self.store.authorize(self.agent_id, "spend", "treasury", amount_minor=100, currency="USD")["decision"],
            "require_approval"
        )
        self.assertEqual(
            self.store.authorize(self.agent_id, "spend", "treasury", amount_minor=100,
                                 currency="USD", approval_ref="approval-123")["decision"],
            "require_approval"
        )

    def test_amount_limit_and_currency_enforced(self):
        self.store.grant(self.agent_id, "owner_1", "spend", "treasury", max_amount_minor=100, currency="USD")
        self.assertEqual(
            self.store.authorize(self.agent_id, "spend", "treasury", amount_minor=101,
                                 currency="USD", approval_ref="x")["decision"],
            "deny"
        )
        self.assertEqual(
            self.store.authorize(self.agent_id, "spend", "treasury", amount_minor=50,
                                 currency="EUR", approval_ref="x")["decision"],
            "deny"
        )
        self.assertEqual(
            self.store.authorize(self.agent_id, "spend", "treasury")["decision"],
            "deny"
        )

    def test_negative_amount_is_always_denied(self):
        self.store.grant(self.agent_id, "owner_1", "spend", "treasury",
                         max_amount_minor=100, currency="USD")
        self.assertEqual(
            self.store.authorize(self.agent_id, "spend", "treasury",
                                 amount_minor=-1, currency="USD")["decision"],
            "deny"
        )

    def test_amount_ceiling_requires_currency_and_valid_expiry(self):
        with self.assertRaisesRegex(ValueError, "supplied together"):
            self.store.grant(self.agent_id, "owner_1", "spend", "treasury",
                             max_amount_minor=100)
        with self.assertRaisesRegex(ValueError, "future timezone-aware"):
            self.store.grant(self.agent_id, "owner_1", "task:submit", "project",
                             expires_at="2030-01-01T00:00:00")

    def test_suspended_participant_cannot_use_existing_capability(self):
        registry = ParticipantRegistry(Path(self.tmp.name) / "participants.sqlite3")
        person = registry.create_human("participant", "Participant")
        participant_id = person["participant_id"]
        self.store.grant(participant_id, "owner", "task:submit", "project:one")
        self.assertEqual(
            self.store.authorize(participant_id, "task:submit", "project:one")["decision"],
            "allow"
        )
        registry.set_status(participant_id, "suspended")
        self.assertEqual(
            self.store.authorize(participant_id, "task:submit", "project:one")["decision"],
            "deny"
        )

    def test_revoked_grant_denied(self):
        grant = self.store.grant(self.agent_id, "owner_1", "task:submit", "project:1")
        self.store.revoke(grant, "owner_1")
        self.assertEqual(self.store.authorize(self.agent_id, "task:submit", "project:1")["decision"], "deny")

    def test_only_issuer_can_revoke(self):
        grant = self.store.grant(self.agent_id, "owner_1", "task:submit", "project:1")
        with self.assertRaises(ValueError):
            self.store.revoke(grant, "agent_2")

    def test_audit_records_denial(self):
        self.store.authorize(self.agent_id, "task:submit", "project:1")
        self.assertEqual(len(self.store.audit(self.agent_id)), 1)


if __name__ == "__main__":
    unittest.main()
