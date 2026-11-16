import unittest

from economy.opportunities import Evidence, EvidenceKind, Opportunity
from economy.business_pipeline import OpportunityToListingPipeline


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

    def test_pipeline_stops_for_owner_approval(self):
        result = OpportunityToListingPipeline().run(self.opportunity())
        self.assertEqual(result.status, "awaiting_owner_approval")
        self.assertIsNone(result.product)
        self.assertIsNone(result.listing)

    def test_pipeline_prepares_unpublished_listing_after_approval(self):
        result = OpportunityToListingPipeline().run(self.opportunity(), owner_approved=True)
        self.assertEqual(result.status, "listing_draft_ready")
        self.assertTrue(result.qa.passed)
        self.assertFalse(result.listing.published)
        self.assertFalse(result.listing.customer_contacted)

    def test_pipeline_blocks_insufficient_evidence(self):
        opportunity = self.opportunity()
        opportunity = Opportunity(opportunity.title, opportunity.buyer_segment,
                                  opportunity.problem, opportunity.proposed_solution,
                                  opportunity.delivery_format, opportunity.estimated_startup_cost_minor,
                                  legal_risk_notes=opportunity.legal_risk_notes)
        result = OpportunityToListingPipeline().run(opportunity, owner_approved=True)
        self.assertEqual(result.status, "blocked_research")
        self.assertIsNone(result.product)


if __name__ == "__main__":
    unittest.main()