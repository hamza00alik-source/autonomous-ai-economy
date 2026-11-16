import tempfile
import unittest
from pathlib import Path

from economy.approvals import OwnerApprovalStore, create_approval_token
from economy.opportunities import Evidence, EvidenceKind, Opportunity


class OwnerApprovalTests(unittest.TestCase):
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

    def test_token_is_bound_to_exact_opportunity(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OwnerApprovalStore(Path(directory) / "approvals.sqlite3")
            secret = "x" * 48
            token = create_approval_token(self.opportunity(), secret)
            changed = Opportunity("Different", "Competitive players", "Practice planning is difficult",
                                  "A structured practice planner", "PDF", 0,
                                  legal_risk_notes="No third-party IP used.",
                                  evidence=self.opportunity().evidence)
            ok, message = store.consume(token, changed, secret)
            self.assertFalse(ok)
            self.assertIn("does not match", message)

    def test_token_is_single_use(self):
        with tempfile.TemporaryDirectory() as directory:
            store = OwnerApprovalStore(Path(directory) / "approvals.sqlite3")
            secret = "x" * 48
            token = create_approval_token(self.opportunity(), secret)
            self.assertTrue(store.consume(token, self.opportunity(), secret)[0])
            ok, message = store.consume(token, self.opportunity(), secret)
            self.assertFalse(ok)
            self.assertIn("already been used", message)

    def test_invalid_secret_and_short_secret_are_rejected(self):
        with self.assertRaises(ValueError):
            create_approval_token(self.opportunity(), "short")
        with tempfile.TemporaryDirectory() as directory:
            store = OwnerApprovalStore(Path(directory) / "approvals.sqlite3")
            token = create_approval_token(self.opportunity(), "x" * 48)
            self.assertFalse(store.consume(token, self.opportunity(), "y" * 48)[0])


if __name__ == "__main__":
    unittest.main()
