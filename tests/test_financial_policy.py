import base64
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from economy.financial_policy import FinancialPolicyError, FinancialPolicyStore, _canonical


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


class FakeParticipantRegistry:
    def __init__(self, owner_key: str):
        self.records = {
            "owner-1": {
                "participant_id": "owner-1", "participant_type": "human",
                "status": "active", "public_key": owner_key,
            },
            "agent-1": {
                "participant_id": "agent-1", "participant_type": "agent",
                "status": "active", "public_key": "agent-public-key",
                "operator_id": "owner-1",
            },
        }

    def get(self, participant_id):
        return self.records.get(participant_id)


class FinancialPolicyStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.private_key = Ed25519PrivateKey.generate()
        self.public_key = b64(self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        ))
        self.registry = FakeParticipantRegistry(self.public_key)
        self.store = FinancialPolicyStore(
            self.registry, Path(self.tmp.name) / "policies.sqlite3"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def payload(self, version=1):
        return self.store.payload(
            policy_id="agent-ops",
            version=version,
            owner_id="owner-1",
            agent_id="agent-1",
            currency="USD",
            per_transaction_limit_minor=500,
            daily_spend_limit_minor=2000,
            allowed_destinations=["service:compute", "service:storage"],
        )

    def sign(self, payload):
        return b64(self.private_key.sign(_canonical(payload)))

    def test_valid_owner_signature_saves_active_policy(self):
        payload = self.payload()
        saved = self.store.save(payload, self.sign(payload))
        self.assertEqual(saved["status"], "active")
        self.assertTrue(saved["currently_authorized"])
        self.assertEqual(saved["policy"]["daily_spend_limit_minor"], 2000)

    def test_invalid_signature_is_rejected(self):
        with self.assertRaisesRegex(FinancialPolicyError, "signature"):
            self.store.save(self.payload(), b64(b"\x00" * 64))

    def test_non_operator_cannot_sign_agent_policy(self):
        self.registry.records["owner-2"] = {
            "participant_id": "owner-2", "participant_type": "organization",
            "status": "active", "public_key": self.public_key,
        }
        payload = self.payload()
        payload["owner_id"] = "owner-2"
        payload = self.store.payload(
            policy_id=payload["policy_id"], version=payload["version"],
            owner_id="owner-2", agent_id="agent-1", currency="USD",
            per_transaction_limit_minor=500, daily_spend_limit_minor=2000,
            allowed_destinations=["service:compute"],
        )
        with self.assertRaisesRegex(FinancialPolicyError, "operator"):
            self.store.save(payload, self.sign(payload))

    def test_policy_version_must_increase_and_old_version_is_superseded(self):
        first = self.payload(1)
        self.store.save(first, self.sign(first))
        second = self.payload(2)
        saved = self.store.save(second, self.sign(second))
        self.assertEqual(saved["version"], 2)
        self.assertEqual(saved["status"], "active")
        self.assertTrue(saved["currently_authorized"])
        with self.assertRaisesRegex(FinancialPolicyError, "increase"):
            self.store.save(first, self.sign(first))

    def test_owner_key_rotation_invalidates_existing_policy(self):
        payload = self.payload()
        self.store.save(payload, self.sign(payload))
        replacement = Ed25519PrivateKey.generate()
        self.registry.records["owner-1"]["public_key"] = b64(
            replacement.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        )
        self.assertFalse(self.store.get("agent-1", "agent-ops")["currently_authorized"])

    def test_inactive_owner_or_agent_is_rejected(self):
        self.registry.records["owner-1"]["status"] = "suspended"
        with self.assertRaisesRegex(FinancialPolicyError, "inactive"):
            self.store.save(self.payload(), self.sign(self.payload()))

    def test_wildcard_and_overflow_limits_are_rejected(self):
        with self.assertRaisesRegex(FinancialPolicyError, "wildcard"):
            self.store.payload(
                policy_id="x", version=1, owner_id="owner-1", agent_id="agent-1",
                currency="USD", per_transaction_limit_minor=1,
                daily_spend_limit_minor=1, allowed_destinations=["*"],
            )
        with self.assertRaisesRegex(FinancialPolicyError, "signed-64-bit"):
            self.store.payload(
                policy_id="x", version=1, owner_id="owner-1", agent_id="agent-1",
                currency="USD", per_transaction_limit_minor=2**63,
                daily_spend_limit_minor=2**63, allowed_destinations=["service:x"],
            )


if __name__ == "__main__":
    unittest.main()
