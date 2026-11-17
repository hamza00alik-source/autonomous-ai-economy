import io
import json
import unittest

from economy.directory_api import DirectoryApplication


class FakeCatalog:
    def discover(self, **_kwargs):
        return []


class FakeAuthenticator:
    def __init__(self):
        self.calls = []

    def authenticate(self, participant_id, method, path, body, timestamp, nonce, signature):
        self.calls.append((participant_id, method, path, body, timestamp, nonce, signature))
        if signature != "valid":
            raise ValueError("bad signature")
        return {"participant_id": participant_id}


class FakeAgreements:
    def __init__(self):
        self.created = None
        self.responded = None

    def create_offer(self, **kwargs):
        self.created = kwargs
        return {
            "task_id": kwargs["task_id"], "listing_id": kwargs["listing_id"],
            "buyer_id": kwargs["buyer_id"], "provider_id": kwargs["provider_id"],
            "status": "offered", "created_at": "2026-11-17T00:00:00+00:00",
        }

    def respond(self, task_id, **kwargs):
        self.responded = (task_id, kwargs)
        return {"task_id": task_id, "status": "accepted",
                "provider_id": kwargs["provider_id"]}

    def offers_for_provider(self, provider_id, *, status="offered", limit=50):
        return [{
            "task_id": "task_a", "listing_id": "listing_a",
            "buyer_id": "buyer_1", "provider_id": provider_id,
            "title": "Research", "scope": "Scope",
            "acceptance_criteria": "Criteria", "due_at": None,
            "price_minor": 500, "currency": "USD",
            "status": status, "created_at": "2026-11-17T00:00:00+00:00",
            "private_signature": "never return",
        }][:limit]

    def get(self, task_id):
        return {
            "task_id": task_id, "listing_id": "listing_a",
            "buyer_id": "buyer_1", "provider_id": "provider_1",
            "title": "Research", "scope": "Scope",
            "acceptance_criteria": "Criteria", "due_at": None,
            "price_minor": 500, "currency": "USD",
            "status": "offered", "created_at": "2026-11-17T00:00:00+00:00",
            "updated_at": "2026-11-17T00:00:00+00:00",
            "buyer_signature": "private",
        }


class SignedTaskOfferApiTests(unittest.TestCase):
    def setUp(self):
        self.auth = FakeAuthenticator()
        self.agreements = FakeAgreements()
        self.app = DirectoryApplication(FakeCatalog(), authenticator=self.auth,
                                         agreements=self.agreements)

    def request(self, method, path, payload, participant="buyer_1", signature="valid"):
        raw = payload if isinstance(payload, bytes) else json.dumps(
            payload, separators=(",", ":")
        ).encode()
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)
        output = self.app({
            "REQUEST_METHOD": method, "PATH_INFO": path,
            "QUERY_STRING": "", "CONTENT_LENGTH": str(len(raw)),
            "wsgi.input": io.BytesIO(raw),
            "HTTP_X_AAE_PARTICIPANT": participant,
            "HTTP_X_AAE_TIMESTAMP": "1799999999",
            "HTTP_X_AAE_NONCE": "abcdefghijklmnop",
            "HTTP_X_AAE_SIGNATURE": signature,
        }, start_response)
        return captured, json.loads(b"".join(output))

    def test_buyer_offer_uses_authenticated_identity_not_body_identity(self):
        response, body = self.request("POST", "/v1/tasks/offers", {
            "task_id": "task_a", "listing_id": "listing_a",
            "provider_id": "provider_1", "title": "Research",
            "scope": "Prepare a market report",
            "acceptance_criteria": "Report includes sources",
            "offer_signature": "buyer_offer_sig",
        })
        self.assertEqual(response["status"], "201 Created")
        self.assertEqual(self.agreements.created["buyer_id"], "buyer_1")
        self.assertEqual(self.auth.calls[0][2], "/v1/tasks/offers")
        self.assertEqual(body["task"]["status"], "offered")
        self.assertIn("no payment", body["notice"])

    def test_task_offer_quota_rejects_before_creating_offer(self):
        from economy.identity import ParticipantRateLimitExceeded

        class LimitedRegistry:
            def consume_operation_quota(self, participant_id, operation, **kwargs):
                self.args = (participant_id, operation, kwargs)
                raise ParticipantRateLimitExceeded(operation)

        self.app.registry = LimitedRegistry()
        response, body = self.request("POST", "/v1/tasks/offers", {
            "task_id": "task_a", "listing_id": "listing_a",
            "provider_id": "provider_1", "title": "Research",
            "scope": "Prepare a market report",
            "acceptance_criteria": "Report includes sources",
            "offer_signature": "buyer_offer_sig",
        })
        self.assertEqual(response["status"], "429 Too Many Requests")
        self.assertEqual(response["headers"]["Retry-After"], "3600")
        self.assertEqual(body["error"], "participant_operation_rate_limited")
        self.assertIsNone(self.agreements.created)

    def test_provider_response_is_scoped_to_authenticated_provider(self):
        response, body = self.request(
            "POST", "/v1/tasks/task_a/responses",
            {"decision": "accept", "response_signature": "provider_sig"},
            participant="provider_1",
        )
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(self.agreements.responded,
                         ("task_a", {"provider_id": "provider_1",
                                     "decision": "accept",
                                     "signature": "provider_sig"}))
        self.assertEqual(self.auth.calls[0][2], "/v1/tasks/task_a/responses")
        self.assertEqual(body["task"]["status"], "accepted")

    def test_rejects_extra_fields_and_duplicate_json_keys(self):
        response, body = self.request("POST", "/v1/tasks/offers", {
            "task_id": "task_a", "listing_id": "listing_a",
            "provider_id": "provider_1", "title": "Research",
            "scope": "Scope", "acceptance_criteria": "Criteria",
            "offer_signature": "sig", "buyer_id": "victim",
        })
        self.assertEqual(response["status"], "400 Bad Request")
        self.assertEqual(body["error"], "invalid_offer_fields")
        raw = b'{"decision":"accept","decision":"decline","response_signature":"sig"}'
        response, body = self.request("POST", "/v1/tasks/task_a/responses", raw)
        self.assertEqual(response["status"], "400 Bad Request")
        self.assertEqual(body["error"], "invalid_json_body")

    def get_request(self, path, participant="provider_1"):
        captured = {}
        def start_response(status, headers):
            captured["status"] = status
        route, _, query = path.partition("?")
        output = self.app({
            "REQUEST_METHOD": "GET", "PATH_INFO": route,
            "QUERY_STRING": query, "CONTENT_LENGTH": "0",
            "HTTP_X_AAE_PARTICIPANT": participant,
            "HTTP_X_AAE_TIMESTAMP": "1799999999",
            "HTTP_X_AAE_NONCE": "qrstuvwxyzABCDEF",
            "HTTP_X_AAE_SIGNATURE": "valid",
        }, start_response)
        return captured, json.loads(b"".join(output))

    def test_provider_inbox_is_scoped_and_query_is_signed(self):
        response, body = self.get_request("/v1/tasks/offers/inbox?status=offered&limit=5")
        self.assertEqual(response["status"], "200 OK")
        self.assertEqual(body["items"][0]["provider_id"], "provider_1")
        self.assertNotIn("private_signature", body["items"][0])
        self.assertEqual(self.auth.calls[-1][2],
                         "/v1/tasks/offers/inbox?status=offered&limit=5")

    def test_agreement_detail_is_private_to_buyer_and_provider(self):
        response, body = self.get_request("/v1/tasks/task_a", participant="buyer_1")
        self.assertEqual(response["status"], "200 OK")
        self.assertNotIn("buyer_signature", body["task"])
        response, body = self.get_request("/v1/tasks/task_a", participant="stranger")
        self.assertEqual(response["status"], "404 Not Found")
        self.assertEqual(body["error"], "not_found")

    def test_rejects_invalid_offer_types_and_boolean_amount(self):
        payload = {
            "task_id": "task_a", "listing_id": "listing_a",
            "provider_id": "provider_1", "title": "Research",
            "scope": "Scope", "acceptance_criteria": "Criteria",
            "offer_signature": "sig", "price_minor": True, "currency": "USD",
        }
        response, body = self.request("POST", "/v1/tasks/offers", payload)
        self.assertEqual(response["status"], "400 Bad Request")
        self.assertEqual(body["error"], "invalid_offer_fields")
        payload["price_minor"] = 100
        payload["title"] = ["not", "a", "string"]
        response, body = self.request("POST", "/v1/tasks/offers", payload)
        self.assertEqual(response["status"], "400 Bad Request")
        self.assertEqual(body["error"], "invalid_offer_fields")

    def test_rejects_invalid_request_signature(self):
        response, body = self.request(
            "POST", "/v1/tasks/task_a/responses",
            {"decision": "accept", "response_signature": "sig"},
            signature="invalid",
        )
        self.assertEqual(response["status"], "401 Unauthorized")
        self.assertEqual(body["error"], "authentication_failed")


if __name__ == "__main__":
    unittest.main()
