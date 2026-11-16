import base64
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from economy.delegation import DelegationStore
from economy.identity import ParticipantRegistry


class DelegationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "participants.sqlite3"
        self.registry = ParticipantRegistry(self.path)
        self.owner = self.registry.create_human("owner", "Owner")
        self.owner_key = base64.urlsafe_b64encode(b"o" * 32).decode().rstrip("=")
        self.agent_key = base64.urlsafe_b64encode(b"a" * 32).decode().rstrip("=")
        self.worker_key = base64.urlsafe_b64encode(b"w" * 32).decode().rstrip("=")
        self.agent = self._agent("agent-one", self.agent_key)
        self.worker = self._agent("agent-two", self.worker_key)
        self.store = DelegationStore(
            self.path, trusted_roots={self.owner["participant_id"]: self.owner_key},
            verifier=lambda key, message, signature: signature == "valid",
        )
        self.expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    def tearDown(self):
        self.tmp.cleanup()

    def _agent(self, handle, key):
        challenge = self.registry.begin_agent_enrollment(handle, handle, key)
        return self.registry.complete_agent_enrollment(
            challenge["challenge_id"], "proof", verifier=lambda *_: True
        )

    def _create_root(self, *, action="task:submit", resource="project:alpha",
                     delegation_id="root", expiry=None, signature="valid"):
        return self.store.create(
            delegation_id=delegation_id, delegator_id=self.owner["participant_id"],
            delegate_id=self.agent["participant_id"], action=action, resource=resource,
            expires_at=expiry or self.expiry, signature=signature,
        )

    def test_trusted_root_and_child_delegation_are_narrowed(self):
        self._create_root()
        child = self.store.create(
            delegation_id="child", delegator_id=self.agent["participant_id"],
            delegate_id=self.worker["participant_id"], action="task:submit",
            resource="project:alpha", expires_at=self.expiry, parent_id="root",
            signature="valid",
        )
        self.assertEqual(child["depth"], 1)
        self.assertEqual(self.store.authorize(
            "child", delegate_id=self.worker["participant_id"],
            action="task:submit", resource="project:alpha"
        )["decision"], "allow")

    def test_untrusted_root_and_invalid_signature_rejected(self):
        with self.assertRaisesRegex(ValueError, "trusted owner"):
            self.store.create(
                delegation_id="bad-root", delegator_id=self.agent["participant_id"],
                delegate_id=self.worker["participant_id"], action="task:submit",
                resource="*", expires_at=self.expiry, signature="valid",
            )
        with self.assertRaisesRegex(ValueError, "signature"):
            self._create_root(delegation_id="forged", signature="forged")

    def test_child_cannot_widen_scope_or_outlive_parent(self):
        short = (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat()
        self._create_root(expiry=short)
        with self.assertRaisesRegex(ValueError, "scope exceeds"):
            self.store.create(
                delegation_id="wide", delegator_id=self.agent["participant_id"],
                delegate_id=self.worker["participant_id"], action="*", resource="project:alpha",
                expires_at=short, parent_id="root", signature="valid",
            )
        with self.assertRaisesRegex(ValueError, "outlive"):
            self.store.create(
                delegation_id="late", delegator_id=self.agent["participant_id"],
                delegate_id=self.worker["participant_id"], action="task:submit",
                resource="project:alpha", expires_at=self.expiry, parent_id="root",
                signature="valid",
            )

    def test_parent_revocation_invalidates_descendants(self):
        self._create_root()
        self.store.create(
            delegation_id="child", delegator_id=self.agent["participant_id"],
            delegate_id=self.worker["participant_id"], action="task:submit",
            resource="project:alpha", expires_at=self.expiry, parent_id="root",
            signature="valid",
        )
        self.store.revoke("root", actor_id=self.owner["participant_id"], signature="valid")
        result = self.store.authorize(
            "child", delegate_id=self.worker["participant_id"],
            action="task:submit", resource="project:alpha",
        )
        self.assertEqual(result["decision"], "deny")

    def test_high_risk_delegation_never_executes_without_separate_approval(self):
        self._create_root(action="spend", resource="treasury:main", delegation_id="spend-root")
        result = self.store.authorize(
            "spend-root", delegate_id=self.agent["participant_id"],
            action="spend", resource="treasury:main", amount_minor=100, currency="USD",
        )
        self.assertEqual(result["decision"], "require_approval")

    def test_amount_and_currency_ceiling_enforced(self):
        self.store.create(
            delegation_id="budget", delegator_id=self.owner["participant_id"],
            delegate_id=self.agent["participant_id"], action="task:submit",
            resource="project:alpha", expires_at=self.expiry, signature="valid",
            max_amount_minor=500, currency="USD",
        )
        self.assertEqual(self.store.authorize(
            "budget", delegate_id=self.agent["participant_id"],
            action="task:submit", resource="project:alpha",
            amount_minor=501, currency="USD",
        )["decision"], "deny")
        self.assertEqual(self.store.authorize(
            "budget", delegate_id=self.agent["participant_id"],
            action="task:submit", resource="project:alpha",
            amount_minor=500, currency="EUR",
        )["decision"], "deny")


if __name__ == "__main__":
    unittest.main()
