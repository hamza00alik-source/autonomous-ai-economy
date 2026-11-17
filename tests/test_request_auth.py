import base64
import tempfile
import unittest
from pathlib import Path

from economy.identity import ParticipantRegistry
from economy.request_auth import RequestAuthenticator


class RequestAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.registry = ParticipantRegistry(root / "participants.sqlite3")
        self.person = self.registry.create_human("signed-user", "Signed User")
        self.public_key = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
        challenge = self.registry.begin_key_binding(
            self.person["participant_id"], self.public_key
        )
        self.registry.complete_key_binding(
            challenge["challenge_id"], "proof", verifier=lambda *_: True
        )
        self.now = 1_800_000_000
        self.signed_payloads = set()

        def verifier(_key, payload, signature):
            return signature == "valid" and payload in self.signed_payloads

        self.auth = RequestAuthenticator(
            self.registry, root / "replay.sqlite3",
            verifier=verifier, clock=lambda: self.now,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _request(self, nonce="abcdefghijklmnop", *, timestamp=None,
                 method="POST", path="/v1/tasks/offers", body=b'{"task":"x"}'):
        timestamp = self.now if timestamp is None else timestamp
        payload = self.auth.signing_bytes(method, path, body, timestamp, nonce)
        self.signed_payloads.add(payload)
        return self.auth.authenticate(
            self.person["participant_id"], method, path, body,
            timestamp, nonce, "valid",
        )

    def test_authenticates_current_active_participant_key(self):
        result = self._request()
        self.assertTrue(result["authenticated"])
        self.assertEqual(result["participant_type"], "human")
        self.assertEqual(len(result["key_id"]), 24)

    def test_rejects_replayed_nonce(self):
        self._request()
        with self.assertRaisesRegex(ValueError, "already been used"):
            self._request()

    def test_signature_is_bound_to_method_path_and_body(self):
        timestamp = self.now
        nonce = "qrstuvwxyzABCDEF"
        original = self.auth.signing_bytes(
            "POST", "/v1/tasks/offers", b'{"task":"x"}', timestamp, nonce
        )
        self.signed_payloads.add(original)
        with self.assertRaisesRegex(ValueError, "signature is invalid"):
            self.auth.authenticate(
                self.person["participant_id"], "POST", "/v1/tasks/other",
                b'{"task":"x"}', timestamp, nonce, "valid",
            )

    def test_rejects_stale_request(self):
        with self.assertRaisesRegex(ValueError, "clock window"):
            self._request(timestamp=self.now - 301)

    def test_rejects_unbound_or_inactive_participant(self):
        other = self.registry.create_human("unbound", "Unbound")
        with self.assertRaisesRegex(ValueError, "no bound signing key"):
            self.auth.authenticate(
                other["participant_id"], "GET", "/v1/participants/me",
                b"", self.now, "1234567890abcdef", "valid",
            )
        self.registry.set_status(self.person["participant_id"], "suspended")
        with self.assertRaisesRegex(ValueError, "inactive"):
            self._request(nonce="ABCDEFGHIJKLMNOP")

    def test_rejects_malformed_nonce_and_path(self):
        with self.assertRaisesRegex(ValueError, "nonce"):
            self.auth.signing_bytes("GET", "/health", b"", self.now, "short")
        with self.assertRaisesRegex(ValueError, "absolute request path"):
            self.auth.signing_bytes("GET", "https://example.test/", b"",
                                    self.now, "abcdefghijklmnop")


if __name__ == "__main__":
    unittest.main()
