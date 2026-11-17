import hashlib
import tempfile
import unittest
from pathlib import Path

from economy.artifact_evidence import (
    MANIFEST_SCHEMA, MAX_ARTIFACT_BYTES, validate_manifest, verify_local_artifact,
)


class ArtifactEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "deliverable.bin"
        self.data = b"actual delivered bytes\x00\x01"
        self.path.write_bytes(self.data)
        self.manifest = {
            "schema": MANIFEST_SCHEMA,
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "size_bytes": len(self.data),
            "media_type": "application/octet-stream",
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_local_bytes_match_manifest(self):
        result = verify_local_artifact(self.path, self.manifest)
        self.assertTrue(result["valid"])
        self.assertEqual(result["sha256"], self.manifest["sha256"])

    def test_digest_mismatch_is_not_valid(self):
        self.path.write_bytes(b"altered")
        result = verify_local_artifact(self.path, self.manifest)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "size_mismatch")

    def test_same_size_tampering_is_detected_by_digest(self):
        self.path.write_bytes(b"changed delivered bytes\x00")
        self.manifest["size_bytes"] = self.path.stat().st_size
        result = verify_local_artifact(self.path, self.manifest)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "sha256_mismatch")

    def test_rejects_symlink(self):
        link = Path(self.tmp.name) / "link.bin"
        link.symlink_to(self.path)
        with self.assertRaisesRegex(ValueError, "non-symlink"):
            verify_local_artifact(link, self.manifest)

    def test_manifest_rejects_boolean_size_and_extra_fields(self):
        invalid = dict(self.manifest, size_bytes=True)
        with self.assertRaisesRegex(ValueError, "size_bytes"):
            validate_manifest(invalid)
        invalid = dict(self.manifest, provenance="claimed")
        with self.assertRaisesRegex(ValueError, "exactly"):
            validate_manifest(invalid)

    def test_manifest_enforces_size_limit(self):
        invalid = dict(self.manifest, size_bytes=MAX_ARTIFACT_BYTES + 1)
        with self.assertRaisesRegex(ValueError, "size_bytes"):
            validate_manifest(invalid)


if __name__ == "__main__":
    unittest.main()
