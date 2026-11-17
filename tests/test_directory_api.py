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


if __name__ == "__main__":
    unittest.main()
