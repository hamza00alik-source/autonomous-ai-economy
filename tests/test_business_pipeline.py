import tempfile
import unittest
from pathlib import Path

from economy.approvals import OwnerApprovalStore, create_approval_token
from economy.opportunities import Evidence, EvidenceKind, Opportunity
from economy.business_pipeline import OpportunityToListingPipeline
from economy.shared_brain import SharedBrain


class BusinessPipelineTests(unittest.TestCase):
    def opportunity(self):
        evidence = (
            Evidence("Buyers", "https://example.com/buyers", "2026-11-16", EvidenceKind.BUYER_SIGNAL, "Buyer requests observed."),
            Evidence("Competitors", "https://example.org/competitors", "2026-11-16", EvidenceKind.COMPETITOR, "Comparable products listed."),
            Evidence("Fees", "https://example.net/fees", "2026-11-16", EvidenceKind.COST, "Fees reviewed."),
            Evidence("Policy", "https://example.edu/policy", "2026-11-16", EvidenceKind.LEGAL_OR_POLICY, "Rules reviewed."),
        )
        return Opportunity("Planner", "Competitive players", "Practice planning is difficult",
                           "A structured practice planner", "PDF", 0,
                           legal_risk_notes="No third-party IP used.", evidence=evidence)

    def test_pipeline_stops_without_authenticated_owner_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            pipeline = OpportunityToListingPipeline(OwnerApprovalStore(Path(directory) / "approvals.sqlite3"))
            result = pipeline.run(self.opportunity())
            self.assertEqual(result.status, "awaiting_owner_approval")
            self.assertIsNone(result.product)
            self.assertIsNone(result.listing)

    def test_pipeline_prepares_unpublished_listing_after_signed_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            opportunity = self.opportunity()
            secret = "local-test-secret-" + ("x" * 40)
            store = OwnerApprovalStore(Path(directory) / "approvals.sqlite3")
            token = create_approval_token(opportunity, secret)
            result = OpportunityToListingPipeline(store).run(
                opportunity, approval_token=token, approval_secret=secret
            )
            self.assertEqual(result.status, "listing_draft_ready")
            self.assertTrue(result.qa.passed)
            self.assertFalse(result.listing.published)
            self.assertFalse(result.listing.customer_contacted)

    def test_pipeline_rejects_replayed_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            opportunity = self.opportunity()
            secret = "local-test-secret-" + ("x" * 40)
            store = OwnerApprovalStore(Path(directory) / "approvals.sqlite3")
            token = create_approval_token(opportunity, secret)
            pipeline = OpportunityToListingPipeline(store)
            self.assertEqual(pipeline.run(opportunity, approval_token=token, approval_secret=secret).status,
                             "listing_draft_ready")
            replay = pipeline.run(opportunity, approval_token=token, approval_secret=secret)
            self.assertEqual(replay.status, "awaiting_owner_approval")
            self.assertIn("already been used", replay.blockers[0])

    def test_pipeline_agents_recall_the_same_owner_approved_team_lesson(self):
        with tempfile.TemporaryDirectory() as directory:
            brain = SharedBrain(Path(directory) / "brain.sqlite3")
            memory = brain.propose(
                title="Evidence provenance",
                lesson="Preserve original source links when assessing buyer demand.",
                category="research_quality", created_by="market-research",
                tags=["buyer", "demand", "evidence"],
                source_refs=["https://example.com/research"], confidence=0.9,
            )
            brain.review(memory["memory_id"], decision="approved",
                         reviewer="owner", note="Source checked.")
            result = OpportunityToListingPipeline(
                OwnerApprovalStore(Path(directory) / "approvals.sqlite3"),
                shared_brain=brain,
            ).run(self.opportunity())
            self.assertTrue(result.research.relevant_lessons)
            self.assertTrue(result.analysis.relevant_lessons)
            self.assertEqual(result.research.relevant_lessons[0]["memory_id"], memory["memory_id"])
            self.assertEqual(result.analysis.relevant_lessons[0]["memory_id"], memory["memory_id"])

    def test_pipeline_blocks_insufficient_evidence(self):
        opportunity = self.opportunity()
        opportunity = Opportunity(opportunity.title, opportunity.buyer_segment,
                                  opportunity.problem, opportunity.proposed_solution,
                                  opportunity.delivery_format, opportunity.estimated_startup_cost_minor,
                                  legal_risk_notes=opportunity.legal_risk_notes)
        with tempfile.TemporaryDirectory() as directory:
            result = OpportunityToListingPipeline(OwnerApprovalStore(Path(directory) / "approvals.sqlite3")).run(
                opportunity, approval_token="irrelevant", approval_secret="x" * 48
            )
        self.assertEqual(result.status, "blocked_research")
        self.assertIsNone(result.product)


if __name__ == "__main__":
    unittest.main()
