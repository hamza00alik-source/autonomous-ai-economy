import unittest

from economy.opportunities import (
    Evidence, EvidenceKind, Opportunity, OpportunityValidator, ValidationStatus,
)
from economy.opportunity_workflow import OpportunityWorkflow


class OpportunityTests(unittest.TestCase):
    def make_opportunity(self, evidence=()):
        return Opportunity(
            title="Downloadable practice planner",
            buyer_segment="Independent competitive gamers",
            problem="Players may struggle to structure practice",
            proposed_solution="A printable and editable practice planner",
            delivery_format="PDF and spreadsheet",
            estimated_startup_cost_minor=0,
            legal_risk_notes="Avoid game logos, copied assets, and unsupported performance claims.",
            evidence=tuple(evidence),
        )

    def test_empty_evidence_is_not_validated(self):
        report = OpportunityValidator().evaluate(self.make_opportunity())
        self.assertEqual(report.status, ValidationStatus.INSUFFICIENT_EVIDENCE)
        self.assertFalse(report.can_publish)
        self.assertFalse(report.can_spend)

    def test_invalid_evidence_url_is_blocked(self):
        evidence = Evidence("Market page", "not-a-url", "2026-11-16",
                            EvidenceKind.BUYER_SIGNAL, "Example listing")
        report = OpportunityValidator().evaluate(self.make_opportunity([evidence]))
        self.assertTrue(any("absolute http(s)" in item for item in report.blockers))
        self.assertEqual(report.status, ValidationStatus.NEEDS_RESEARCH)

    def test_complete_evidence_only_reaches_owner_review(self):
        evidence = [
            Evidence("Marketplace listing", "https://example.com/listing", "2026-11-16",
                     EvidenceKind.BUYER_SIGNAL, "Visible paid listing; sales count not verified."),
            Evidence("Competitor catalog", "https://example.org/catalog", "2026-11-16",
                     EvidenceKind.COMPETITOR, "Comparable products listed."),
            Evidence("Fee schedule", "https://example.net/fees", "2026-11-16",
                     EvidenceKind.COST, "Platform fee schedule reviewed."),
            Evidence("Platform policy", "https://example.edu/policy", "2026-11-16",
                     EvidenceKind.LEGAL_OR_POLICY, "Relevant prohibited-item rules reviewed."),
        ]
        assessment = OpportunityWorkflow().assess(self.make_opportunity(evidence))
        self.assertEqual(assessment.report.status, ValidationStatus.OWNER_REVIEW)
        self.assertTrue(assessment.report.owner_approval_required)
        self.assertFalse(assessment.report.can_publish)
        self.assertFalse(assessment.report.can_spend)

    def test_duplicate_urls_are_counted_once(self):
        evidence = [
            Evidence("Source A", "https://example.com/a", "2026-11-16",
                     EvidenceKind.BUYER_SIGNAL, "Signal"),
            Evidence("Source B", "https://example.com/a", "2026-11-16",
                     EvidenceKind.COMPETITOR, "Competitor"),
            Evidence("Cost", "https://example.net/cost", "2026-11-16",
                     EvidenceKind.COST, "Fee"),
            Evidence("Policy", "https://example.org/policy", "2026-11-16",
                     EvidenceKind.LEGAL_OR_POLICY, "Rules"),
        ]
        report = OpportunityValidator().evaluate(self.make_opportunity(evidence))
        self.assertEqual(report.independent_source_count, 3)
        self.assertEqual(report.status, ValidationStatus.OWNER_REVIEW)


if __name__ == "__main__":
    unittest.main()
