import tempfile
import unittest
from pathlib import Path

from economy.source_dossier import build_source_dossier
from economy.source_review import SourceReviewStore


class SourceDossierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SourceReviewStore(Path(self.temp.name) / "research.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def add(self, url, digest, classification, finding):
        return self.store.record_review({
            "url": url,
            "final_url": url,
            "fetched_at": "2026-11-16T12:00:00+00:00",
            "content_sha256": digest * 64,
            "verification_status": "retrieved_unverified",
            "buyer_evidence_created": False,
            "extracted_text": "Untrusted source snapshot",
        }, classification=classification, finding=finding, reviewer_note="Owner read the source and recorded context.")

    def build(self):
        return build_source_dossier(
            self.store,
            title="Invoice workflow helper",
            buyer_segment="Small business operators",
            problem="Invoice tracking is fragmented",
            proposed_solution="A downloadable invoice tracker",
            delivery_format="Spreadsheet",
            estimated_startup_cost_minor=0,
            currency="USD",
            legal_risk_notes="Marketplace and tax requirements still need review.",
        )

    def test_compiles_reviewed_sources_with_provenance_but_never_independent(self):
        self.add("https://buyers.example/problem", "a", "supports_buyer_problem", "Operators report repeated invoice follow-up work.")
        self.add("https://vendor.example/offer", "b", "competitor_offer", "Vendor sells an invoice tracker.")
        dossier = self.build()
        self.assertEqual(dossier["dossier_type"], "owner_reviewed_research_draft")
        self.assertEqual(len(dossier["source_reviews"]), 2)
        self.assertEqual(len(dossier["opportunity"]["evidence"]), 2)
        self.assertTrue(all(not e["independent_source"] for e in dossier["opportunity"]["evidence"]))
        self.assertEqual(dossier["opportunity"]["evidence"][0]["observed_on"], "2026-11-16")
        self.assertFalse(dossier["readiness"]["real_buyer_demand_verified"])
        self.assertFalse(dossier["readiness"]["can_publish"])
        self.assertFalse(dossier["readiness"]["can_spend"])

    def test_unreliable_and_irrelevant_sources_are_excluded_but_audited(self):
        self.add("https://noise.example/a", "c", "unreliable", "Unsubstantiated claim.")
        self.add("https://noise.example/b", "d", "not_relevant", "Unrelated topic.")
        dossier = self.build()
        self.assertEqual(dossier["source_reviews"], [])
        self.assertEqual(len(dossier["excluded_source_reviews"]), 2)
        self.assertEqual(dossier["opportunity"]["evidence"], [])

    def test_draft_cannot_pass_independent_evidence_gate(self):
        self.add("https://buyer.example/a", "e", "supports_buyer_problem", "A buyer reports a problem.")
        self.add("https://cost.example/b", "f", "cost_reference", "A published price is listed.")
        dossier = self.build()
        self.assertNotEqual(dossier["validation"]["status"], "owner_review")
        self.assertTrue(any("missing independent buyer evidence" in b for b in dossier["validation"]["blockers"]))
        self.assertTrue(all(not e["independent_source"] for e in dossier["opportunity"]["evidence"]))


if __name__ == "__main__":
    unittest.main()
