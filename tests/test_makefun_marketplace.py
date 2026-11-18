import json
import unittest
from urllib.parse import urlparse

from economy.makefun_marketplace import MakeFunPublicBounties


class MakeFunMarketplaceTests(unittest.TestCase):
    def test_reads_open_competitions_without_auth_and_never_authorizes_entry(self):
        seen = {}
        payload = {"competitions": [
            {"slug": "small-code-task", "title": "Build a parser", "status": "open",
             "category": "Code", "reward_usdc": "25", "paid_places": 3,
             "entry_fee_usdc": "0", "deadline": "2026-12-01T00:00:00Z"},
            {"slug": "closed-task", "title": "Closed", "status": "closed"},
            {"title": "Malformed", "status": "open"},
        ]}
        def fetch(url, timeout):
            seen["url"] = url
            return json.dumps(payload).encode()
        rows = MakeFunPublicBounties(fetcher=fetch).search(limit=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].reward_usdc, "25")
        self.assertEqual(rows[0].paid_places, 3)
        self.assertEqual(rows[0].entry_fee_usdc, "0")
        self.assertFalse(rows[0].payment_verified)
        self.assertFalse(rows[0].entry_allowed)
        self.assertEqual(urlparse(seen["url"]).hostname, "make.fun")

    def test_rejects_invalid_limit(self):
        provider = MakeFunPublicBounties(fetcher=lambda *_: b'{"competitions":[]}')
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
