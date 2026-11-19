import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from economy.financial_console import main, _cloud_policy_envelope


class FinancialConsoleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data = Path(self.tmp.name) / "data"

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        output = io.StringIO()
        with patch.object(sys, "argv", ["economy-finance", "--data-dir", str(self.data), *args]):
            with contextlib.redirect_stdout(output):
                code = main()
        self.assertEqual(code, 0)
        return output.getvalue()

    def test_empty_policy_and_schedule_inventory_is_readable(self):
        self.assertEqual(json.loads(self.run_cli("policies")), [])
        self.assertEqual(json.loads(self.run_cli("schedules")), [])

    def test_emergency_pause_all_is_idempotent_and_local(self):
        first = json.loads(self.run_cli("pause-all"))
        second = json.loads(self.run_cli("pause-all"))
        self.assertEqual(first["paused_schedules"], 0)
        self.assertEqual(second["paused_schedules"], 0)
        self.assertIn("paused", second["message"])

    def test_policy_template_writes_normalized_unsigned_terms_without_overwrite(self):
        output = self.data / "policy-template.json"
        self.run_cli(
            "policy-template", "--policy-id", "ops", "--version", "1",
            "--owner-id", "owner", "--agent-id", "agent", "--currency", "USD",
            "--per-transaction-limit-minor", "250",
            "--daily-spend-limit-minor", "500",
            "--destination", "service:compute", "--output", str(output),
        )
        payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(payload["allowed_destinations"], ["service:compute"])
        self.assertEqual(payload["per_transaction_limit_minor"], 250)
        with self.assertRaises(SystemExit):
            self.run_cli(
                "policy-template", "--policy-id", "ops", "--version", "1",
                "--owner-id", "owner", "--agent-id", "agent", "--currency", "USD",
                "--per-transaction-limit-minor", "250",
                "--daily-spend-limit-minor", "500",
                "--destination", "service:compute", "--output", str(output),
            )



    def test_cloud_policy_envelope_signs_exact_cloud_schema_and_matches_enrolled_owner_key(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            self.skipTest("cryptography identity extra is not installed")
        import base64
        import hashlib

        key = Ed25519PrivateKey.generate()
        public_raw = key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        public_key = base64.urlsafe_b64encode(public_raw).decode("ascii").rstrip("=")
        owner = {"status": "active", "participant_type": "human", "public_key": public_key}
        agent = {"status": "active", "participant_type": "agent", "operator_id": "owner-01"}

        class Registry:
            def get(self, participant_id):
                return {"owner-01": owner, "agent-01": agent}.get(participant_id)

        payload = {
            "policy_id": "policy-01", "version": 1, "owner_id": "owner-01",
            "agent_id": "agent-01", "currency": "USD",
            "per_transaction_limit_minor": 250, "daily_spend_limit_minor": 500,
            "allowed_destinations": ["service:compute"],
        }
        envelope = _cloud_policy_envelope(Registry(), payload, key, "operator-01")
        self.assertEqual(set(envelope), {
            "policy", "canonical_payload", "signature_base64url", "signer_key_fingerprint"
        })
        signature = base64.urlsafe_b64decode(
            envelope["signature_base64url"] + "=" * (-len(envelope["signature_base64url"]) % 4)
        )
        key.public_key().verify(signature, envelope["canonical_payload"].encode("utf-8"))
        fingerprint_json = json.dumps(
            {"crv": "Ed25519", "kty": "OKP", "x": public_key}, separators=(",", ":")
        )
        self.assertEqual(envelope["signer_key_fingerprint"],
                         hashlib.sha256(fingerprint_json.encode("utf-8")).hexdigest())
        self.assertEqual(envelope["policy"], payload)

    def test_cloud_policy_export_rejects_key_mismatch_and_unowned_agent(self):
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            self.skipTest("cryptography identity extra is not installed")
        import base64

        enrolled_key = Ed25519PrivateKey.generate()
        wrong_key = Ed25519PrivateKey.generate()
        public_raw = enrolled_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
        owner = {"status": "active", "participant_type": "human",
                 "public_key": base64.urlsafe_b64encode(public_raw).decode("ascii").rstrip("=")}
        agent = {"status": "active", "participant_type": "agent", "operator_id": "other-owner"}

        class Registry:
            def get(self, participant_id):
                return {"owner-01": owner, "agent-01": agent}.get(participant_id)

        payload = {
            "policy_id": "policy-01", "version": 1, "owner_id": "owner-01",
            "agent_id": "agent-01", "currency": "USD",
            "per_transaction_limit_minor": 250, "daily_spend_limit_minor": 500,
            "allowed_destinations": ["service:compute"],
        }
        with self.assertRaisesRegex(ValueError, "operated by this owner"):
            _cloud_policy_envelope(Registry(), payload, enrolled_key, "operator-01")
        agent["operator_id"] = "owner-01"
        with self.assertRaisesRegex(ValueError, "does not match"):
            _cloud_policy_envelope(Registry(), payload, wrong_key, "operator-01")

if __name__ == "__main__":
    unittest.main()
