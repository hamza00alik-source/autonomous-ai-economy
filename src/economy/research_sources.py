"""Free, keyless discovery of public Google News RSS items.

Results are leads for human/source verification, never proof of demand or sales.
The adapter fetches only news.google.com and rejects redirects to other hosts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Callable
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET


MAX_FEED_BYTES = 1_000_000
ALLOWED_HOST = "news.google.com"


@dataclass(frozen=True)
class ResearchCandidate:
    candidate_id: str
    query: str
    title: str
    article_url: str
    publisher: str
    published_at: str
    discovered_at: str
    source_kind: str = "news_discovery_lead"
    verification_status: str = "unverified"
    sales_verified: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class _SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlparse(newurl)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise URLError("redirect rejected: only HTTPS news.google.com is allowed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class GoogleNewsRSSProvider:
    """Fetch public news discovery leads without an API key or paid service."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 12,
        fetcher: Callable[[str, float], bytes] | None = None,
    ) -> None:
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        self.timeout_seconds = timeout_seconds
        self._fetcher = fetcher or self._fetch

    @staticmethod
    def _fetch(url: str, timeout: float) -> bytes:
        request = Request(url, headers={"User-Agent": "AutonomousAIEconomy/0.1 (public RSS discovery)"})
        opener = build_opener(_SameHostRedirect())
        with opener.open(request, timeout=timeout) as response:
            final = urlparse(response.geturl())
            if final.scheme != "https" or final.hostname != ALLOWED_HOST:
                raise URLError("feed response host rejected")
            body = response.read(MAX_FEED_BYTES + 1)
        if len(body) > MAX_FEED_BYTES:
            raise ValueError("RSS feed exceeds the 1 MB safety limit")
        return body

    def search(self, query: str, *, limit: int = 10) -> list[ResearchCandidate]:
        cleaned = " ".join(query.split())
        if not cleaned:
            raise ValueError("query is required")
        if len(cleaned) > 300:
            raise ValueError("query must be 300 characters or fewer")
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")

        url = "https://news.google.com/rss/search?" + urlencode({
            "q": cleaned,
            "hl": "en",
            "gl": "US",
            "ceid": "US:en",
        })
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_HOST:
            raise ValueError("feed URL host rejected")
        body = self._fetcher(url, self.timeout_seconds)
        if len(body) > MAX_FEED_BYTES:
            raise ValueError("RSS feed exceeds the 1 MB safety limit")

        root = ET.fromstring(body)
        candidates: list[ResearchCandidate] = []
        discovered = datetime.now(timezone.utc).isoformat()
        for item in root.findall("./channel/item")[:limit]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            published = (item.findtext("pubDate") or "").strip()
            source_element = item.find("source")
            publisher = (source_element.text or "").strip() if source_element is not None else ""
            article = urlparse(link)
            if not title or article.scheme not in {"http", "https"} or not article.netloc:
                continue
            key = sha256((cleaned + "|" + link).encode("utf-8")).hexdigest()[:20]
            candidates.append(ResearchCandidate(
                candidate_id=key,
                query=cleaned,
                title=title[:500],
                article_url=link,
                publisher=publisher[:200],
                published_at=published[:100],
                discovered_at=discovered,
            ))
        return candidates
