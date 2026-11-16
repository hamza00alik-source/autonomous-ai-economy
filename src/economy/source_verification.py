"""Explicit, allowlisted retrieval of original research pages.

This is a manual owner-invoked fetch, not an automatic crawler. Retrieved text
is untrusted source material and is never promoted to buyer evidence.
"""
from __future__ import annotations

import hashlib
import ipaddress
import socket
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_SOURCE_BYTES = 1_000_000
MAX_TEXT_CHARS = 30_000


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        elif tag.lower() in {"p", "div", "br", "li", "h1", "h2", "h3", "article"}:
            self.parts.append("\\n")

    def handle_endtag(self, tag):
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag.lower() in {"p", "div", "li", "h1", "h2", "h3", "article"}:
            self.parts.append("\\n")

    def handle_data(self, data):
        if not self.skip_depth:
            cleaned = " ".join(data.split())
            if cleaned:
                self.parts.append(cleaned)

    def text(self) -> str:
        return "\\n".join(part for part in self.parts if part).strip()[:MAX_TEXT_CHARS]


@dataclass(frozen=True)
class RetrievedSource:
    url: str
    final_url: str
    hostname: str
    fetched_at: str
    content_type: str
    status_code: int
    content_sha256: str
    extracted_text: str
    text_truncated: bool
    verification_status: str = "retrieved_unverified"
    buyer_evidence_created: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _validate_url(url: str, allowed_hosts: set[str]) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("source URL must use HTTPS and include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not allowed")
    if parsed.port not in (None, 443):
        raise ValueError("only the default HTTPS port is allowed")
    host = parsed.hostname.lower().rstrip(".")
    if host not in allowed_hosts:
        raise ValueError("source hostname is not in the explicit --allowed-host list")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError("source hostname could not be resolved") from exc
    if not addresses:
        raise ValueError("source hostname has no resolved addresses")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("source hostname resolves to a non-public IP address")
    return host


class _AllowlistedRedirect(HTTPRedirectHandler):
    def __init__(self, allowed_hosts: set[str]) -> None:
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        host = _validate_url(newurl, self.allowed_hosts)
        original_host = urlparse(req.full_url).hostname
        if host != original_host:
            raise URLError("cross-host redirects are rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class OriginalSourceFetcher:
    """Fetch a single explicitly requested HTTPS page from an allowlisted host."""

    def fetch(self, url: str, *, allowed_hosts: list[str], timeout_seconds: float = 12) -> RetrievedSource:
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        hosts = {host.lower().rstrip(".") for host in allowed_hosts if host.strip()}
        if not hosts:
            raise ValueError("at least one explicit --allowed-host is required")
        hostname = _validate_url(url, hosts)
        request = Request(url, headers={
            "User-Agent": "AutonomousAIEconomy/0.1 (manual source verification)",
            "Accept": "text/html, text/plain, application/xhtml+xml",
        })
        opener = build_opener(_AllowlistedRedirect(hosts))
        with opener.open(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            final_host = _validate_url(final_url, hosts)
            if final_host != hostname:
                raise URLError("cross-host final response rejected")
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
                raise ValueError("only HTML and plain-text source pages are supported")
            body = response.read(MAX_SOURCE_BYTES + 1)
            status = getattr(response, "status", 200)
        if len(body) > MAX_SOURCE_BYTES:
            raise ValueError("source response exceeds the 1 MB safety limit")
        encoding = "utf-8"
        try:
            text_body = body.decode(encoding)
        except UnicodeDecodeError:
            text_body = body.decode("utf-8", errors="replace")
        if content_type in {"text/html", "application/xhtml+xml"}:
            parser = _TextExtractor()
            parser.feed(text_body)
            extracted = parser.text()
        else:
            extracted = " ".join(text_body.split())[:MAX_TEXT_CHARS]
        return RetrievedSource(
            url=url,
            final_url=final_url,
            hostname=hostname,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            content_type=content_type,
            status_code=status,
            content_sha256=hashlib.sha256(body).hexdigest(),
            extracted_text=extracted,
            text_truncated=len(text_body) > MAX_TEXT_CHARS or len(extracted) >= MAX_TEXT_CHARS,
        )
