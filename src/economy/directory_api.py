"""Loopback-friendly, read-only WSGI service directory."""
from __future__ import annotations

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

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = environ.get("PATH_INFO", "")
        if method != "GET":
            return self._response(start_response, "405 Method Not Allowed",
                                  {"error": "method_not_allowed"},
                                  [("Allow", "GET")])
        if path == "/health":
            return self._response(start_response, "200 OK", {"status": "ok"})
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
