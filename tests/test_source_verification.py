import unittest
from unittest.mock import patch

from economy.source_verification import (
    OriginalSourceFetcher,
    RetrievedSource,
    _TextExtractor,
    _validate_url,
)


class FakeHeaders(dict):
    pass


class FakeResponse:
    status = 200
    headers = FakeHeaders({"Content-Type": "text/html; charset=utf-8"})

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def geturl(self):
        return "https://publisher.example/story"

    def read(self, size):
        return b"<html><script>secret()</script><h1>Buyer problem</h1><p>People need a better invoice workflow.</p></html>"


class FakeOpener:
    def open(self, request, timeout):
        self.request = request
        self.timeout = timeout
        return FakeResponse()


class SourceVerificationTests(unittest.TestCase):
    @patch("economy.source_verification.socket.getaddrinfo")
    def test_rejects_private_or_local_resolution(self, dns):
        dns.return_value = [(None, None, None, None, ("127.0.0.1", 443))]
        with self.assertRaises(ValueError):
            _validate_url("https://publisher.example/story", {"publisher.example"})

    def test_rejects_non_https_credentials_unlisted_hosts_and_nonstandard_ports(self):
        for url, allowed in [
            ("http://publisher.example/story", {"publisher.example"}),
            ("https://user:pass@publisher.example/story", {"publisher.example"}),
            ("https://publisher.example:8443/story", {"publisher.example"}),
            ("https://other.example/story", {"publisher.example"}),
        ]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                OriginalSourceFetcher().fetch(url, allowed_hosts=list(allowed))

    def test_html_extraction_skips_scripts_and_caps_output(self):
        parser = _TextExtractor()
        parser.feed("<h1>Useful heading</h1><script>do not include</script><p>Useful detail</p>")
        extracted = parser.text()
        self.assertIn("Useful heading", extracted)
        self.assertIn("Useful detail", extracted)
        self.assertNotIn("do not include", extracted)

    @patch("economy.source_verification.socket.getaddrinfo")
    @patch("economy.source_verification.build_opener")
    def test_returns_hash_and_unverified_content_without_evidence_promotion(self, build_opener, dns):
        dns.return_value = [(None, None, None, None, ("93.184.216.34", 443))]
        opener = FakeOpener()
        build_opener.return_value = opener
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
        self.assertEqual(opener.timeout, 12)


if __name__ == "__main__":
    unittest.main()
