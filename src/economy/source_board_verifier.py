"""Read-only verification of GitHub issue/PR links before drafting work.

Only canonical github.com issue and pull-request URLs are accepted. This module
never comments, assigns, forks, pushes, opens a PR, or submits work.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from urllib.parse import urlparse
from urllib.request import Request, urlopen

API_ROOT = "https://api.github.com"
MAX_BYTES = 1_000_000


@dataclass(frozen=True)
class SourceBoardResult:
    url: str
    supported: bool
    verified: bool
    state: str
    title: str | None
    comments: int | None
    updated_at: str | None
    merged: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


class GitHubSourceBoardVerifier:
    """Check canonical public GitHub issue/PR state without external writes."""

    def __init__(self, *, timeout_seconds: float = 10, fetcher=None):
        if not 1 <= timeout_seconds <= 20:
            raise ValueError("timeout_seconds must be between 1 and 20")
        self.timeout = timeout_seconds
        self.fetcher = fetcher or self._fetch

    @staticmethod
    def _fetch(url: str, timeout: float) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "api.github.com":
            raise ValueError("only HTTPS api.github.com is allowed")
        request = Request(url, headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "AutonomousAIEconomy-read-only-source-check",
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
    def _endpoint(url: str) -> tuple[str, str] | None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in {"github.com", "www.github.com"}:
            return None
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 4 or parts[2] not in {"issues", "pull"}:
            return None
        owner, repo, kind, number = parts
        if (not owner or not repo or not number.isdigit()
                or any(ch in owner + repo for ch in "?#%")):
            return None
        return f"{API_ROOT}/repos/{owner}/{repo}/issues/{number}", kind

    def verify(self, url: str) -> SourceBoardResult:
        endpoint = self._endpoint(url)
        if endpoint is None:
            return SourceBoardResult(
                url=url, supported=False, verified=False, state="unsupported",
                title=None, comments=None, updated_at=None, merged=False,
                reasons=("unsupported_source_url",),
            )
        api_url, kind = endpoint
        try:
            raw = self.fetcher(api_url, self.timeout)
            payload = json.loads(raw)
            if not isinstance(payload, dict) or not isinstance(payload.get("state"), str):
                raise ValueError("unexpected GitHub issue schema")
            is_pr = isinstance(payload.get("pull_request"), dict) or kind == "pull"
            merged = payload.get("pull_request", {}).get("merged") is True if isinstance(payload.get("pull_request"), dict) else False
            state = payload["state"].lower()
            comments = payload.get("comments")
            comments = max(0, int(comments)) if comments is not None else None
            reasons = []
            if state != "open":
                reasons.append("source_item_not_open")
            if merged:
                reasons.append("source_pull_request_already_merged")
            if comments is None:
                reasons.append("source_competition_unknown")
            elif comments > 10:
                reasons.append("source_competition_high")
            return SourceBoardResult(
                url=url, supported=True, verified=True,
                state="open_pull_request" if is_pr and state == "open" else state,
                title=str(payload.get("title") or "")[:300] or None,
                comments=comments,
                updated_at=payload.get("updated_at") if isinstance(payload.get("updated_at"), str) else None,
                merged=merged, reasons=tuple(reasons),
            )
        except Exception as exc:
            return SourceBoardResult(
                url=url, supported=True, verified=False, state="unverified",
                title=None, comments=None, updated_at=None, merged=False,
                reasons=(f"source_fetch_failed:{type(exc).__name__}",),
            )
