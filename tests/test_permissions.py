import tempfile
import unittest
from pathlib import Path

from economy.permissions import CapabilityStore


class PermissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = CapabilityStore(Path(self.tmp.name) / "participants.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_deny(self):
        result = self.store.authorize("agent_1", "task:submit", "project:1")
        self.assertEqual(result["decision"], "deny")

    def test_exact_scope_allows(self):
        self.store.grant("agent_1", "owner_1", "task:submit", "project:1")
        result = self.store.authorize("agent_1", "task:submit", "project:1")
        self.assertEqual(result["decision"], "allow")

    def test_wildcard_resource_is_explicit(self):
        self.store.grant("agent_1", "owner_1", "opportunity:discover", "*")
        self.assertEqual(
            self.store.authorize("agent_1", "opportunity:discover", "public")["decision"],
            "allow"
        )

    def test_high_risk_requires_approval_reference(self):
        self.store.grant("agent_1", "owner_1", "spend", "treasury", max_amount_minor=500, currency="USD")
        self.assertEqual(
            self.store.authorize("agent_1", "spend", "treasury", amount_minor=100, currency="USD")["decision"],
            "require_approval"
        )
        self.assertEqual(
            self.store.authorize("agent_1", "spend", "treasury", amount_minor=100,
                                 currency="USD", approval_ref="approval-123")["decision"],
            "allow"
        )

    def test_amount_limit_and_currency_enforced(self):
        self.store.grant("agent_1", "owner_1", "spend", "treasury", max_amount_minor=100, currency="USD")
        self.assertEqual(
            self.store.authorize("agent_1", "spend", "treasury", amount_minor=101,
                                 currency="USD", approval_ref="x")["decision"],
            "deny"
        )
        self.assertEqual(
            self.store.authorize("agent_1", "spend", "treasury", amount_minor=50,
                                 currency="EUR", approval_ref="x")["decision"],
            "deny"
        )

    def test_revoked_grant_denied(self):
        grant = self.store.grant("agent_1", "owner_1", "task:submit", "project:1")
        self.store.revoke(grant, "owner_1")
        self.assertEqual(self.store.authorize("agent_1", "task:submit", "project:1")["decision"], "deny")

    def test_only_issuer_can_revoke(self):
        grant = self.store.grant("agent_1", "owner_1", "task:submit", "project:1")
        with self.assertRaises(ValueError):
            self.store.revoke(grant, "agent_2")

    def test_audit_records_denial(self):
        self.store.authorize("agent_1", "task:submit", "project:1")
        self.assertEqual(len(self.store.audit("agent_1")), 1)


if __name__ == "__main__":
    unittest.main()
