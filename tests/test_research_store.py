import tempfile
import unittest
from pathlib import Path

from economy.research_sources import ResearchCandidate
from economy.research_store import ResearchCandidateStore


def candidate(candidate_id="abc"):
    return ResearchCandidate(
        candidate_id=candidate_id,
        query="digital products",
        title="Example headline",
        article_url="https://publisher.example/story",
        publisher="Publisher",
        published_at="",
        discovered_at="2026-11-16T00:00:00+00:00",
    )


class ResearchCandidateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ResearchCandidateStore(Path(self.temp.name) / "research.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_persists_and_deduplicates_candidates(self):
        self.assertEqual(
            self.store.save_many([candidate(), candidate()]),
            {"inserted": 1, "already_present": 1},
        )
        self.assertEqual(len(self.store.list_candidates()), 1)
        self.assertEqual(
            self.store.save_many([candidate()]),
            {"inserted": 0, "already_present": 1},
        )

    def test_new_candidates_remain_unverified_and_not_sales_verified(self):
        self.store.save_many([candidate()])
        record = self.store.get("abc")
        self.assertEqual(record["review_status"], "unverified")
        self.assertEqual(record["candidate"]["verification_status"], "unverified")
        self.assertFalse(record["candidate"]["sales_verified"])

    def test_owner_review_requires_note_and_is_one_way(self):
        self.store.save_many([candidate()])
        with self.assertRaises(ValueError):
            self.store.mark_owner_reviewed("abc", " ")
        reviewed = self.store.mark_owner_reviewed("abc", "Checked original publisher")
        self.assertEqual(reviewed["review_status"], "owner_reviewed")
        self.assertEqual(reviewed["review_note"], "Checked original publisher")
        self.assertFalse(reviewed["candidate"]["sales_verified"])
        with self.assertRaises(ValueError):
            self.store.mark_owner_reviewed("abc", "Second review")

    def test_unknown_candidate_and_invalid_filter_rejected(self):
        with self.assertRaises(ValueError):
            self.store.mark_owner_reviewed("missing", "Reviewed")
        with self.assertRaises(ValueError):
            self.store.list_candidates("approved")


if __name__ == "__main__":
    unittest.main()
