import base64
import tempfile
import unittest
from pathlib import Path

from economy.identity import ParticipantRegistry


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = ParticipantRegistry(Path(self.tmp.name) / "participants.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_human_account_is_not_claimed_as_kyc_verified(self):
        person = self.registry.create_human("alice", "Alice")
        self.assertEqual(person["participant_type"], "human")
        self.assertEqual(person["metadata"]["account_control_method"], "unverified")
        self.assertEqual(person["status"], "active")

    def test_duplicate_handle_rejected(self):
        self.registry.create_human("alice", "Alice")
        with self.assertRaises(Exception):
            self.registry.create_human("alice", "Alice 2")

    def test_agent_challenge_requires_valid_signature_and_consumes_once(self):
        public_key = base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")
        challenge = self.registry.begin_agent_enrollment("worker", "Worker", public_key)
        verified = []
        def verifier(key, message, signature):
            verified.append((key, message, signature))
            return signature == "valid"
        agent = self.registry.complete_agent_enrollment(
            challenge["challenge_id"], "valid", verifier=verifier
        )
        self.assertEqual(agent["participant_type"], "agent")
        self.assertEqual(agent["metadata"]["identity_method"], "ed25519_possession")
        with self.assertRaises(ValueError):
            self.registry.complete_agent_enrollment(
                challenge["challenge_id"], "valid", verifier=verifier
            )

    def test_human_can_bind_signing_key_with_single_use_proof(self):
        person = self.registry.create_human("carol", "Carol")
        public_key = base64.urlsafe_b64encode(b"z" * 32).decode().rstrip("=")
        challenge = self.registry.begin_key_binding(person["participant_id"], public_key)
        bound = self.registry.complete_key_binding(
            challenge["challenge_id"], "valid", verifier=lambda *_: True
        )
        self.assertEqual(bound["public_key"], public_key)
        self.assertEqual(bound["metadata"]["signing_key_method"], "ed25519_possession")
        with self.assertRaisesRegex(ValueError, "already consumed"):
            self.registry.complete_key_binding(
                challenge["challenge_id"], "valid", verifier=lambda *_: True
            )

    def test_human_key_binding_rejects_invalid_proof_and_duplicate_key(self):
        person = self.registry.create_human("dave", "Dave")
        public_key = base64.urlsafe_b64encode(b"q" * 32).decode().rstrip("=")
        challenge = self.registry.begin_key_binding(person["participant_id"], public_key)
        with self.assertRaisesRegex(ValueError, "proof is invalid"):
            self.registry.complete_key_binding(
                challenge["challenge_id"], "bad", verifier=lambda *_: False
            )
        self.registry.complete_key_binding(
            challenge["challenge_id"], "valid", verifier=lambda *_: True
        )
        other = self.registry.create_human("erin", "Erin")
        challenge2 = self.registry.begin_key_binding(other["participant_id"], public_key)
        with self.assertRaisesRegex(ValueError, "already bound"):
            self.registry.complete_key_binding(
                challenge2["challenge_id"], "valid", verifier=lambda *_: True
            )

    def test_key_rotation_requires_both_keys_and_records_history(self):
        person = self.registry.create_human("rotate-me", "Rotate Me")
        old_key = base64.urlsafe_b64encode(b"r" * 32).decode().rstrip("=")
        new_key = base64.urlsafe_b64encode(b"n" * 32).decode().rstrip("=")
        challenge = self.registry.begin_key_binding(person["participant_id"], old_key)
        self.registry.complete_key_binding(
            challenge["challenge_id"], "old-proof", verifier=lambda *_: True
        )
        rotation = self.registry.begin_key_rotation(person["participant_id"], new_key)
        verifier = lambda key, message, signature: (
            (key == old_key and signature == "old-proof")
            or (key == new_key and signature == "new-proof")
        )
        with self.assertRaisesRegex(ValueError, "new-key rotation proof"):
            self.registry.complete_key_rotation(
                rotation["challenge_id"], "old-proof", "wrong", verifier=verifier
            )
        rotated = self.registry.complete_key_rotation(
            rotation["challenge_id"], "old-proof", "new-proof", verifier=verifier
        )
        self.assertEqual(rotated["public_key"], new_key)
        history = self.registry.key_history(person["participant_id"])
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["old_public_key"], old_key)
        self.assertEqual(history[0]["new_public_key"], new_key)
        other = self.registry.create_human("other", "Other")
        with self.assertRaisesRegex(ValueError, "key history"):
            self.registry.begin_key_binding(other["participant_id"], old_key)

    def test_invalid_agent_signature_rejected(self):
        public_key = base64.urlsafe_b64encode(b"y" * 32).decode().rstrip("=")
        challenge = self.registry.begin_agent_enrollment("worker", "Worker", public_key)
        with self.assertRaises(ValueError):
            self.registry.complete_agent_enrollment(
                challenge["challenge_id"], "invalid", verifier=lambda *_: False
            )

    def test_claim_scope_is_explicit(self):
        person = self.registry.create_human("bob", "Bob")
        claim_id = self.registry.add_claim(
            person["participant_id"], "account_control", "local-test", "account",
            status="self_asserted"
        )
        claims = self.registry.claims(person["participant_id"])
        self.assertEqual(claims[0]["claim_id"], claim_id)
        self.assertEqual(claims[0]["status"], "self_asserted")


if __name__ == "__main__":
    unittest.main()
