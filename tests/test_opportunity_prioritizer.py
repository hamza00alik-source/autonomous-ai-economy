import unittest

from economy.opportunity_prioritizer import prioritize_opportunities


def item(title, assessment, validation=None):
    return {
        "dossier": {
            "opportunity": {"title": title},
            "validation": validation or {"status": "needs_research", "blockers": ["buyer evidence missing"]},
        },
        "assessment": assessment,
    }


class OpportunityPrioritizerTests(unittest.TestCase):
    def test_ranks_using_owner_supplied_operational_inputs(self):
        results = prioritize_opportunities([
            item("Complex service", {
                "currency": "USD", "startup_cost_minor": 5000, "ongoing_cost_minor": 2000,
                "hours_to_first_delivery": 20, "delivery_complexity": 5,
                "fulfillment_burden": 5, "legal_policy_status": "review_needed",
            }),
            item("Simple download", {
                "currency": "USD", "startup_cost_minor": 1000, "ongoing_cost_minor": 100,
                "hours_to_first_delivery": 2, "delivery_complexity": 1,
                "fulfillment_burden": 1, "legal_policy_status": "owner_reviewed_no_blocker",
            }),
        ])
        self.assertEqual(results[0]["title"], "Simple download")
        self.assertEqual(results[0]["operational_fit_score"], 20)
        self.assertEqual(results[0]["score_label"], "relative_operational_fit_from_owner_inputs")
        self.assertFalse(results[0]["can_publish"])
        self.assertFalse(results[0]["can_spend"])
        self.assertFalse(results[0]["sales_verified"])
        self.assertFalse(results[0]["profitability_verified"])

    def test_unknowns_remain_unknown_and_are_reported(self):
        result = prioritize_opportunities([item("Incomplete", {
            "startup_cost_minor": 0,
        })])[0]
        self.assertIsNone(result["owner_inputs"]["ongoing_cost_minor"])
        self.assertIn("ongoing_cost_minor", result["missing_information"])
        self.assertIn("hours_to_first_delivery", result["missing_information"])
        self.assertEqual(result["assessment_completeness"], 17)
        self.assertEqual(result["research_validation_status"], "needs_research")

    def test_costs_and_time_are_compared_only_within_currency(self):
        results = prioritize_opportunities([
            item("USD", {"currency": "USD", "startup_cost_minor": 100, "ongoing_cost_minor": 10}),
            item("EUR", {"currency": "EUR", "startup_cost_minor": 1, "ongoing_cost_minor": 1}),
        ])
        by_title = {r["title"]: r for r in results}
        self.assertEqual(by_title["USD"]["score_components"]["cost"], 20)
        self.assertEqual(by_title["EUR"]["score_components"]["cost"], 20)

    def test_rejects_invalid_assessment_values(self):
        with self.assertRaises(ValueError):
            prioritize_opportunities([item("Bad", {"startup_cost_minor": -1})])
        with self.assertRaises(ValueError):
            prioritize_opportunities([item("Bad", {"startup_cost_minor": 0, "delivery_complexity": 6})])
        with self.assertRaises(ValueError):
            prioritize_opportunities([item("Bad", {"startup_cost_minor": 0, "legal_policy_status": "legal_ok"})])


if __name__ == "__main__":
    unittest.main()
