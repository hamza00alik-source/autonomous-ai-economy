import json
import tempfile
import unittest
from pathlib import Path

from economy.audit_checkpoint import export_checkpoint, verify_checkpoint
from economy.task_store import TaskStore

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
except ImportError:
    serialization = None
    Ed25519PrivateKey = None


@unittest.skipIf(Ed25519PrivateKey is None, "cryptography identity extra is not installed")
class AuditCheckpointTests(unittest.TestCase):
    def test_signed_checkpoint_verifies_and_matches_local_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "economy.sqlite3")
            store.enqueue("Checkpoint", "Signed head", "agent-a")
            private = Ed25519PrivateKey.generate()
            private_path = root / "owner-private.pem"
            public_path = root / "owner-public.pem"
            checkpoint_path = root / "checkpoint.json"
            private_path.write_bytes(private.private_bytes(
                serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))
            public_path.write_bytes(private.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
            exported = export_checkpoint(store, private_path, checkpoint_path)
            self.assertEqual(exported["checked_events"], 1)
            verified = verify_checkpoint(checkpoint_path, public_path, store)
            self.assertTrue(verified["valid"])
            self.assertTrue(verified["matches_local_head"])

    def test_checkpoint_tampering_and_wrong_key_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "economy.sqlite3")
            store.enqueue("Checkpoint", "Tamper", "agent-a")
            private = Ed25519PrivateKey.generate()
            other = Ed25519PrivateKey.generate()
            priv_path, pub_path, wrong_path = root / "private.pem", root / "public.pem", root / "wrong.pem"
            cp_path = root / "checkpoint.json"
            priv_path.write_bytes(private.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            pub_path.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo))
            wrong_path.write_bytes(other.public_key().public_bytes(serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo))
            export_checkpoint(store, priv_path, cp_path)
            self.assertFalse(verify_checkpoint(cp_path, wrong_path)["valid"])
            doc = json.loads(cp_path.read_text())
            doc["head_hash"] = "f" * 64
            cp_path.write_text(json.dumps(doc))
            self.assertFalse(verify_checkpoint(cp_path, pub_path)["valid"])

    def test_checkpoint_rejects_timezone_free_timestamp_and_boolean_event_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "economy.sqlite3")
            private = Ed25519PrivateKey.generate()
            private_path, public_path = root / "private.pem", root / "public.pem"
            checkpoint_path = root / "checkpoint.json"
            private_path.write_bytes(private.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            public_path.write_bytes(private.public_key().public_bytes(serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo))
            export_checkpoint(store, private_path, checkpoint_path)
            original = json.loads(checkpoint_path.read_text())
            for field, value in (("created_at", "2026-11-17T12:00:00"), ("checked_events", True)):
                altered = dict(original)
                altered[field] = value
                checkpoint_path.write_text(json.dumps(altered))
                with self.assertRaises(ValueError):
                    verify_checkpoint(checkpoint_path, public_path)

    def test_checkpoint_does_not_overwrite_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = TaskStore(root / "economy.sqlite3")
            private = Ed25519PrivateKey.generate()
            key_path, cp_path = root / "private.pem", root / "checkpoint.json"
            key_path.write_bytes(private.private_bytes(serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
            cp_path.write_text("preserve")
            with self.assertRaises(FileExistsError):
                export_checkpoint(store, key_path, cp_path)
            self.assertEqual(cp_path.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
