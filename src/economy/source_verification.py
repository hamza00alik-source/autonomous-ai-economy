"""Explicit, allowlisted retrieval of original research pages.

This manual owner-invoked fetch pins each TCP connection to a validated public
IP address while retaining the original hostname for TLS SNI and certificate
validation. Retrieved text remains untrusted and is never buyer evidence.
"""
from __future__ import annotations

import hashlib
import http.client
import ipaddress
import socket
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

MAX_SOURCE_BYTES = 1_000_000
MAX_TEXT_CHARS = 30_000
MAX_REDIRECTS = 3
ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_tags: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_tags.append(tag)
        elif not self.skip_tags and tag in {"p", "div", "br", "li", "h1", "h2", "h3", "article"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.skip_tags:
            # Pop through the matching nested element without allowing malformed
            # markup to leave the parser permanently inside a skipped section.
            index = len(self.skip_tags) - 1 - self.skip_tags[::-1].index(tag)
            del self.skip_tags[index:]
        elif not self.skip_tags and tag in {"p", "div", "li", "h1", "h2", "h3", "article"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_tags:
            cleaned = " ".join(data.split())
            if cleaned:
                self.parts.append(cleaned)

    def text(self) -> str:
        return "\n".join(part for part in self.parts if part).strip()[:MAX_TEXT_CHARS]


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


def _parse_allowed_url(url: str, allowed_hosts: set[str]) -> tuple[str, str]:
    if not isinstance(url, str) or any(ord(char) < 32 for char in url):
        raise ValueError("source URL is malformed")
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("source URL must use HTTPS and include a hostname")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not allowed")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("source URL port is invalid") from exc
    if port not in (None, 443):
        raise ValueError("only the default HTTPS port is allowed")
    host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    if host not in allowed_hosts:
        raise ValueError("source hostname is not in the explicit --allowed-host list")
    if not parsed.path.startswith("/") or parsed.netloc.endswith("@"):
        raise ValueError("source URL authority or path is malformed")
    return host, parsed.path + (("?" + parsed.query) if parsed.query else "")


def _resolve_public_addresses(host: str) -> list[str]:
    try:
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("source hostname could not be resolved") from exc
    addresses = list(dict.fromkeys(item[4][0] for item in records))
    if not addresses:
        raise ValueError("source hostname has no resolved addresses")
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as exc:
            raise ValueError("DNS returned an invalid address") from exc
        if not ip.is_global:
            raise ValueError("source hostname resolves to a non-public IP address")
    return addresses


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that dials a pinned IP but authenticates the DNS hostname."""

    def __init__(self, hostname: str, pinned_ip: str, timeout: float):
        super().__init__(hostname, 443, timeout=timeout, context=ssl.create_default_context())
        self.pinned_ip = pinned_ip

    def connect(self):
        raw_socket = socket.create_connection((self.pinned_ip, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)
        except Exception:
            raw_socket.close()
            raise


def _fetch_one(url: str, host: str, request_target: str, timeout: float):
    addresses = _resolve_public_addresses(host)
    last_error = None
    for address in addresses:
        connection = _PinnedHTTPSConnection(host, address, timeout)
        try:
            connection.request("GET", request_target, headers={
                "User-Agent": "AutonomousAIEconomy/0.1 (manual source verification)",
                "Accept": "text/html, text/plain, application/xhtml+xml",
                "Connection": "close",
            })
            response = connection.getresponse()
            return connection, response
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            connection.close()
            last_error = exc
    raise OSError("could not connect to any validated public address") from last_error


class OriginalSourceFetcher:
    """Fetch one HTTPS page from an explicit allowlist with per-hop IP pinning."""

    def fetch(self, url: str, *, allowed_hosts: list[str], timeout_seconds: float = 12) -> RetrievedSource:
        if not 1 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 1 and 30")
        hosts = {
            host.encode("idna").decode("ascii").lower().rstrip(".")
            for host in allowed_hosts if isinstance(host, str) and host.strip()
        }
        if not hosts:
            raise ValueError("at least one explicit --allowed-host is required")

        original_host, _ = _parse_allowed_url(url, hosts)
        current_url = url
        connection = None
        response = None
        try:
            for redirect_count in range(MAX_REDIRECTS + 1):
                host, request_target = _parse_allowed_url(current_url, hosts)
                if host != original_host:
                    raise ValueError("cross-host redirects are rejected")
                connection, response = _fetch_one(current_url, host, request_target, timeout_seconds)
                if response.status in REDIRECT_STATUSES:
                    location = response.getheader("Location")
                    response.read(0)
                    connection.close()
                    connection = None
                    if not location or redirect_count >= MAX_REDIRECTS:
                        raise ValueError("redirect missing location or redirect limit exceeded")
                    next_url = urljoin(current_url, location)
                    next_host, _ = _parse_allowed_url(next_url, hosts)
                    if next_host != original_host:
                        raise ValueError("cross-host redirects are rejected")
                    current_url = next_url
                    continue
                if response.status != 200:
                    raise ValueError("source server returned HTTP " + str(response.status))
                content_type = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type not in ALLOWED_CONTENT_TYPES:
                    raise ValueError("only HTML and plain-text source pages are supported")
                body = response.read(MAX_SOURCE_BYTES + 1)
                if len(body) > MAX_SOURCE_BYTES:
                    raise ValueError("source response exceeds the 1 MB safety limit")
                break
            else:
                raise ValueError("redirect limit exceeded")
        finally:
            if connection is not None:
                connection.close()

        text_body = body.decode("utf-8", errors="replace")
        if content_type in {"text/html", "application/xhtml+xml"}:
            parser = _TextExtractor()
            parser.feed(text_body)
            extracted = parser.text()
        else:
            extracted = " ".join(text_body.split())[:MAX_TEXT_CHARS]
        return RetrievedSource(
            url=url,
            final_url=current_url,
            hostname=original_host,
            fetched_at=datetime.now(timezone.utc).isoformat(),
            content_type=content_type,
            status_code=200,
            content_sha256=hashlib.sha256(body).hexdigest(),
            extracted_text=extracted,
            text_truncated=len(text_body) > MAX_TEXT_CHARS or len(extracted) >= MAX_TEXT_CHARS,
        )
