"""Loopback-friendly, read-only WSGI service directory."""
from __future__ import annotations

import html
import json
from urllib.parse import parse_qs

from .service_catalog import ServiceCatalog


class DirectoryApplication:
    """Expose only explicitly active listings; no participant PII or write routes."""

    def __init__(self, catalog: ServiceCatalog) -> None:
        self.catalog = catalog

    @staticmethod
    def _response(start_response, status: str, payload: dict, headers=None):
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        response_headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
        ]
        if headers:
            response_headers.extend(headers)
        start_response(status, response_headers)
        return [body]

    def _html_response(self, start_response, body: str, status: str = "200 OK"):
        encoded = body.encode("utf-8")
        start_response(status, [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(encoded))),
            ("Cache-Control", "no-store"),
            ("X-Content-Type-Options", "nosniff"),
            ("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"),
            ("Referrer-Policy", "no-referrer"),
        ])
        return [encoded]

    def _directory_page(self, query: str = "") -> str:
        listings = self.catalog.discover(query=query, limit=50)
        cards = []
        for item in listings:
            title = html.escape(str(item["title"]))
            description = html.escape(str(item["description"]))
            category = html.escape(str(item["category"]))
            delivery = html.escape(str(item["delivery_format"]))
            terms = html.escape(str(item["terms"]))
            provider = html.escape(str(item["provider_id"]))
            price = ("Not specified" if item["price_minor"] is None else
                     f'{html.escape(str(item["price_minor"]))} minor units {html.escape(str(item["currency"]))}')
            cards.append(
                '<article class="card"><p class="eyebrow">' + category + '</p>'
                '<h2>' + title + '</h2><p>' + description + '</p>'
                '<dl><dt>Delivery</dt><dd>' + delivery + '</dd>'
                '<dt>Terms</dt><dd>' + terms + '</dd>'
                '<dt>Price</dt><dd>' + price + '</dd>'
                '<dt>Provider ID</dt><dd>' + provider + '</dd></dl></article>'
            )
        content = "".join(cards) if cards else '<p class="empty">No active services found.</p>'
        safe_query = html.escape(query, quote=True)
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Autonomous AI Economy — Services</title><style>'
            ':root{color-scheme:light dark;font-family:system-ui,sans-serif}'
            'body{margin:0;padding:24px;max-width:900px;margin-inline:auto;line-height:1.5}'
            'header{margin:12px 0 24px}.muted,.eyebrow{opacity:.72}'
            'form{display:flex;gap:8px;margin:18px 0 24px}'
            'input{flex:1;min-width:0;padding:12px;border:1px solid #888;border-radius:10px;background:transparent;color:inherit}'
            'button{padding:12px 16px;border:0;border-radius:10px;font-weight:600}'
            '.card{border:1px solid #8888;border-radius:14px;padding:18px;margin:14px 0}'
            'h2{font-size:1.2rem;margin:4px 0}.eyebrow{text-transform:uppercase;font-size:.75rem;letter-spacing:.08em}'
            'dl{display:grid;grid-template-columns:110px 1fr;gap:6px 12px;font-size:.9rem}'
            'dt{font-weight:650}.empty{padding:24px;border:1px dashed #888;border-radius:12px}'
            '</style></head><body><header><p class="eyebrow">Open participation • read-only preview</p>'
            '<h1>Available services</h1><p class="muted">Only active, owner-approved listings appear here.</p></header>'
            '<form method="get" action="/"><input name="q" maxlength="120" value="' + safe_query +
            '" placeholder="Search services"><button type="submit">Search</button></form>'
            + content + '<footer class="muted"><p>Local prototype directory. No payments or bookings are processed.</p></footer>'
            '</body></html>'
        )

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "")
        if method != "GET":
            return self._response(start_response, "405 Method Not Allowed",
                                  {"error": "method_not_allowed"},
                                  [("Allow", "GET")])
        if path == "/health":
            return self._response(start_response, "200 OK", {"status": "ok"})
        if path == "/":
            params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
            if any(len(values) != 1 for values in params.values()) or set(params) - {"q"}:
                return self._html_response(start_response, "<h1>Invalid query</h1>", "400 Bad Request")
            query = params.get("q", [""])[0]
            if len(query) > 120:
                return self._html_response(start_response, "<h1>Search query too long</h1>", "400 Bad Request")
            try:
                return self._html_response(start_response, self._directory_page(query))
            except Exception:
                return self._html_response(start_response, "<h1>Directory temporarily unavailable</h1>", "503 Service Unavailable")
        if path != "/v1/directory/services":
            return self._response(start_response, "404 Not Found",
                                  {"error": "not_found"})
        params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        if any(len(values) != 1 for values in params.values()):
            return self._response(start_response, "400 Bad Request",
                                  {"error": "duplicate_query_parameter"})
        allowed = {"q", "category", "limit"}
        if set(params) - allowed:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "unsupported_query_parameter"})
        query = params.get("q", [""])[0]
        category = params.get("category", [None])[0]
        raw_limit = params.get("limit", ["50"])[0]
        if len(query) > 120 or (category is not None and len(category) > 80):
            return self._response(start_response, "400 Bad Request",
                                  {"error": "query_too_long"})
        try:
            limit = int(raw_limit)
        except ValueError:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "limit_must_be_integer"})
        if not 1 <= limit <= 100:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "limit_out_of_range"})
        try:
            listings = self.catalog.discover(
                query=query, category=category, limit=limit
            )
        except Exception:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "directory_temporarily_unavailable"})
        # discover() already filters status='active'; explicitly serialize fields.
        public_items = [{
            "listing_id": item["listing_id"],
            "provider_id": item["provider_id"],
            "slug": item["slug"],
            "title": item["title"],
            "description": item["description"],
            "category": item["category"],
            "delivery_format": item["delivery_format"],
            "terms": item["terms"],
            "price_minor": item["price_minor"],
            "currency": item["currency"],
        } for item in listings]
        return self._response(start_response, "200 OK", {
            "items": public_items, "count": len(public_items),
        })


def create_directory_app(data_dir="./data") -> DirectoryApplication:
    from pathlib import Path
    return DirectoryApplication(ServiceCatalog(Path(data_dir) / "participants.sqlite3"))
