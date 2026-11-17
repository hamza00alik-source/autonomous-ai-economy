"""Loopback-friendly, read-only WSGI service directory."""
from __future__ import annotations

import html
import ipaddress
import json
from urllib.parse import parse_qs

from .service_catalog import ServiceCatalog
from .identity import ParticipantRegistry
from .request_auth import RequestAuthenticator
from .task_store import TaskStore


class DirectoryApplication:
    """Expose only explicitly active listings; no participant PII or write routes."""

    def __init__(self, catalog: ServiceCatalog, *,
                 registry: ParticipantRegistry | None = None,
                 authenticator: RequestAuthenticator | None = None,
                 task_store: TaskStore | None = None) -> None:
        self.catalog = catalog
        self.registry = registry
        self.authenticator = authenticator
        self.task_store = task_store

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
        if path == "/v1/local/owner/overview":
            return self._owner_overview(environ, start_response)
        if path == "/owner":
            return self._owner_dashboard(environ, start_response)
        if path == "/v1/tasks/mine":
            return self._my_tasks(environ, start_response)
        if path == "/v1/participants/me":
            if self.registry is None or self.authenticator is None:
                return self._response(start_response, "503 Service Unavailable",
                                      {"error": "authenticated_profile_unavailable"})
            try:
                raw_length = environ.get("CONTENT_LENGTH") or "0"
                body_length = int(raw_length)
                if not 0 <= body_length <= 65536:
                    raise ValueError("request body length is invalid")
                stream = environ.get("wsgi.input")
                body = stream.read(body_length) if stream is not None and body_length else b""
                if len(body) != body_length:
                    raise ValueError("request body is incomplete")
                participant_id = environ.get("HTTP_X_AAE_PARTICIPANT", "")
                timestamp = int(environ.get("HTTP_X_AAE_TIMESTAMP", ""))
                nonce = environ.get("HTTP_X_AAE_NONCE", "")
                signature = environ.get("HTTP_X_AAE_SIGNATURE", "")
                principal = self.authenticator.authenticate(
                    participant_id, method, path, body, timestamp, nonce, signature
                )
                participant = self.registry.get(principal["participant_id"])
                if participant is None:
                    raise ValueError("participant no longer exists")
            except (ValueError, TypeError, KeyError):
                return self._response(start_response, "401 Unauthorized",
                                      {"error": "authentication_failed"},
                                      [("WWW-Authenticate", "AAE-Signature")])
            except Exception:
                return self._response(start_response, "503 Service Unavailable",
                                      {"error": "authentication_temporarily_unavailable"})
            public_profile = {
                key: participant[key] for key in (
                    "participant_id", "participant_type", "handle",
                    "display_name", "status", "created_at",
                )
            }
            return self._response(start_response, "200 OK",
                                  {"participant": public_profile})
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

    def _owner_dashboard(self, environ, start_response):
        """Loopback-only, aggregate-only HTML owner snapshot; no controls or writes."""
        try:
            remote = ipaddress.ip_address(environ.get("REMOTE_ADDR", ""))
        except ValueError:
            remote = None
        if remote is None or not remote.is_loopback:
            return self._html_response(start_response, "<h1>Local access only</h1>", "403 Forbidden")
        if self.registry is None or self.task_store is None:
            return self._html_response(start_response, "<h1>Owner overview unavailable</h1>", "503 Service Unavailable")
        try:
            summary = {
                "participants": self.registry.summary_counts(),
                "tasks": self.task_store.summary_counts(),
                "services": self.catalog.summary_counts(),
                "financial_activity": {
                    "payments_enabled": False,
                    "wallets_enabled": False,
                    "transfers_enabled": False,
                },
            }
            safe_json = html.escape(json.dumps(summary, indent=2, ensure_ascii=False))
            page = (
                '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>Local owner overview</title><style>'
                ':root{color-scheme:light dark;font-family:system-ui,sans-serif}'
                'body{max-width:760px;margin:0 auto;padding:24px;line-height:1.5}'
                'pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:18px;border:1px solid #8888;border-radius:12px}'
                '.note{opacity:.75}</style></head><body><header><p class="note">LOCAL • READ ONLY</p>'
                '<h1>Economy overview</h1><p class="note">Aggregate operational counts only. '
                'No participant records, task contents, payments, wallets or transfers are exposed.</p></header>'
                '<pre>' + safe_json + '</pre><p class="note">Prototype snapshot; not a production administration console.</p>'
                '</body></html>'
            )
            return self._html_response(start_response, page)
        except Exception:
            return self._html_response(start_response, "<h1>Owner overview temporarily unavailable</h1>", "503 Service Unavailable")

    def _owner_overview(self, environ, start_response):
        """Loopback-only operational summary; never returns participant or task records."""
        try:
            remote = ipaddress.ip_address(environ.get("REMOTE_ADDR", ""))
        except ValueError:
            remote = None
        if remote is None or not remote.is_loopback:
            return self._response(start_response, "403 Forbidden",
                                  {"error": "local_access_only"})
        if self.registry is None or self.task_store is None:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "owner_overview_unavailable"})
        try:
            return self._response(start_response, "200 OK", {
                "scope": "aggregate_local_read_only",
                "participants": self.registry.summary_counts(),
                "tasks": self.task_store.summary_counts(),
                "services": self.catalog.summary_counts(),
                "financial_activity": {
                    "payments_enabled": False,
                    "wallets_enabled": False,
                    "transfers_enabled": False,
                },
            })
        except Exception:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "owner_overview_temporarily_unavailable"})

    def _my_tasks(self, environ, start_response):
        if self.registry is None or self.authenticator is None or self.task_store is None:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "authenticated_tasks_unavailable"})
        params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        if any(len(values) != 1 for values in params.values()):
            return self._response(start_response, "400 Bad Request",
                                  {"error": "duplicate_query_parameter"})
        if set(params) - {"status", "limit"}:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "unsupported_query_parameter"})
        status = params.get("status", [None])[0]
        if status not in {None, "queued", "running", "completed", "failed"}:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_task_status"})
        try:
            limit = int(params.get("limit", ["50"])[0])
        except ValueError:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "limit_must_be_integer"})
        if not 1 <= limit <= 100:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "limit_out_of_range"})
        try:
            body_length = int(environ.get("CONTENT_LENGTH") or "0")
            if not 0 <= body_length <= 65536:
                raise ValueError("invalid body length")
            stream = environ.get("wsgi.input")
            body = stream.read(body_length) if stream is not None and body_length else b""
            if len(body) != body_length:
                raise ValueError("incomplete body")
            participant_id = environ.get("HTTP_X_AAE_PARTICIPANT", "")
            timestamp = int(environ.get("HTTP_X_AAE_TIMESTAMP", ""))
            nonce = environ.get("HTTP_X_AAE_NONCE", "")
            signature = environ.get("HTTP_X_AAE_SIGNATURE", "")
            principal = self.authenticator.authenticate(
                participant_id, "GET", "/v1/tasks/mine", body, timestamp, nonce, signature
            )
            participant = self.registry.get(principal["participant_id"])
            if participant is None:
                raise ValueError("participant no longer exists")
        except (ValueError, TypeError, KeyError):
            return self._response(start_response, "401 Unauthorized",
                                  {"error": "authentication_failed"},
                                  [("WWW-Authenticate", "AAE-Signature")])
        except Exception:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "authentication_temporarily_unavailable"})
        try:
            tasks = self.task_store.list_for_agent(
                participant["participant_id"], status=status, limit=limit
            )
        except Exception:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "tasks_temporarily_unavailable"})
        safe_tasks = [{
            "task_id": task["task_id"],
            "title": task["title"],
            "assigned_agent": task["assigned_agent"],
            "status": task["status"],
            "attempts": task["attempts"],
            "max_attempts": task["max_attempts"],
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        } for task in tasks]
        return self._response(start_response, "200 OK",
                              {"items": safe_tasks, "count": len(safe_tasks)})


def create_directory_app(data_dir="./data") -> DirectoryApplication:
    from pathlib import Path
    data_dir = Path(data_dir)
    registry = ParticipantRegistry(data_dir / "participants.sqlite3")
    authenticator = RequestAuthenticator(
        registry, data_dir / "request-replay.sqlite3"
    )
    return DirectoryApplication(
        ServiceCatalog(data_dir / "participants.sqlite3"),
        registry=registry, authenticator=authenticator,
        task_store=TaskStore(data_dir / "economy.sqlite3"),
    )
