"""Prepare local-only GitHub task packets after read-only source verification.

This creates a structured working brief, not a completed deliverable or a claim.
It never comments, claims, submits, opens a PR, or contacts a requester.
"""
from __future__ import annotations

from pathlib import Path
import json
import re
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .source_board_verifier import GitHubSourceBoardVerifier

MAX_BYTES = 1_000_000
ACCEPTANCE_TERMS = re.compile(
    r"acceptance criteria|must include|must contain|definition of done|"
    r"expected behavior|requirements:|deliverable:|submission requirements",
    re.IGNORECASE,
)
DELIVERABLE_TERMS = re.compile(
    r"deliverable|submit|provide|implement|create|build|fix|document|report|"
    r"pull request|reproduction|test case",
    re.IGNORECASE,
)


class GitHubTaskDraftBuilder:
    """Build a reviewable local packet from a live, open GitHub issue or PR."""

    def __init__(self, *, timeout_seconds: float = 10, fetcher=None):
        if not 1 <= timeout_seconds <= 20:
            raise ValueError("timeout_seconds must be between 1 and 20")
        self.timeout = timeout_seconds
        self.fetcher = fetcher or self._fetch
        self.verifier = GitHubSourceBoardVerifier(
            timeout_seconds=timeout_seconds, fetcher=self.fetcher
        )

    @staticmethod
    def _fetch(url: str, timeout: float) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "api.github.com":
            raise ValueError("only HTTPS api.github.com is allowed")
        request = Request(url, headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AutonomousAIEconomy-local-task-drafter",
        })
        with urlopen(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != "api.github.com":
                raise ValueError("GitHub API response host rejected")
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("GitHub issue response exceeds size limit")
        return body

    @staticmethod
    def _api_url(source_url: str) -> str | None:
        endpoint = GitHubSourceBoardVerifier._endpoint(source_url)
        return endpoint[0] if endpoint else None

    @staticmethod
    def _lines(value: str) -> list[str]:
        return [line.strip(" -*\t") for line in value.splitlines() if line.strip()]

    def prepare(self, source_url: str) -> dict:
        verification = self.verifier.verify(source_url)
        base = {
            "source_url": source_url,
            "source_verification": verification.to_dict(),
            "draft_only": True,
            "external_actions": 0,
            "claim_allowed": False,
            "submission_allowed": False,
            "payment_verified": False,
        }
        if not verification.verified:
            return {**base, "status": "blocked_unverified_source",
                    "blockers": list(verification.reasons)}
        if verification.state not in {"open", "open_pull_request"} or verification.merged:
            return {**base, "status": "blocked_source_not_open",
                    "blockers": list(verification.reasons)}
        if verification.comments is None or verification.comments > 10:
            return {**base, "status": "needs_review_competition",
                    "blockers": list(verification.reasons or ("competition_unknown_or_high",))}

        api_url = self._api_url(source_url)
        if not api_url:
            return {**base, "status": "blocked_unsupported_source",
                    "blockers": ["unsupported_source_url"]}
        try:
            detail = json.loads(self.fetcher(api_url, self.timeout))
        except Exception as exc:
            return {**base, "status": "blocked_detail_fetch",
                    "blockers": [f"detail_fetch_failed:{type(exc).__name__}"]}
        if not isinstance(detail, dict) or not isinstance(detail.get("body"), (str, type(None))):
            return {**base, "status": "blocked_invalid_detail",
                    "blockers": ["unexpected_github_detail_schema"]}

        title = str(detail.get("title") or verification.title or "")[:300]
        body = str(detail.get("body") or "")[:20000]
        lines = self._lines(body)
        acceptance = [line[:500] for line in lines if ACCEPTANCE_TERMS.search(line)]
        deliverables = [line[:500] for line in lines if DELIVERABLE_TERMS.search(line)]
        blockers = []
        if not title:
            blockers.append("missing_task_title")
        if len(body.strip()) < 40:
            blockers.append("task_description_too_short")
        if not acceptance:
            blockers.append("explicit_acceptance_criteria_not_found")
        if not deliverables:
            blockers.append("explicit_deliverable_not_found")
        status = "ready_for_human_review" if not blockers else "needs_review"
        return {
            **base,
            "status": status,
            "title": title,
            "task_description": body,
            "detected_deliverable_lines": deliverables[:20],
            "detected_acceptance_lines": acceptance[:20],
            "local_work_checklist": [
                "Read the complete original task and linked references",
                "Confirm scope, deadline, license, AI-use rules and payout terms",
                "Create the deliverable locally and test it against every acceptance criterion",
                "Check for secrets, personal data, copied material and unsupported claims",
                "Request owner approval before any external claim or submission",
            ],
            "draft_response_outline": [
                "Briefly state the deliverable completed",
                "List files or evidence included",
                "Map each acceptance criterion to concrete evidence",
                "Disclose AI assistance if required by the source rules",
            ],
            "blockers": blockers,
            "notice": "This packet is a preparation aid only. It does not establish eligibility, acceptance, escrow, payment, or profit.",
        }

    @staticmethod
    def save_new(packet: dict, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            json.dump(packet, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
