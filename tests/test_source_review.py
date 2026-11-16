import tempfile
import unittest
from pathlib import Path

from economy.source_review import SourceReviewStore, normalize_source_url


def snapshot(url="https://publisher.example/story", digest="a" * 64):
    return {
        "url": url,
        "final_url": url,
        "hostname": "publisher.example",
        "content_sha256": digest,
        "verification_status": "retrieved_unverified",
        "buyer_evidence_created": False,
        "extracted_text": "Untrusted page text",
    }


class SourceReviewStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SourceReviewStore(Path(self.temp.name) / "research.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def review(self, snap=None, **kwargs):
        return self.store.record_review(
            snap or snapshot(),
            classification=kwargs.get("classification", "supports_buyer_problem"),
            finding=kwargs.get("finding", "The page describes a stated workflow problem."),
            reviewer_note=kwargs.get("reviewer_note", "Read the original page and checked its context."),
        )

    def test_normalizes_https_url_and_removes_fragment(self):
        self.assertEqual(
            normalize_source_url("https://Publisher.Example:443/story#section"),
            "https://publisher.example/story",
        )

    def test_rejects_non_https_and_credentials(self):
        for url in ("http://publisher.example/story", "https://user@publisher.example/story"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                normalize_source_url(url)

    def test_records_explicit_owner_classification_without_creating_evidence(self):
        record = self.review()
        self.assertEqual(record["classification"], "supports_buyer_problem")
        self.assertEqual(record["publisher_identity"], "publisher.example")
        self.assertFalse(record["evidence_created"])
        self.assertFalse(record["independent_source_claim"])
        self.assertEqual(len(self.store.list_reviews()), 1)

    def test_duplicate_url_or_content_hash_cannot_be_counted_twice(self):
        self.review()
        with self.assertRaisesRegex(ValueError, "already reviewed"):
            self.review()
        with self.assertRaisesRegex(ValueError, "already reviewed"):
            self.review(snapshot("https://publisher.example/another-page", "a" * 64))

    def test_requires_supported_classification_finding_and_note(self):
        with self.assertRaises(ValueError):
            self.review(classification="buyer_signal")
        with self.assertRaises(ValueError):
            self.review(finding=" ")
        with self.assertRaises(ValueError):
            self.review(reviewer_note=" ")

    def test_rejects_snapshot_that_claims_verification_or_evidence(self):
        invalid = snapshot()
        invalid["verification_status"] = "verified"
        with self.assertRaises(ValueError):
            self.review(invalid)
        invalid = snapshot()
        invalid["buyer_evidence_created"] = True
        with self.assertRaises(ValueError):
            self.review(invalid)


if __name__ == "__main__":
    unittest.main()
