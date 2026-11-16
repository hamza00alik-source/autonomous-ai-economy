import tempfile
import unittest
from pathlib import Path

from economy.shared_brain import SharedBrain, SharedBrainContext


class SharedBrainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.brain = SharedBrain(Path(self.temp.name) / "brain.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def test_agents_share_owner_approved_learning(self):
        researcher = SharedBrainContext(self.brain, "market-research")
        analyst = SharedBrainContext(self.brain, "opportunity-analyst")
        proposed = researcher.propose_learning(
            title="Marketplace fee lesson",
            lesson="Include listing and payment fees in unit economics before comparing margins.",
            category="cost_validation",
            tags=["fees", "pricing"],
            source_refs=["https://example.org/fee-policy"],
            confidence=0.8,
        )
        self.assertEqual(proposed["status"], "proposed")
        self.assertEqual(analyst.recall("marketplace fees pricing"), [])
        self.brain.review(proposed["memory_id"], decision="approved",
                          reviewer="owner", note="Checked against current fee schedule.")
        recalled = analyst.recall("marketplace fees pricing")
        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0]["created_by"], "market-research")
        self.assertEqual(recalled[0]["source_refs"], ["https://example.org/fee-policy"])

    def test_rejected_learning_is_not_used_in_normal_recall(self):
        entry = self.brain.propose(
            title="Unverified shortcut", lesson="Assume all products sell quickly.",
            category="claim", created_by="agent", confidence=0.1,
        )
        self.brain.review(entry["memory_id"], decision="rejected",
                          reviewer="owner", note="Unsupported claim.")
        self.assertEqual(self.brain.recall("products sell quickly"), [])
        self.assertEqual(self.brain.get(entry["memory_id"])["status"], "rejected")

    def test_review_is_required_and_decision_is_immutable(self):
        entry = self.brain.propose(title="Lesson", lesson="Keep source links.",
                                   category="research", created_by="agent")
        with self.assertRaises(ValueError):
            self.brain.review(entry["memory_id"], decision="approved",
                              reviewer="owner", note="")
        self.brain.review(entry["memory_id"], decision="approved",
                          reviewer="owner", note="Verified.")
        with self.assertRaises(ValueError):
            self.brain.review(entry["memory_id"], decision="rejected",
                              reviewer="owner", note="Change my mind.")
        self.assertEqual(len(self.brain.events(entry["memory_id"])), 2)

    def test_confidence_and_required_fields_are_validated(self):
        with self.assertRaises(ValueError):
            self.brain.propose(title="", lesson="x", category="x", created_by="agent")
        with self.assertRaises(ValueError):
            self.brain.propose(title="x", lesson="x", category="x",
                               created_by="agent", confidence=1.2)

    def test_recall_limit_is_bounded(self):
        with self.assertRaises(ValueError):
            self.brain.recall("lesson", limit=0)


if __name__ == "__main__":
    unittest.main()
