import unittest

from economy.economics import UnitEconomics
from economy.opportunities import Evidence, EvidenceKind, Opportunity
from economy.opportunity_ranker import rank_readiness
from economy.research_engine import ResearchDiscoveryEngine
from economy.research_sources import ResearchCandidate


class FakeProvider:
    def __init__(self):
        self.calls = []

    def search(self, query, *, limit):
        self.calls.append((query, limit))
        return [
            ResearchCandidate("query-specific-id", query, "Headline", "https://publisher.example/story",
                              "Publisher", "", "2026-11-16T00:00:00+00:00")
        ]


class ResearchEngineTests(unittest.TestCase):
    def test_multi_query_deduplicates_by_original_url(self):
        provider = FakeProvider()
        results = ResearchDiscoveryEngine(provider).discover([" alpha ", "beta", "alpha"], limit_per_query=4)
        self.assertEqual(len(results), 1)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(results[0].query, "alpha")
        self.assertEqual(len(results[0].candidate_id), 20)
        self.assertFalse(results[0].sales_verified)

    def test_empty_or_excessive_queries_rejected(self):
        engine = ResearchDiscoveryEngine(FakeProvider())
        with self.assertRaises(ValueError):
            engine.discover([" ", ""])
        with self.assertRaises(ValueError):
            engine.discover([str(i) for i in range(11)])


class EconomicsTests(unittest.TestCase):
    def test_calculates_profit_fees_and_break_even(self):
        result = UnitEconomics(
            price_minor=1000, variable_cost_minor=100, fixed_setup_cost_minor=500,
            platform_fee_bps=1000, payment_fee_bps=300, fixed_fee_per_sale_minor=20,
        ).calculate(units=3)
        self.assertEqual(result["gross_revenue_minor"], 3000)
        self.assertEqual(result["estimated_platform_and_payment_fees_minor"], 390)
        self.assertEqual(result["estimated_net_profit_minor"], 1750)
        self.assertEqual(result["break_even_units"], 1)

    def test_non_profitable_unit_has_no_break_even(self):
        result = UnitEconomics(price_minor=100, variable_cost_minor=200).calculate()
        self.assertIsNone(result["break_even_units"])
        self.assertFalse(result["profitable_per_unit_before_setup"])

    def test_invalid_inputs_rejected(self):
        with self.assertRaises(ValueError):
            UnitEconomics(price_minor=0, variable_cost_minor=0).calculate()
        with self.assertRaises(ValueError):
            UnitEconomics(price_minor=100, variable_cost_minor=0, platform_fee_bps=10001).calculate()


class ReadinessRankerTests(unittest.TestCase):
    def opportunity(self, title, evidence):
        return Opportunity(title, "buyers", "problem", "solution", "download",
                           0, legal_risk_notes="Review required", evidence=tuple(evidence))

    def test_ranks_documentation_completeness_not_sales(self):
        complete = [
            Evidence("Buyer forum", "https://a.example/1", "2026-11-16", EvidenceKind.BUYER_SIGNAL, "Asked for solution"),
            Evidence("Competitor", "https://b.example/2", "2026-11-16", EvidenceKind.COMPETITOR, "Comparable offer"),
            Evidence("Fee schedule", "https://c.example/3", "2026-11-16", EvidenceKind.COST, "Fee"),
            Evidence("Policy", "https://d.example/4", "2026-11-16", EvidenceKind.LEGAL_OR_POLICY, "Policy"),
        ]
        ranked = rank_readiness([
            self.opportunity("Weak", []),
            self.opportunity("Documented", complete),
        ])
        self.assertEqual(ranked[0].title, "Documented")
        self.assertEqual(ranked[0].score, 95)
        self.assertEqual(ranked[0].label, "evidence_readiness_only")
        self.assertIn("does not estimate demand", ranked[0].to_dict()["warning"])


if __name__ == "__main__":
    unittest.main()
