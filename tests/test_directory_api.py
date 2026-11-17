import json
import unittest

from economy.directory_api import DirectoryApplication


class FakeCatalog:
    def __init__(self):
        self.calls = []

    def discover(self, *, query="", category=None, limit=50):
        self.calls.append((query, category, limit))
        return [{
            "listing_id": "listing_public",
            "provider_id": "provider_public",
            "slug": "safe-service",
            "title": "Safe Service",
            "description": "Public listing description",
            "category": "research",
            "delivery_format": "report",
            "terms": "One-time delivery",
            "price_minor": 1000,
            "currency": "USD",
            "private_metadata": "must-not-leak",
        }][:limit]


class DirectoryApiTests(unittest.TestCase):
    def setUp(self):
        self.catalog = FakeCatalog()
        self.app = DirectoryApplication(self.catalog)

    def request(self, path, method="GET"):
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": path.split("?", 1)[0],
            "QUERY_STRING": path.split("?", 1)[1] if "?" in path else "",
        }
        body = b"".join(self.app(environ, start_response))
        return captured, json.loads(body)

    def test_health_exposes_only_minimal_status(self):
        response, body = self.request("/health")
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(body, {"status": "ok"})

    def test_directory_returns_allowlisted_active_listing_fields(self):
        response, body = self.request(
            "/v1/directory/services?q=research&category=research&limit=10"
        )
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(body["count"], 1)
        self.assertNotIn("private_metadata", body["items"][0])
        self.assertEqual(self.catalog.calls, [("research", "research", 10)])
        self.assertEqual(response["headers"]["Cache-Control"], "no-store")

    def test_mobile_directory_page_escapes_listing_content(self):
        class UnsafeCatalog:
            def discover(self, **_kwargs):
                return [{
                    "listing_id": "x", "provider_id": "p",
                    "slug": "x", "title": "<script>alert(1)</script>",
                    "description": "<img src=x onerror=alert(1)>",
                    "category": "test", "delivery_format": "download",
                    "terms": "terms", "price_minor": None, "currency": None,
                }]
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)
        output = DirectoryApplication(UnsafeCatalog())(
            {"REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "q=demo"},
            start_response,
        )
        page = b"".join(output).decode("utf-8")
        self.assertEqual(captured["status"], "200 OK")
        self.assertIn("name=\"viewport\"", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("Content-Security-Policy", captured["headers"])

    def test_authenticated_profile_returns_only_allowlisted_fields(self):
        class FakeRegistry:
            def get(self, participant_id):
                return {
                    "participant_id": participant_id,
                    "participant_type": "human",
                    "handle": "alice",
                    "display_name": "Alice",
                    "status": "active",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "public_key": "secret-public-key-material",
                    "operator_id": "private-operator",
                    "metadata": {"private": "do-not-return"},
                }
        class FakeAuthenticator:
            def authenticate(self, participant_id, method, path, body,
                             timestamp, nonce, signature):
                if (participant_id, method, path, body, timestamp, nonce, signature) != (
                    "human_1", "GET", "/v1/participants/me", b"",
                    1800000000, "abcdefghijklmnop", "signed",
                ):
                    raise ValueError("invalid")
                return {"participant_id": participant_id}
        app = DirectoryApplication(
            self.catalog, registry=FakeRegistry(),
            authenticator=FakeAuthenticator(),
        )
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
        environ = {
            "REQUEST_METHOD": "GET", "PATH_INFO": "/v1/participants/me",
            "QUERY_STRING": "", "CONTENT_LENGTH": "0",
            "HTTP_X_AAE_PARTICIPANT": "human_1",
            "HTTP_X_AAE_TIMESTAMP": "1800000000",
            "HTTP_X_AAE_NONCE": "abcdefghijklmnop",
            "HTTP_X_AAE_SIGNATURE": "signed",
        }
        body = json.loads(b"".join(app(environ, start_response)))
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(body["participant"]["handle"], "alice")
        self.assertNotIn("public_key", body["participant"])
        self.assertNotIn("metadata", body["participant"])
        self.assertNotIn("operator_id", body["participant"])

    def test_authenticated_profile_rejects_missing_signature_headers(self):
        class FakeRegistry:
            def get(self, _participant_id):
                return None
        class FakeAuthenticator:
            def authenticate(self, *_args):
                raise ValueError("missing signature")
        app = DirectoryApplication(
            self.catalog, registry=FakeRegistry(),
            authenticator=FakeAuthenticator(),
        )
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
        body = json.loads(b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/v1/participants/me",
            "QUERY_STRING": "", "CONTENT_LENGTH": "0",
        }, start_response)))
        self.assertEqual(captured["status"], "401 Unauthorized")
        self.assertEqual(body, {"error": "authentication_failed"})

    def test_rejects_write_methods_and_unknown_routes(self):
        response, body = self.request("/v1/directory/services", method="POST")
        self.assertEqual(response["status"], "405 Method Not Allowed")
        self.assertEqual(body["error"], "method_not_allowed")
        response, body = self.request("/v1/private")
        self.assertEqual(response["status"], "404 Not Found")

    def test_rejects_unbounded_or_ambiguous_query_parameters(self):
        response, body = self.request("/v1/directory/services?limit=1000")
        self.assertEqual(response["status"], "400 Bad Request")
        self.assertEqual(body["error"], "limit_out_of_range")
        response, body = self.request("/v1/directory/services?limit=5&limit=6")
        self.assertEqual(response["status"], "400 Bad Request")
        self.assertEqual(body["error"], "duplicate_query_parameter")
        response, body = self.request("/v1/directory/services?admin=true")
        self.assertEqual(body["error"], "unsupported_query_parameter")

    def test_catalog_failure_does_not_leak_exception(self):
        class BrokenCatalog:
            def discover(self, **_kwargs):
                raise RuntimeError("database password leaked")
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
        output = DirectoryApplication(BrokenCatalog())(
            {"REQUEST_METHOD": "GET", "PATH_INFO": "/v1/directory/services",
             "QUERY_STRING": ""},
            start_response,
        )
        body = json.loads(b"".join(output))
        self.assertEqual(captured["status"], "503 Service Unavailable")
        self.assertEqual(body, {"error": "directory_temporarily_unavailable"})


    def test_authenticated_tasks_are_scoped_to_requesting_participant(self):
        class FakeRegistry:
            def get(self, participant_id):
                return {"participant_id": participant_id, "status": "active"}
        class FakeAuthenticator:
            def authenticate(self, participant_id, method, path, body, timestamp, nonce, signature):
                self.args = (participant_id, method, path, body, timestamp, nonce, signature)
                return {"participant_id": participant_id}
        class FakeTasks:
            def list_for_agent(self, agent_id, *, status=None, limit=50):
                self.args = (agent_id, status, limit)
                return [{
                    "task_id": "task_1", "title": "Research",
                    "assigned_agent": agent_id, "status": "queued",
                    "attempts": 0, "max_attempts": 3,
                    "created_at": "now", "updated_at": "now",
                    "objective": "private objective", "result": "private result",
                    "idempotency_key": "secret",
                }]
        auth, tasks = FakeAuthenticator(), FakeTasks()
        app = DirectoryApplication(self.catalog, registry=FakeRegistry(),
                                   authenticator=auth, task_store=tasks)
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
        environ = {
            "REQUEST_METHOD": "GET", "PATH_INFO": "/v1/tasks/mine",
            "QUERY_STRING": "status=queued&limit=5", "CONTENT_LENGTH": "0",
            "HTTP_X_AAE_PARTICIPANT": "agent_1", "HTTP_X_AAE_TIMESTAMP": "1800000000",
            "HTTP_X_AAE_NONCE": "abcdefghijklmnop", "HTTP_X_AAE_SIGNATURE": "signed",
        }
        body = json.loads(b"".join(app(environ, start_response)))
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(tasks.args, ("agent_1", "queued", 5))
        self.assertEqual(body["items"][0]["task_id"], "task_1")
        self.assertNotIn("objective", body["items"][0])
        self.assertNotIn("result", body["items"][0])
        self.assertNotIn("idempotency_key", body["items"][0])
        self.assertEqual(auth.args[2], "/v1/tasks/mine?status=queued&limit=5")

    def test_authenticated_profile_rejects_unsigned_query_parameters(self):
        class NeverAuthenticate:
            def authenticate(self, *_args):
                raise AssertionError("authentication must not run for unsupported query")
        app = DirectoryApplication(
            self.catalog,
            registry=object(),
            authenticator=NeverAuthenticate(),
        )
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
        output = app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/v1/participants/me",
            "QUERY_STRING": "admin=true",
        }, start_response)
        self.assertEqual(captured["status"], "400 Bad Request")
        self.assertEqual(json.loads(b"".join(output)), {
            "error": "query_parameters_not_supported"
        })

    def test_tasks_endpoint_rejects_invalid_filters_and_missing_auth(self):
        class FakeRegistry:
            def get(self, _participant_id):
                return None
        class FakeAuthenticator:
            def authenticate(self, *_args):
                raise ValueError("missing signature")
        class FakeTasks:
            def list_for_agent(self, *_args, **_kwargs):
                return []
        app = DirectoryApplication(self.catalog, registry=FakeRegistry(),
                                   authenticator=FakeAuthenticator(), task_store=FakeTasks())
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
        for query in ("status=all", "limit=1000", "admin=true"):
            environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/v1/tasks/mine",
                       "QUERY_STRING": query}
            b"".join(app(environ, start_response))
            self.assertEqual(captured["status"], "400 Bad Request")
        environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/v1/tasks/mine",
                   "QUERY_STRING": ""}
        body = json.loads(b"".join(app(environ, start_response)))
        self.assertEqual(captured["status"], "401 Unauthorized")
        self.assertEqual(body, {"error": "authentication_failed"})
    def test_local_owner_overview_returns_aggregates_only(self):
        class FakeRegistry:
            def summary_counts(self):
                return {"human": {"active": 2}, "agent": {"suspended": 1}}
        class FakeTasks:
            def summary_counts(self):
                return {"queued": 3, "completed": 4}
        class FakeOverviewCatalog:
            def summary_counts(self):
                return {"active": 2, "draft": 1}
            def discover(self, **_kwargs):
                return []
        app = DirectoryApplication(FakeOverviewCatalog(), registry=FakeRegistry(),
                                   task_store=FakeTasks())
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
        body = json.loads(b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/v1/local/owner/overview",
            "QUERY_STRING": "", "REMOTE_ADDR": "127.0.0.1",
        }, start_response)))
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(body["participants"]["human"]["active"], 2)
        self.assertEqual(body["tasks"]["queued"], 3)
        self.assertEqual(body["services"]["active"], 2)
        self.assertFalse(body["financial_activity"]["payments_enabled"])
        serialized = json.dumps(body)
        self.assertNotIn("participant_id", serialized)
        self.assertNotIn("private", serialized)

    def test_local_owner_overview_denies_non_loopback_clients(self):
        class FakeRegistry:
            def summary_counts(self):
                raise AssertionError("must not query owner data for remote clients")
        class FakeTasks:
            def summary_counts(self):
                raise AssertionError("must not query owner data for remote clients")
        app = DirectoryApplication(self.catalog, registry=FakeRegistry(),
                                   task_store=FakeTasks())
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
        body = json.loads(b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/v1/local/owner/overview",
            "QUERY_STRING": "", "REMOTE_ADDR": "203.0.113.10",
        }, start_response)))
        self.assertEqual(captured["status"], "403 Forbidden")
        self.assertEqual(body, {"error": "local_access_only"})

    def test_owner_dashboard_is_loopback_only_and_aggregate_only(self):
        class FakeRegistry:
            def summary_counts(self):
                return {"human": {"active": 2}}
        class FakeTasks:
            def summary_counts(self):
                return {"queued": 3}
        class FakeDashboardCatalog:
            def summary_counts(self):
                return {"active": 1}
            def discover(self, **_kwargs):
                return []
        app = DirectoryApplication(FakeDashboardCatalog(), registry=FakeRegistry(),
                                   task_store=FakeTasks())
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)
        page = b"".join(app({
            "REQUEST_METHOD": "GET", "PATH_INFO": "/owner",
            "QUERY_STRING": "", "REMOTE_ADDR": "::1",
        }, start_response)).decode("utf-8")
        self.assertEqual(captured["status"], "200 OK")
        self.assertIn("Economy overview", page)
        self.assertIn('&quot;payments_enabled&quot;: false', page)
        self.assertIn("Aggregate operational counts only", page)
        self.assertNotIn("participant_id", page)
        self.assertIn("Content-Security-Policy", captured["headers"])

    def test_owner_dashboard_rejects_remote_and_missing_client_address(self):
        class FakeRegistry:
            def summary_counts(self):
                raise AssertionError("must reject before querying")
        class FakeTasks:
            def summary_counts(self):
                raise AssertionError("must reject before querying")
        app = DirectoryApplication(self.catalog, registry=FakeRegistry(),
                                   task_store=FakeTasks())
        for remote in ("203.0.113.8", ""):
            captured = {}
            def start_response(status, headers):
                captured["status"] = status
            page = b"".join(app({
                "REQUEST_METHOD": "GET", "PATH_INFO": "/owner",
                "QUERY_STRING": "", "REMOTE_ADDR": remote,
            }, start_response)).decode("utf-8")
            self.assertEqual(captured["status"], "403 Forbidden")
            self.assertIn("Local access only", page)

if __name__ == "__main__":
    unittest.main()
