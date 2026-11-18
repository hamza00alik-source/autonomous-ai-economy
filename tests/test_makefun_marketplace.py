import json
import unittest
from urllib.parse import urlparse

from economy.makefun_marketplace import MakeFunPublicBounties


class MakeFunMarketplaceTests(unittest.TestCase):
    def test_parses_current_makefun_api_schema_without_authorizing_entry(self):
        seen = {}
        payload = {"items": [
            {
                "slug": "roblox-brainrot-01", "title": "Build a Roblox game",
                "status": "open", "url": "/bounty/roblox-brainrot-01",
                "category": "Games", "rewardAmount": 1000,
                "rewards": {"1": 150, "2": 80, "3": 50},
                "entryFeeUsd": None, "entryFeesUsd": "0.00",
                "submissionCount": 22,
                "deadline": "2026-11-20T14:30:00.000Z",
                "escrowLifecycle": {"state": "open"},
                "description": "Build an original game."
            },
            {
                "slug": "paid-entry", "title": "Paid contest", "status": "open",
                "rewardAmount": 50, "rewards": {"1": 20},
                "entryFeeUsd": "0.50", "entryFeesUsd": "109.00",
                "submissionCount": 402, "escrowLock": {"status": "open"}
            },
            {"slug": "closed-task", "title": "Closed", "status": "closed"},
            {"title": "Malformed", "status": "open"},
        ]}
        def fetch(url, timeout):
            seen["url"] = url
            return json.dumps(payload).encode()

        rows = MakeFunPublicBounties(fetcher=fetch).search(limit=10)
        self.assertEqual(len(rows), 2)
        free = rows[0]
        self.assertEqual(free.reward_usdc, "1000")
        self.assertEqual(free.paid_places, 3)
        self.assertIsNone(free.entry_fee_usdc)
        self.assertEqual(free.submission_count, 22)
        self.assertEqual(free.escrow_status, "open")
        self.assertEqual(free.source_url, "https://make.fun/bounty/roblox-brainrot-01")
        self.assertFalse(free.payment_verified)
        self.assertFalse(free.entry_allowed)

        paid = rows[1]
        self.assertEqual(paid.entry_fee_usdc, "0.50")
        self.assertNotEqual(paid.entry_fee_usdc, "109.00")
        self.assertEqual(paid.escrow_status, "open")
        self.assertEqual(urlparse(seen["url"]).hostname, "make.fun")

    def test_rejects_invalid_limit(self):
        provider = MakeFunPublicBounties(fetcher=lambda *_: b'{"items":[]}')
        with self.assertRaises(ValueError):
            provider.search(limit=0)

    def test_rejects_oversized_response(self):
        provider = MakeFunPublicBounties(fetcher=lambda *_: b"x" * 1_000_001)
        with self.assertRaises(ValueError):
            provider.search()

    def test_rejects_untrusted_host(self):
        with self.assertRaises(ValueError):
            MakeFunPublicBounties()._fetcher("https://example.com/api/competitions", 1)


if __name__ == "__main__":
    unittest.main()
