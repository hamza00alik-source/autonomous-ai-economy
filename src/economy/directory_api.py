"""Local service directory and signed participant task-offer API."""
from __future__ import annotations

import hashlib
import html
import ipaddress
import json
from urllib.parse import parse_qs

from .service_catalog import ServiceCatalog
from .identity import ParticipantRegistry
from .request_auth import RequestAuthenticator
from .task_store import TaskStore
from .task_agreements import TaskAgreementStore


class DirectoryApplication:
    """Expose only explicitly active listings; no participant PII or write routes."""

    def __init__(self, catalog: ServiceCatalog, *,
                 registry: ParticipantRegistry | None = None,
                 authenticator: RequestAuthenticator | None = None,
                 task_store: TaskStore | None = None,
                 agreements: TaskAgreementStore | None = None) -> None:
        self.catalog = catalog
        self.registry = registry
        self.authenticator = authenticator
        self.task_store = task_store
        self.agreements = agreements

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
        if method == "POST" and path == "/v1/participants/me/key-rotation-challenges":
            return self._begin_participant_key_rotation(environ, start_response)
        if method == "POST" and path == "/v1/participants/me/key-rotations":
            return self._complete_participant_key_rotation(environ, start_response)
        if method == "POST" and path == "/v1/participants/me/security-lock":
            return self._lock_participant_account(environ, start_response)
        if method == "POST" and path == "/v1/tasks/offers":
            return self._create_task_offer(environ, start_response)
        if method == "POST" and path.startswith("/v1/tasks/") and path.endswith("/responses"):
            task_id = path[len("/v1/tasks/"):-len("/responses")]
            if not task_id or "/" in task_id:
                return self._response(start_response, "404 Not Found", {"error": "not_found"})
            return self._respond_to_task_offer(environ, start_response, task_id)
        if method != "GET":
            return self._response(start_response, "405 Method Not Allowed",
                                  {"error": "method_not_allowed"},
                                  [("Allow", "GET, POST")])
        if path == "/health":
            return self._response(start_response, "200 OK", {"status": "ok"})
        if path == "/v1/local/owner/overview":
            return self._owner_overview(environ, start_response)
        if path == "/owner":
            return self._owner_dashboard(environ, start_response)
        if path == "/v1/tasks/offers/inbox":
            return self._provider_offer_inbox(environ, start_response)
        if method == "GET" and path.startswith("/v1/tasks/") and path not in {
            "/v1/tasks/mine", "/v1/tasks/offers/inbox"
        }:
            task_id = path[len("/v1/tasks/"):]
            if task_id and "/" not in task_id:
                return self._task_agreement_detail(environ, start_response, task_id)
        if path == "/v1/tasks/mine":
            return self._my_tasks(environ, start_response)
        if path == "/v1/participants/me/security-events":
            if environ.get("QUERY_STRING", ""):
                return self._response(start_response, "400 Bad Request",
                                      {"error": "query_parameters_not_supported"})
            if self.registry is None:
                return self._response(start_response, "503 Service Unavailable",
                                      {"error": "participant_security_events_unavailable"})
            principal, error = self._authenticated_get_principal(
                environ, start_response, path
            )
            if error is not None:
                return error
            try:
                events = self.registry.security_events(principal["participant_id"])
                items = [{
                    "event_id": item["event_id"],
                    "event_type": item["event_type"],
                    "occurred_at": item["occurred_at"],
                } for item in events]
            except Exception:
                return self._response(start_response, "503 Service Unavailable",
                                      {"error": "participant_security_events_temporarily_unavailable"})
            return self._response(start_response, "200 OK", {
                "participant_id": principal["participant_id"],
                "items": items, "count": len(items),
            })
        if path == "/v1/participants/me/keys":
            if environ.get("QUERY_STRING", ""):
                return self._response(start_response, "400 Bad Request",
                                      {"error": "query_parameters_not_supported"})
            if self.registry is None:
                return self._response(start_response, "503 Service Unavailable",
                                      {"error": "participant_key_history_unavailable"})
            principal, error = self._authenticated_get_principal(
                environ, start_response, path
            )
            if error is not None:
                return error
            try:
                history = self.registry.key_history(principal["participant_id"])
                items = [{
                    "old_key_id": hashlib.sha256(
                        item["old_public_key"].encode("ascii")
                    ).hexdigest()[:24],
                    "new_key_id": hashlib.sha256(
                        item["new_public_key"].encode("ascii")
                    ).hexdigest()[:24],
                    "rotated_at": item["rotated_at"],
                } for item in history]
            except Exception:
                return self._response(start_response, "503 Service Unavailable",
                                      {"error": "participant_key_history_temporarily_unavailable"})
            return self._response(start_response, "200 OK", {
                "participant_id": principal["participant_id"],
                "items": items,
                "count": len(items),
            })
        if path == "/v1/participants/me":
            if environ.get("QUERY_STRING", ""):
                return self._response(start_response, "400 Bad Request",
                                      {"error": "query_parameters_not_supported"})
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
            public_key = participant.get("public_key")
            public_profile = {
                key: participant[key] for key in (
                    "participant_id", "participant_type", "handle",
                    "display_name", "status", "created_at",
                )
            }
            # Expose only a stable fingerprint, never the signing key itself.
            public_profile["key_bound"] = bool(public_key)
            public_profile["key_id"] = (
                hashlib.sha256(public_key.encode("ascii")).hexdigest()[:24]
                if isinstance(public_key, str) and public_key.isascii()
                else None
            )
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

    def _authenticated_get_principal(self, environ, start_response, path):
        if self.authenticator is None:
            return None, self._response(start_response, "503 Service Unavailable",
                                        {"error": "authenticated_api_unavailable"})
        try:
            if environ.get("CONTENT_LENGTH") not in (None, "", "0"):
                raise ValueError("GET request body is not supported")
            timestamp = int(environ.get("HTTP_X_AAE_TIMESTAMP", ""))
            principal = self.authenticator.authenticate(
                environ.get("HTTP_X_AAE_PARTICIPANT", ""), "GET", path, b"",
                timestamp, environ.get("HTTP_X_AAE_NONCE", ""),
                environ.get("HTTP_X_AAE_SIGNATURE", ""),
            )
            return principal, None
        except (ValueError, TypeError):
            return None, self._response(start_response, "401 Unauthorized",
                                        {"error": "authentication_failed"},
                                        [("WWW-Authenticate", "AAE-Signature")])
        except Exception:
            return None, self._response(start_response, "503 Service Unavailable",
                                        {"error": "authentication_temporarily_unavailable"})

    def _provider_offer_inbox(self, environ, start_response):
        if self.agreements is None:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "task_offers_unavailable"})
        params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        if any(len(values) != 1 for values in params.values()) or set(params) - {"status", "limit"}:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_query_parameters"})
        status = params.get("status", ["offered"])[0]
        if status not in {"offered", "accepted", "declined", "withdrawn"}:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_offer_status"})
        try:
            limit = int(params.get("limit", ["50"])[0])
        except ValueError:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "limit_must_be_integer"})
        if not 1 <= limit <= 50:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "limit_out_of_range"})
        raw_query = environ.get("QUERY_STRING", "")
        target = "/v1/tasks/offers/inbox" + (("?" + raw_query) if raw_query else "")
        principal, error = self._authenticated_get_principal(environ, start_response, target)
        if error is not None:
            return error
        try:
            offers = self.agreements.offers_for_provider(
                principal["participant_id"], status=status, limit=limit
            )
        except Exception:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "offers_temporarily_unavailable"})
        items = [{
            key: offer[key] for key in (
                "task_id", "listing_id", "buyer_id", "provider_id", "title",
                "scope", "acceptance_criteria", "due_at", "price_minor",
                "currency", "status", "created_at",
            )
        } for offer in offers]
        return self._response(start_response, "200 OK", {"items": items, "count": len(items)})

    def _task_agreement_detail(self, environ, start_response, task_id):
        if self.agreements is None:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "task_offers_unavailable"})
        if environ.get("QUERY_STRING", ""):
            return self._response(start_response, "400 Bad Request",
                                  {"error": "query_parameters_not_supported"})
        principal, error = self._authenticated_get_principal(
            environ, start_response, f"/v1/tasks/{task_id}"
        )
        if error is not None:
            return error
        try:
            offer = self.agreements.get(task_id)
        except KeyError:
            return self._response(start_response, "404 Not Found", {"error": "not_found"})
        except Exception:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "offer_temporarily_unavailable"})
        if principal["participant_id"] not in {offer["buyer_id"], offer["provider_id"]}:
            return self._response(start_response, "404 Not Found", {"error": "not_found"})
        return self._response(start_response, "200 OK", {
            "task": {key: offer[key] for key in (
                "task_id", "listing_id", "buyer_id", "provider_id", "title",
                "scope", "acceptance_criteria", "due_at", "price_minor",
                "currency", "status", "created_at", "updated_at",
            )}
        })

    def _signed_json_body(self, environ, start_response, path):
        """Authenticate exact raw bytes before parsing a bounded JSON object."""
        if self.authenticator is None:
            return None, None, self._response(start_response, "503 Service Unavailable",
                                               {"error": "authenticated_api_unavailable"})
        if environ.get("QUERY_STRING", ""):
            return None, None, self._response(start_response, "400 Bad Request",
                                               {"error": "query_parameters_not_supported"})
        try:
            length = int(environ.get("CONTENT_LENGTH") or "0")
            if not 1 <= length <= 16384:
                raise ValueError("invalid body length")
            stream = environ.get("wsgi.input")
            raw = stream.read(length) if stream is not None else b""
            if len(raw) != length:
                raise ValueError("incomplete request body")
            timestamp = int(environ.get("HTTP_X_AAE_TIMESTAMP", ""))
        except (ValueError, TypeError):
            return None, None, self._response(start_response, "400 Bad Request",
                                               {"error": "invalid_request"})
        participant_id = environ.get("HTTP_X_AAE_PARTICIPANT", "")
        nonce = environ.get("HTTP_X_AAE_NONCE", "")
        signature = environ.get("HTTP_X_AAE_SIGNATURE", "")
        try:
            principal = self.authenticator.authenticate(
                participant_id, "POST", path, raw, timestamp, nonce, signature
            )
        except ValueError:
            return None, None, self._response(start_response, "401 Unauthorized",
                                               {"error": "authentication_failed"},
                                               [("WWW-Authenticate", "AAE-Signature")])
        except Exception:
            return None, None, self._response(start_response, "503 Service Unavailable",
                                               {"error": "authentication_temporarily_unavailable"})
        try:
            def no_duplicate_keys(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError("duplicate JSON key")
                    result[key] = value
                return result
            payload = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicate_keys)
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return principal, payload, None
        except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
            return None, None, self._response(start_response, "400 Bad Request",
                                               {"error": "invalid_json_body"})

    def _lock_participant_account(self, environ, start_response):
        if self.registry is None:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "participant_security_lock_unavailable"})
        path = "/v1/participants/me/security-lock"
        principal, body, error = self._signed_json_body(environ, start_response, path)
        if error is not None:
            return error
        if body != {"confirm": "LOCK_ACCOUNT"}:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "explicit_lock_confirmation_required"})
        try:
            locked = self.registry.emergency_lock_account(principal["participant_id"])
        except KeyError:
            return self._response(start_response, "404 Not Found",
                                  {"error": "participant_not_found"})
        except ValueError:
            return self._response(start_response, "409 Conflict",
                                  {"error": "participant_not_active"})
        except Exception:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "participant_security_lock_temporarily_unavailable"})
        return self._response(start_response, "202 Accepted", {
            "participant_id": locked["participant_id"],
            "status": locked["status"],
            "locked_at": locked["locked_at"],
            "notice": "Account access is suspended. There is no self-service unlock."
        })

    def _begin_participant_key_rotation(self, environ, start_response):
        if self.registry is None:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "participant_key_rotation_unavailable"})
        path = "/v1/participants/me/key-rotation-challenges"
        principal, body, error = self._signed_json_body(environ, start_response, path)
        if error is not None:
            return error
        if set(body) != {"new_public_key"} or not isinstance(body["new_public_key"], str) or not body["new_public_key"]:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_key_rotation_fields"})
        if len(body["new_public_key"]) > 128:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_key_rotation_fields"})
        try:
            challenge = self.registry.begin_key_rotation(
                principal["participant_id"], body["new_public_key"]
            )
        except ValueError:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "key_rotation_challenge_rejected"})
        except Exception:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "key_rotation_temporarily_unavailable"})
        return self._response(start_response, "201 Created", {
            "participant_id": principal["participant_id"],
            "challenge": challenge["challenge"],
            "challenge_id": challenge["challenge_id"],
            "expires_at": challenge["expires_at"],
            "signature_encoding": challenge["signature_encoding"],
            "required_signatures": "current_and_new_key",
            "notice": "No key changes until both proofs are verified."
        })

    def _complete_participant_key_rotation(self, environ, start_response):
        if self.registry is None:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "participant_key_rotation_unavailable"})
        path = "/v1/participants/me/key-rotations"
        principal, body, error = self._signed_json_body(environ, start_response, path)
        if error is not None:
            return error
        required = {"challenge_id", "old_signature", "new_signature"}
        if set(body) != required or any(
            not isinstance(body[key], str) or not body[key].strip() or len(body[key]) > 256
            for key in required
        ):
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_key_rotation_fields"})
        try:
            participant = self.registry.get(principal["participant_id"])
            if participant is None or participant.get("status") != "active":
                raise ValueError("participant is inactive")
            rotated = self.registry.complete_key_rotation(
                body["challenge_id"], body["old_signature"], body["new_signature"],
                expected_participant_id=principal["participant_id"]
            )
            if rotated.get("participant_id") != principal["participant_id"]:
                return self._response(start_response, "409 Conflict",
                                      {"error": "key_rotation_rejected"})
        except ValueError:
            return self._response(start_response, "409 Conflict",
                                  {"error": "key_rotation_rejected"})
        except Exception:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "key_rotation_temporarily_unavailable"})
        public_key = rotated.get("public_key")
        key_id = (hashlib.sha256(public_key.encode("ascii")).hexdigest()[:24]
                  if isinstance(public_key, str) and public_key.isascii() else None)
        return self._response(start_response, "200 OK", {
            "participant_id": principal["participant_id"],
            "key_bound": bool(public_key),
            "key_id": key_id,
            "notice": "Signing key rotated. Sign subsequent requests with the new key."
        })

    def _create_task_offer(self, environ, start_response):
        if self.agreements is None:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "task_offers_unavailable"})
        path = "/v1/tasks/offers"
        principal, body, error = self._signed_json_body(environ, start_response, path)
        if error is not None:
            return error
        required = {"task_id", "listing_id", "provider_id", "title", "scope",
                    "acceptance_criteria", "offer_signature"}
        optional = {"due_at", "price_minor", "currency"}
        if set(body) - required - optional or not required.issubset(body):
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_offer_fields"})
        string_limits = {
            "task_id": 128, "listing_id": 128, "provider_id": 128,
            "title": 160, "scope": 4000, "acceptance_criteria": 2000,
            "offer_signature": 256,
        }
        if any(not isinstance(body[key], str) or not body[key].strip()
               or len(body[key]) > limit for key, limit in string_limits.items()):
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_offer_fields"})
        if "due_at" in body and (not isinstance(body["due_at"], str) or len(body["due_at"]) > 80):
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_offer_fields"})
        if "price_minor" in body and (
            not isinstance(body["price_minor"], int) or isinstance(body["price_minor"], bool)
            or body["price_minor"] < 0
        ):
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_offer_fields"})
        if "currency" in body and (
            not isinstance(body["currency"], str) or len(body["currency"]) != 3
            or not body["currency"].isalpha()
        ):
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_offer_fields"})
        if ("price_minor" in body) != ("currency" in body):
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_offer_fields"})
        try:
            offer = self.agreements.create_offer(
                task_id=body["task_id"], listing_id=body["listing_id"],
                buyer_id=principal["participant_id"], provider_id=body["provider_id"],
                title=body["title"], scope=body["scope"],
                acceptance_criteria=body["acceptance_criteria"],
                due_at=body.get("due_at"), price_minor=body.get("price_minor"),
                currency=body.get("currency"), signature=body["offer_signature"],
            )
        except ValueError:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "offer_validation_failed"})
        except Exception:
            return self._response(start_response, "409 Conflict",
                                  {"error": "offer_could_not_be_created"})
        return self._response(start_response, "201 Created", {
            "task": {"task_id": offer["task_id"], "listing_id": offer["listing_id"],
                     "buyer_id": offer["buyer_id"], "provider_id": offer["provider_id"],
                     "status": offer["status"], "created_at": offer["created_at"]},
            "notice": "Offer created; no payment has been requested or processed.",
        })

    def _respond_to_task_offer(self, environ, start_response, task_id):
        if self.agreements is None:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "task_offers_unavailable"})
        path = f"/v1/tasks/{task_id}/responses"
        principal, body, error = self._signed_json_body(environ, start_response, path)
        if error is not None:
            return error
        if set(body) != {"decision", "response_signature"}:
            return self._response(start_response, "400 Bad Request",
                                  {"error": "invalid_response_fields"})
        try:
            offer = self.agreements.respond(
                task_id, provider_id=principal["participant_id"],
                decision=body["decision"], signature=body["response_signature"],
            )
        except ValueError:
            return self._response(start_response, "409 Conflict",
                                  {"error": "offer_response_rejected"})
        except Exception:
            return self._response(start_response, "503 Service Unavailable",
                                  {"error": "offer_response_temporarily_unavailable"})
        return self._response(start_response, "200 OK", {
            "task": {"task_id": offer["task_id"], "status": offer["status"],
                     "provider_id": offer["provider_id"]},
            "notice": "Provider response recorded; no payment has been processed.",
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
            # Bind the exact raw query string into the signature. Otherwise a
            # valid signature for one filter/limit could be replayed with another.
            request_target = "/v1/tasks/mine"
            raw_query = environ.get("QUERY_STRING", "")
            if raw_query:
                request_target += "?" + raw_query
            principal = self.authenticator.authenticate(
                participant_id, "GET", request_target, body, timestamp, nonce, signature
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
        agreements=TaskAgreementStore(data_dir / "participants.sqlite3"),
    )
