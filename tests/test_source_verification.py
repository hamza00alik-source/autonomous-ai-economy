import unittest
from unittest.mock import MagicMock, call, patch

from economy.source_verification import (
    OriginalSourceFetcher,
    RetrievedSource,
    _PinnedHTTPSConnection,
    _TextExtractor,
    _resolve_public_addresses,
)


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"<html><script>secret()</script><h1>Buyer problem</h1><p>People need a better invoice workflow.</p></html>"):
        self.status = status
        self.headers = headers or {"Content-Type": "text/html; charset=utf-8"}
        self.body = body

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, amount=-1):
        if amount == 0:
            return b""
        return self.body[:amount]


class FakeConnection:
    instances = []
    responses = []

    def __init__(self, hostname, pinned_ip, timeout):
        self.hostname = hostname
        self.pinned_ip = pinned_ip
        self.timeout = timeout
        self.request_args = None
        self.closed = False
        self.__class__.instances.append(self)

    def request(self, method, target, headers):
        self.request_args = (method, target, headers)

    def getresponse(self):
        return self.__class__.responses.pop(0)

    def close(self):
        self.closed = True


class SourceVerificationTests(unittest.TestCase):
    def setUp(self):
        FakeConnection.instances = []
        FakeConnection.responses = []

    @patch("economy.source_verification.socket.getaddrinfo")
    def test_rejects_private_or_local_dns_resolution(self, dns):
        dns.return_value = [(None, None, None, None, ("127.0.0.1", 443))]
        with self.assertRaises(ValueError):
            _resolve_public_addresses("publisher.example")

    @patch("economy.source_verification.socket.getaddrinfo")
    def test_rejects_mixed_public_and_private_dns_answers(self, dns):
        dns.return_value = [
            (None, None, None, None, ("93.184.216.34", 443)),
            (None, None, None, None, ("10.0.0.8", 443)),
        ]
        with self.assertRaises(ValueError):
            _resolve_public_addresses("publisher.example")

    def test_rejects_non_https_credentials_unlisted_hosts_and_nonstandard_ports(self):
        for url, allowed in [
            ("http://publisher.example/story", ["publisher.example"]),
            ("https://user:pass@publisher.example/story", ["publisher.example"]),
            ("https://publisher.example:8443/story", ["publisher.example"]),
            ("https://other.example/story", ["publisher.example"]),
            ("https://publisher.example.evil.test/story", ["publisher.example"]),
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                OriginalSourceFetcher().fetch(url, allowed_hosts=allowed)

    def test_html_extraction_skips_nested_active_content_and_formats_lines(self):
        parser = _TextExtractor()
        parser.feed("<h1>Useful heading</h1><script>outer<script>inner</script>hidden</script><p>Useful detail</p>")
        extracted = parser.text()
        self.assertIn("Useful heading", extracted)
        self.assertIn("Useful detail", extracted)
        self.assertNotIn("outer", extracted)
        self.assertIn("\n", extracted)

    @patch("economy.source_verification._PinnedHTTPSConnection", FakeConnection)
    @patch("economy.source_verification._resolve_public_addresses", return_value=["93.184.216.34"])
    def test_returns_hash_and_unverified_content_without_evidence_promotion(self, _resolve):
        FakeConnection.responses = [FakeResponse()]
        result = OriginalSourceFetcher().fetch(
            "https://publisher.example/story",
            allowed_hosts=["publisher.example"],
        )
        self.assertIsInstance(result, RetrievedSource)
        self.assertEqual(result.hostname, "publisher.example")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(result.content_sha256), 64)
        self.assertIn("invoice workflow", result.extracted_text)
        self.assertNotIn("secret()", result.extracted_text)
        self.assertEqual(result.verification_status, "retrieved_unverified")
        self.assertFalse(result.buyer_evidence_created)
        connection = FakeConnection.instances[0]
        self.assertEqual(connection.pinned_ip, "93.184.216.34")
        self.assertEqual(connection.request_args[0:2], ("GET", "/story"))
        self.assertTrue(connection.closed)

    @patch("economy.source_verification._PinnedHTTPSConnection", FakeConnection)
    @patch("economy.source_verification._resolve_public_addresses", return_value=["93.184.216.34"])
    def test_redirect_is_revalidated_and_reconnected_with_a_fresh_pin(self, _resolve):
        FakeConnection.responses = [
            FakeResponse(302, {"Location": "/new-path"}),
            FakeResponse(200),
        ]
        result = OriginalSourceFetcher().fetch(
            "https://publisher.example/story",
            allowed_hosts=["publisher.example"],
        )
        self.assertEqual(result.final_url, "https://publisher.example/new-path")
        self.assertEqual(len(FakeConnection.instances), 2)
        self.assertTrue(FakeConnection.instances[0].closed)
        self.assertEqual(FakeConnection.instances[1].request_args[1], "/new-path")

    @patch("economy.source_verification._PinnedHTTPSConnection", FakeConnection)
    @patch("economy.source_verification._resolve_public_addresses", return_value=["93.184.216.34"])
    def test_cross_host_redirect_is_rejected_before_second_connection(self, _resolve):
        FakeConnection.responses = [
            FakeResponse(302, {"Location": "https://attacker.example/"}),
        ]
        with self.assertRaises(ValueError):
            OriginalSourceFetcher().fetch(
                "https://publisher.example/story",
                allowed_hosts=["publisher.example", "attacker.example"],
            )
        self.assertEqual(len(FakeConnection.instances), 1)
        self.assertTrue(FakeConnection.instances[0].closed)

    @patch("economy.source_verification.socket.create_connection")
    def test_tcp_socket_dials_pinned_ip_and_tls_uses_original_hostname(self, create_connection):
        raw_socket = MagicMock()
        tls_socket = MagicMock()
        context = MagicMock()
        context.wrap_socket.return_value = tls_socket
        create_connection.return_value = raw_socket
        with patch("economy.source_verification.ssl.create_default_context", return_value=context):
            connection = _PinnedHTTPSConnection("publisher.example", "93.184.216.34", 7)
        connection.connect()
        create_connection.assert_called_once_with(("93.184.216.34", 443), 7)
        context.wrap_socket.assert_called_once_with(raw_socket, server_hostname="publisher.example")
        self.assertIs(connection.sock, tls_socket)

    @patch("economy.source_verification._PinnedHTTPSConnection", FakeConnection)
    @patch("economy.source_verification._resolve_public_addresses", return_value=["93.184.216.34"])
    def test_oversized_body_is_rejected(self, _resolve):
        from economy.source_verification import MAX_SOURCE_BYTES
        FakeConnection.responses = [
            FakeResponse(200, {"Content-Type": "text/plain"}, b"x" * (MAX_SOURCE_BYTES + 1)),
        ]
        with self.assertRaises(ValueError):
            OriginalSourceFetcher().fetch(
                "https://publisher.example/story",
                allowed_hosts=["publisher.example"],
            )
        self.assertTrue(FakeConnection.instances[0].closed)



class PinnedConnectionIntegrationTests(unittest.TestCase):
    """Exercise the real TLS and TCP stack while simulating a changed DNS answer."""

    @classmethod
    def setUpClass(cls):
        import ssl
        import subprocess
        import tempfile
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        cls._tempdir = tempfile.TemporaryDirectory()
        cls.cert_path = cls._tempdir.name + "/server.pem"
        cls.key_path = cls._tempdir.name + "/server-key.pem"
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", cls.key_path, "-out", cls.cert_path, "-days", "1",
            "-subj", "/CN=publisher.example",
            "-addext", "subjectAltName=DNS:publisher.example",
        ], check=True, capture_output=True)
        cls.server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.server_context.load_cert_chain(cls.cert_path, cls.key_path)
        cls.client_context = ssl.create_default_context(cafile=cls.cert_path)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"<html><h1>Connection-level source</h1><p>Evidence from the live TLS test server.</p></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.socket = cls.server_context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls._tempdir.cleanup()

    def _run_fetch_with_pinned_local_endpoint(self, hostname):
        import socket
        from unittest.mock import patch

        original_create_connection = socket.create_connection
        original_getaddrinfo = socket.getaddrinfo
        resolved_names = []

        def simulate_dns_rebinding(host, port, *args, **kwargs):
            resolved_names.append(str(host))
            # If the fetcher resolves the hostname again after preflight, simulate
            # an attacker changing DNS to a different loopback address.
            if host == hostname:
                return original_getaddrinfo("127.0.0.2", port, *args, **kwargs)
            return original_getaddrinfo(host, port, *args, **kwargs)

        dialed = []

        def connect_to_test_listener(address, timeout=None, source_address=None, **kwargs):
            dialed.append(address)
            if address != ("127.0.0.1", 443):
                raise AssertionError("connection did not use the prevalidated pinned IP")
            return original_create_connection(
                ("127.0.0.1", self.server.server_port),
                timeout=timeout,
                source_address=source_address,
                **kwargs,
            )

        with patch("economy.source_verification._resolve_public_addresses", return_value=["127.0.0.1"]), \
             patch("economy.source_verification.socket.getaddrinfo", side_effect=simulate_dns_rebinding), \
             patch("economy.source_verification.socket.create_connection", side_effect=connect_to_test_listener), \
             patch("economy.source_verification.ssl.create_default_context", return_value=self.client_context):
            result = OriginalSourceFetcher().fetch(
                "https://" + hostname + "/source",
                allowed_hosts=["publisher.example", "other.example"],
            )
        return result, resolved_names, dialed

    def test_live_tls_request_uses_pinned_ip_not_rebound_hostname(self):
        result, resolved_names, dialed = self._run_fetch_with_pinned_local_endpoint("publisher.example")
        self.assertEqual(result.status_code, 200)
        self.assertIn("live TLS test server", result.extracted_text)
        self.assertEqual(dialed, [("127.0.0.1", 443)])
        self.assertNotIn("publisher.example", resolved_names)

    def test_live_tls_certificate_hostname_mismatch_is_rejected(self):
        import socket
        from unittest.mock import patch

        original_create_connection = socket.create_connection

        def connect_to_test_listener(address, timeout=None, source_address=None, **kwargs):
            self.assertEqual(address, ("127.0.0.1", 443))
            return original_create_connection(
                ("127.0.0.1", self.server.server_port),
                timeout=timeout,
                source_address=source_address,
                **kwargs,
            )

        with patch("economy.source_verification._resolve_public_addresses", return_value=["127.0.0.1"]), \
             patch("economy.source_verification.socket.create_connection", side_effect=connect_to_test_listener), \
             patch("economy.source_verification.ssl.create_default_context", return_value=self.client_context):
            with self.assertRaises(OSError):
                OriginalSourceFetcher().fetch(
                    "https://other.example/source",
                    allowed_hosts=["other.example"],
                )


if __name__ == "__main__":
    unittest.main()
