from __future__ import annotations

import json
import urllib.error

import pytest

from economy.ai_runtime import (
    AIConfigurationError, AIBudgetExceeded, AIProviderError,
    CloudflareWorkersAI, InferenceBudget, MODEL_ID, estimate_neurons,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return self.payload[:limit]


def test_estimator_rejects_oversized_prompts_and_outputs():
    with pytest.raises(ValueError):
        estimate_neurons([{"role": "user", "content": "x" * 8001}], 100)
    with pytest.raises(ValueError):
        estimate_neurons([{"role": "user", "content": "hello"}], 513)


def test_missing_credentials_fail_before_budget_or_network(tmp_path):
    calls = []
    budget = InferenceBudget(tmp_path / "budget.sqlite3")
    provider = CloudflareWorkersAI(budget, account_id="", api_token="", opener=lambda *a, **k: calls.append(1))
    with pytest.raises(AIConfigurationError):
        provider.generate("hello")
    assert calls == []
    assert budget.status()["requests_reserved"] == 0


def test_successful_call_uses_allowlisted_model_and_never_persists_prompt(tmp_path):
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse({"success": True, "result": {"response": "A concise result."}})

    budget = InferenceBudget(tmp_path / "budget.sqlite3")
    provider = CloudflareWorkersAI(
        budget, account_id="a" * 32, api_token="secret-test-token", opener=opener
    )
    result = provider.generate("private prompt")
    assert result.text == "A concise result."
    assert result.model == MODEL_ID
    assert captured["url"].endswith("/" + MODEL_ID)
    assert captured["headers"]["Authorization"] == "Bearer secret-test-token"
    assert captured["payload"]["max_tokens"] == 512
    assert budget.status()["requests_reserved"] == 1
    with budget._connect() as db:
        row = db.execute("SELECT prompt_sha256, status FROM ai_inference_reservations").fetchone()
    assert row[1] == "succeeded"
    assert "private prompt" not in str(row)


def test_budget_guard_prevents_network_call(tmp_path):
    calls = []
    budget = InferenceBudget(tmp_path / "budget.sqlite3", daily_limit=1)
    provider = CloudflareWorkersAI(
        budget, account_id="b" * 32, api_token="token",
        opener=lambda *a, **k: calls.append(1),
    )
    with pytest.raises(AIBudgetExceeded):
        provider.generate("this request cannot fit", max_tokens=512)
    assert calls == []
    assert budget.status()["requests_reserved"] == 0


def test_provider_failure_keeps_conservative_reservation(tmp_path):
    budget = InferenceBudget(tmp_path / "budget.sqlite3")

    def opener(*args, **kwargs):
        raise urllib.error.HTTPError(
            "https://api.cloudflare.com", 401, "Unauthorized", {},
            __import__("io").BytesIO(b'{"success":false,"errors":[{"message":"bad token"}]}'),
        )

    provider = CloudflareWorkersAI(
        budget, account_id="c" * 32, api_token="secret", opener=opener
    )
    with pytest.raises(AIProviderError, match="HTTP 401"):
        provider.generate("test")
    assert budget.status()["requests_reserved"] == 1
    with budget._connect() as db:
        assert db.execute("SELECT status FROM ai_inference_reservations").fetchone()[0] == "failed"


def test_daily_budget_reservations_are_atomic_and_bounded(tmp_path):
    budget = InferenceBudget(tmp_path / "budget.sqlite3", daily_limit=100)
    first, used = budget.reserve(model=MODEL_ID, prompt="one", estimated_neurons=60)
    assert used == 60
    with pytest.raises(AIBudgetExceeded):
        budget.reserve(model=MODEL_ID, prompt="two", estimated_neurons=41)
    budget.finish(first, "failed")
    assert budget.status()["reserved_neurons"] == 60

from economy.ai_runtime import runtime_status


def test_status_reports_unconfigured_without_network_or_secret_leak(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    status = runtime_status(tmp_path)
    assert status["configured"] is False
    assert status["network_calls_made"] is False
    assert status["credentials_values_displayed"] is False
    assert status["daily_budget"]["daily_safety_budget_neurons"] == 6500
