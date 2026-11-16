"""Free, keyless Hacker News community-discussion discovery via Algolia.

Discussion signals are qualitative research leads, not verified buying intent,
completed sales, representative market research, or proof of willingness to pay.
"""
from __future__ import annotations

import json
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from hashlib import sha256

from .research_sources import ResearchCandidate

API_HOST = "hn.algolia.com"
MAX_RESPONSE_BYTES = 1_000_000


class _SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname != API_HOST:
            raise URLError("redirect rejected: only HTTPS hn.algolia.com is allowed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class HackerNewsSearchProvider:
    """Search public HN stories without credentials or paid API access."""

    def __init__(self, *, timeout_seconds: float = 12) -> None:
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self.timeout_seconds = timeout_seconds

    @staticmethod
    def _fetch(url: str, timeout: float) -> bytes:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != API_HOST:
            raise ValueError("only HTTPS hn.algolia.com API URLs are allowed")
        request = Request(
            url,
            headers={"User-Agent": "AutonomousAIEconomy/0.1 (public HN research discovery)", "Accept": "application/json"},
        )
        opener = build_opener(_SameHostRedirect())
        with opener.open(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != API_HOST:
                raise URLError("API response host rejected")
            content_type = response.headers.get("Content-Type", "")
            if "application/json" not in content_type.lower():
                raise ValueError("Hacker News API returned a non-JSON content type")
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Hacker News response exceeds the 1 MB safety limit")
        return body

    def search(self, query: str, *, limit: int = 10) -> list[ResearchCandidate]:
        cleaned = " ".join(query.split())
        if not cleaned:
            raise ValueError("query is required")
        if len(cleaned) > 300:
            raise ValueError("query must be 300 characters or fewer")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")

        url = "https://hn.algolia.com/api/v1/search_by_date?" + urlencode({
            "query": cleaned,
            "tags": "story",
            "hitsPerPage": limit,
            "page": 0,
        })
        body = self._fetch(url, self.timeout_seconds)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ValueError("Hacker News response exceeds the 1 MB safety limit")
        payload = json.loads(body)
        hits = payload.get("hits")
        if not isinstance(hits, list):
            raise ValueError("Hacker News API response is missing its hits list")

        from datetime import datetime, timezone
        discovered = datetime.now(timezone.utc).isoformat()
        candidates: list[ResearchCandidate] = []
        for hit in hits[:limit]:
            if not isinstance(hit, dict):
                continue
            object_id = str(hit.get("objectID", "")).strip()
            title = str(hit.get("title") or "").strip()
            if not object_id.isdigit() or not title:
                continue
            permalink = f"https://news.ycombinator.com/item?id={object_id}"
            external_url = hit.get("url")
            if external_url:
                parsed_external = urlparse(str(external_url))
                if parsed_external.scheme not in {"http", "https"} or not parsed_external.netloc:
                    external_url = None
                else:
                    external_url = str(external_url)[:2000]
            key = sha256(("hackernews:" + object_id).encode("utf-8")).hexdigest()[:20]
            candidates.append(ResearchCandidate(
                candidate_id=key,
                query=cleaned,
                title=title[:500],
                article_url=permalink,
                publisher="Hacker News (Algolia Search)",
                published_at=str(hit.get("created_at") or "")[:100],
                discovered_at=discovered,
                source_kind="community_discussion_lead",
                sales_verified=False,
                points=hit.get("points") if isinstance(hit.get("points"), int) else None,
                comments=hit.get("num_comments") if isinstance(hit.get("num_comments"), int) else None,
                author=str(hit.get("author") or "")[:100],
                external_url=external_url,
            ))
        return candidates
