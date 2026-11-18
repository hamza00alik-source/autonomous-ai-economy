import json
from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlparse

from economy.jobbi_gigs import JobbiGigEvaluator, JobbiGigStore, JobbiPublicGigs


def item(gig_id="algora:repo#1", **meta):
    fields = {
        "source": "algora", "source_name": "Algora", "lane": "agent",
        "reward": {"amount": 10, "currency": "USD", "rail": "stripe"},
        "payment_state": "escrowed", "payout_grade": "B",
        "acceptance": "Maintainer merges PR", "acceptance_type": "human-review",
        "claims_open": True, "extra": {"comments": 0},
    }
    fields.update(meta)
    return {"id": gig_id, "title": "Add feature", "url": "https://github.com/org/repo/issues/1",
            "content_text": "Implement a feature", "date_published": "2026-11-17T00:00:00Z",
            "date_modified": "2026-11-17T00:00:00Z", "tags": ["code"], "_jobbi": fields}


class JobbiGigsTests(unittest.TestCase):
    def test_reads_agent_lane_and_preserves_payment_metadata_as_unverified(self):
        seen = {}
        feed = {"items": [
            item(),
            item("human:1", lane="human"),
            {"id": "bad", "title": "Bad", "url": "javascript:alert(1)", "_jobbi": {"lane": "agent"}},
        ]}
        def fetch(url, timeout):
            seen["url"] = url
            return json.dumps(feed).encode()
        gigs = JobbiPublicGigs(fetcher=fetch).search(limit=10)
        self.assertEqual(len(gigs), 1)
        self.assertEqual(gigs[0].payment_state, "escrowed")
        self.assertFalse(gigs[0].payment_verified)
        self.assertEqual(urlparse(seen["url"]).hostname, "jobbi.org")

    def test_rejects_invalid_limit_and_untrusted_host(self):
        provider = JobbiPublicGigs(fetcher=lambda *_: b'{"items":[]}')
        with self.assertRaises(ValueError):
            provider.search(limit=0)
        with self.assertRaises(ValueError):
            JobbiPublicGigs._fetch("https://evil.example/feed", 1)

    def test_evaluator_rejects_stale_crowded_and_outreach_bounties(self):
        feed = {"items": [
            item("stale:1", date_published="2023-01-01T00:00:00Z"),
            item("crowded:2", extra={"comments": 34}),
            item("outreach:3", content_text="Contact the organizer to confirm details."),
        ]}
        gigs = JobbiPublicGigs(fetcher=lambda *_: json.dumps(feed).encode()).search()
        evaluator = JobbiGigEvaluator(now=datetime(2026, 11, 18, tzinfo=timezone.utc))
        results = {gig.gig_id: evaluator.evaluate(gig) for gig in gigs}
        self.assertIn("listing_stale", results["stale:1"]["reasons"])
        self.assertIn("high_competition", results["crowded:2"]["reasons"])
        self.assertIn("outreach_or_promotion_required", results["outreach:3"]["reasons"])

    def test_store_shortlists_escrowed_and_promised_usd_gigs_without_claiming(self):
        gigs = JobbiPublicGigs(fetcher=lambda *_: json.dumps({"items": [
            item(),
            item("bountybook:2", source="bountybook", reward={"amount": 5, "currency": "USDC", "rail": "x402"},
                 payment_state="promised", payout_grade="C-"),
            item("token:3", reward={"amount": 25000, "currency": "TOKEN", "rail": "token"}),
            item("closed:4", claims_open=False),
            item("zero:5", reward={"amount": 0, "currency": "USDC", "rail": "x402"}),
        ]}).encode()).search()
        with tempfile.TemporaryDirectory() as tmp:
            store = JobbiGigStore(Path(tmp) / "gigs.sqlite3")
            summary = store.save_many(gigs, JobbiGigEvaluator(
                now=datetime(2026, 11, 18, tzinfo=timezone.utc),
            ))
            rows = store.list_review_required()
        self.assertEqual(summary["saved"], 5)
        self.assertEqual(summary["review_required"], 1)
        self.assertEqual(summary["claims"], 0)
        self.assertEqual(summary["payments"], 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["payment_state"], "escrowed")
        self.assertEqual(rows[0]["evaluation"]["state"], "qualified_for_local_draft")


if __name__ == "__main__":
    unittest.main()
