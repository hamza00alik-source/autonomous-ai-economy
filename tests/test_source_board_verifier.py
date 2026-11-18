import json
import unittest

from economy.source_board_verifier import GitHubSourceBoardVerifier


class SourceBoardVerifierTests(unittest.TestCase):
    def test_open_uncrowded_issue_is_verified_read_only(self):
        seen = {}
        def fetch(url, timeout):
            seen["url"] = url
            return json.dumps({
                "state": "open", "title": "Implement feature",
                "comments": 2, "updated_at": "2026-11-18T00:00:00Z",
            }).encode()
        result = GitHubSourceBoardVerifier(fetcher=fetch).verify(
            "https://github.com/acme/project/issues/42"
        )
        self.assertTrue(result.verified)
        self.assertEqual(result.state, "open")
        self.assertEqual(result.comments, 2)
        self.assertEqual(result.reasons, ())
        self.assertIn("/repos/acme/project/issues/42", seen["url"])

    def test_closed_and_merged_items_are_flagged(self):
        def fetch(url, timeout):
            return json.dumps({
                "state": "closed", "title": "Already done", "comments": 20,
                "pull_request": {"merged": True},
            }).encode()
        result = GitHubSourceBoardVerifier(fetcher=fetch).verify(
            "https://github.com/acme/project/pull/9"
        )
        self.assertTrue(result.verified)
        self.assertTrue(result.merged)
        self.assertIn("source_item_not_open", result.reasons)
        self.assertIn("source_pull_request_already_merged", result.reasons)
        self.assertIn("source_competition_high", result.reasons)

    def test_non_github_and_non_issue_urls_are_not_fetched(self):
        def forbidden(*args):
            raise AssertionError("fetch must not run")
        verifier = GitHubSourceBoardVerifier(fetcher=forbidden)
        for url in (
            "https://evil.example/acme/project/issues/1",
            "https://github.com/acme/project/discussions/1",
            "http://github.com/acme/project/issues/1",
        ):
            result = verifier.verify(url)
            self.assertFalse(result.supported)
            self.assertFalse(result.verified)

    def test_api_failure_never_becomes_verified(self):
        verifier = GitHubSourceBoardVerifier(fetcher=lambda *_: (_ for _ in ()).throw(TimeoutError()))
        result = verifier.verify("https://github.com/acme/project/issues/3")
        self.assertFalse(result.verified)
        self.assertEqual(result.state, "unverified")
        self.assertEqual(result.reasons, ("source_fetch_failed:TimeoutError",))


if __name__ == "__main__":
    unittest.main()
