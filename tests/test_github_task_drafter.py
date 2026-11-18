import json
import tempfile
import unittest
from pathlib import Path

from economy.github_task_drafter import GitHubTaskDraftBuilder


class GitHubTaskDraftBuilderTests(unittest.TestCase):
    def test_open_issue_with_clear_scope_builds_local_only_packet(self):
        payload = {
            "state": "open",
            "title": "Implement CSV export",
            "comments": 2,
            "updated_at": "2026-11-18T00:00:00Z",
            "body": (
                "Please implement CSV export for the report screen.\n"
                "Deliverable: provide a tested implementation and a pull request.\n"
                "Acceptance criteria: exported rows match the visible report and include headers."
            ),
        }
        calls = []
        def fetch(url, timeout):
            calls.append(url)
            return json.dumps(payload).encode()

        builder = GitHubTaskDraftBuilder(fetcher=fetch)
        packet = builder.prepare("https://github.com/acme/project/issues/42")
        self.assertEqual(packet["status"], "ready_for_human_review")
        self.assertTrue(packet["draft_only"])
        self.assertFalse(packet["claim_allowed"])
        self.assertFalse(packet["submission_allowed"])
        self.assertEqual(packet["external_actions"], 0)
        self.assertTrue(packet["detected_acceptance_lines"])
        self.assertEqual(len(calls), 2)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "packet.json"
            builder.save_new(packet, path)
            saved = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "ready_for_human_review")
            with self.assertRaises(FileExistsError):
                builder.save_new(packet, path)

    def test_open_pull_request_can_be_prepared_but_never_submitted(self):
        payload = {
            "state": "open", "title": "Add API docs", "comments": 0,
            "updated_at": "2026-11-18T00:00:00Z",
            "pull_request": {"url": "https://api.github.com/repos/acme/project/pulls/5"},
            "body": "Deliverable: update the API documentation.\n"
                    "Acceptance criteria: all public endpoints have examples.",
        }
        builder = GitHubTaskDraftBuilder(fetcher=lambda *_: json.dumps(payload).encode())
        packet = builder.prepare("https://github.com/acme/project/pull/5")
        self.assertEqual(packet["status"], "ready_for_human_review")
        self.assertFalse(packet["submission_allowed"])

    def test_closed_or_crowded_sources_are_blocked_before_detail_fetch(self):
        payload = {"state": "closed", "title": "Done", "comments": 20}
        calls = []
        def fetch(url, timeout):
            calls.append(url)
            return json.dumps(payload).encode()
        packet = GitHubTaskDraftBuilder(fetcher=fetch).prepare(
            "https://github.com/acme/project/issues/4"
        )
        self.assertEqual(packet["status"], "blocked_source_not_open")
        self.assertEqual(len(calls), 1)
        self.assertFalse(packet["claim_allowed"])

    def test_missing_acceptance_criteria_remains_manual_review(self):
        payload = {
            "state": "open", "title": "Add a small feature", "comments": 1,
            "body": "Please implement this feature and provide a pull request with tests.",
        }
        packet = GitHubTaskDraftBuilder(
            fetcher=lambda *_: json.dumps(payload).encode()
        ).prepare("https://github.com/acme/project/issues/7")
        self.assertEqual(packet["status"], "needs_review")
        self.assertIn("explicit_acceptance_criteria_not_found", packet["blockers"])


if __name__ == "__main__":
    unittest.main()
