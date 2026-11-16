import tempfile
import unittest
from pathlib import Path

from economy.collective_learning import CollectiveLearningEngine
from economy.shared_brain import SharedBrain


class CollectiveLearningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.brain = SharedBrain(root / "brain.sqlite3")
        self.engine = CollectiveLearningEngine(root / "outcomes.sqlite3", self.brain)

    def tearDown(self):
        self.temp.cleanup()

    def test_repeated_outcomes_create_one_unapproved_shared_proposal(self):
        first = self.engine.record_outcome(
            pattern_key="listing-fee-check",
            outcome_label="worked",
            observation="Checking current fee schedule prevented underpricing.",
            observed_by="business-operations",
            evidence_refs=["https://example.org/fees"],
        )
        self.assertIsNone(first["learning_proposal"])
        second = self.engine.record_outcome(
            pattern_key="listing-fee-check",
            outcome_label="worked",
            observation="A second listing estimate included the marketplace fee.",
            observed_by="opportunity-analyst",
            evidence_refs=["https://example.org/fees-archive"],
        )
        proposal = second["learning_proposal"]
        self.assertEqual(proposal["status"], "proposed")
        self.assertEqual(proposal["created_by"], "collective-learning-engine")
        self.assertEqual(len(proposal["source_refs"]), 2)
        self.assertEqual(self.brain.recall("listing fee pricing"), [])
        again = self.engine.record_outcome(
            pattern_key="listing-fee-check",
            outcome_label="worked",
            observation="Third observed case.",
            observed_by="market-research",
            evidence_refs=["https://example.org/fees-third"],
        )
        self.assertEqual(again["learning_proposal"]["memory_id"], proposal["memory_id"])

    def test_owner_approval_makes_proposal_retrievable_by_all_agents(self):
        for note in ("First observed result.", "Second observed result."):
            result = self.engine.record_outcome(
                pattern_key="quality-review",
                outcome_label="failed",
                observation=note,
                observed_by="quality-assurance",
                evidence_refs=["https://example.org/qa"],
            )
        proposal = result["learning_proposal"]
        self.brain.review(proposal["memory_id"], decision="approved",
                          reviewer="owner", note="Reviewed both QA records.")
        self.assertEqual(len(self.brain.recall("quality review failed")), 1)

    def test_mixed_outcomes_do_not_merge_into_a_single_lesson(self):
        for label in ("worked", "failed"):
            result = self.engine.record_outcome(
                pattern_key="mixed-pattern",
                outcome_label=label,
                observation=f"Observed {label}.",
                observed_by="agent",
                evidence_refs=["https://example.org/case"],
            )
            self.assertIsNone(result["learning_proposal"])

    def test_rejects_missing_evidence_and_invalid_outcome(self):
        with self.assertRaises(ValueError):
            self.engine.record_outcome(
                pattern_key="x", outcome_label="worked", observation="Observed.",
                observed_by="agent", evidence_refs=[],
            )
        with self.assertRaises(ValueError):
            self.engine.record_outcome(
                pattern_key="x", outcome_label="predicted", observation="Observed.",
                observed_by="agent", evidence_refs=["https://example.org"],
            )

    def test_summary_reports_observations_and_emissions(self):
        for _ in range(2):
            self.engine.record_outcome(
                pattern_key="repeat", outcome_label="worked", observation="Same.",
                observed_by="agent", evidence_refs=["https://example.org"],
            )
        summary = self.engine.summarize()
        self.assertEqual(summary["observations_recorded"], 2)
        self.assertEqual(summary["learning_proposals_emitted"], 1)
        self.assertFalse(summary["automatic_approval"])


if __name__ == "__main__":
    unittest.main()
