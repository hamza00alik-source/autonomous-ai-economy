import unittest

from economy.opportunities import Evidence, EvidenceKind, Opportunity
from economy.specialist_agents import (
    BusinessOperationsAgent, MarketResearchAgent, OpportunityAnalystAgent,
    ProductBuilderAgent, ProductDraft, QualityAssuranceAgent,
)


class SpecialistAgentTests(unittest.TestCase):
    def opportunity(self):
        return Opportunity(
            title="Practice planner",
            buyer_segment="Competitive players",
            problem="Need a structured practice routine",
            proposed_solution="A printable practice planner",
            delivery_format="PDF",
            estimated_startup_cost_minor=0,
            legal_risk_notes="No third-party trademarks or copied assets.",
        )

    def test_research_agent_only_reports_supplied_evidence(self):
        evidence = [Evidence("Buyer forum", "https://example.com/thread",
                             "2026-11-16", EvidenceKind.BUYER_SIGNAL,
                             "Several users requested a planner.")]
        brief = MarketResearchAgent().prepare_brief("Assess demand", evidence)
        self.assertFalse(brief.external_research_performed)
        self.assertEqual(len(brief.claims), 1)
        self.assertTrue(any("competitor" in gap for gap in brief.evidence_gaps))

    def test_analyst_never_turns_missing_evidence_into_approval(self):
        result = OpportunityAnalystAgent().analyze(self.opportunity())
        self.assertNotEqual(result.report.status.value, "owner_review")
        self.assertIn("Do not proceed", result.recommendation)

    def test_builder_requires_explicit_owner_approval(self):
        with self.assertRaises(PermissionError):
            ProductBuilderAgent().create_draft(self.opportunity(), owner_approved=False)

    def test_qa_and_listing_are_draft_only(self):
        product = ProductBuilderAgent().create_draft(
            self.opportunity(), owner_approved=True
        )
        qa = QualityAssuranceAgent().review(product)
        self.assertTrue(qa.passed)
        listing = BusinessOperationsAgent().prepare_listing(product, qa)
        self.assertEqual(listing.status, "draft")
        self.assertFalse(listing.published)
        self.assertFalse(listing.customer_contacted)

    def test_listing_blocked_when_qa_fails(self):
        product = ProductDraft("Bad", "buyers", "problem", "solution", "PDF",
                                (), (), status="draft")
        qa = QualityAssuranceAgent().review(product)
        self.assertFalse(qa.passed)
        with self.assertRaises(ValueError):
            BusinessOperationsAgent().prepare_listing(product, qa)


if __name__ == "__main__":
    unittest.main()
