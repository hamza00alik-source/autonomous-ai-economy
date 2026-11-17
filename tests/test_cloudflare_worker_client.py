from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from economy.cloudflare_worker_client import (
    CloudflareWorkerError, submit_and_wait,
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


def _facts(tmp_path):
    path = tmp_path / "facts.json"
    path.write_text(json.dumps({
        "product_name": "MOBA Objective Props",
        "buyer_segment": "Indie game developers",
        "product_summary": "Five original low-poly fantasy props.",
        "included_files": ["five GLB models"],
        "formats": ["GLB", "Godot 4"],
        "known_limits": ["static props only", "no animation"],
        "ai_disclosure": "AI-assisted procedural mesh generation.",
    }))
    return path


def test_client_queues_polls_and_saves_unpublished_draft(tmp_path):
    facts = _facts(tmp_path)
    calls = []
    responses = iter([
        {"task_id": "12345678-1234-1234-1234-123456789012", "status": "queued"},
        {"task_id": "12345678-1234-1234-1234-123456789012", "status": "running"},
        {"task_id": "12345678-1234-1234-1234-123456789012", "status": "completed", "result": {
            "title": "MOBA Objective Props - Five Low-Poly GLB Models",
            "short_description": "Five low-poly props in GLB format for Godot 4.",
            "description": "A factual description of the five low-poly props in GLB format and Godot 4.",
            "tags": ["low-poly", "GLB models", "Godot assets"],
            "ai_disclosure": "AI-assisted procedural mesh generation.",
            "claims_to_verify": [],
            "status": "draft",
            "published": False,
        }},
    ])

    def opener(request, timeout):
        calls.append((request.full_url, request.get_method(), request.get_header("Authorization")))
        return FakeResponse(next(responses))

    sleeps = []
    output = tmp_path / "out" / "listing.json"
    result = submit_and_wait(
        facts_path=facts, output_path=output, worker_url="https://aae.example.workers.dev",
        token="secret", timeout_seconds=120, poll_interval=5, opener=opener,
        sleep=sleeps.append, monotonic=iter([0, 1, 2, 3]).__next__,
    )
    assert result["status"] == "completed"
    assert result["published"] is False
    assert len(calls) == 3
    assert all(call[2] == "Bearer secret" for call in calls)
    assert sleeps == [5, 5]
    assert json.loads(output.read_text())["published"] is False


def test_client_rejects_invalid_origin_and_missing_token_before_network(tmp_path):
    facts = _facts(tmp_path)
    calls = []
    with pytest.raises(ValueError, match="HTTPS"):
        submit_and_wait(facts_path=facts, output_path=tmp_path / "x.json",
                        worker_url="http://bad.example", token="secret",
                        opener=lambda *a, **k: calls.append(1))
    with pytest.raises(ValueError, match="AAE_QUEUE_TOKEN"):
        submit_and_wait(facts_path=facts, output_path=tmp_path / "x.json",
                        worker_url="https://good.example", token="",
                        opener=lambda *a, **k: calls.append(1))
    assert calls == []


def test_client_fails_closed_on_budget_block_and_never_writes_output(tmp_path):
    facts = _facts(tmp_path)
    responses = iter([
        {"task_id": "12345678-1234-1234-1234-123456789012", "status": "queued"},
        {"task_id": "12345678-1234-1234-1234-123456789012", "status": "blocked_budget", "error": "quota reached"},
    ])
    def opener(request, timeout):
        return FakeResponse(next(responses))
    output = tmp_path / "draft.json"
    with pytest.raises(CloudflareWorkerError, match="blocked_budget"):
        submit_and_wait(facts_path=facts, output_path=output,
                        worker_url="https://aae.example.workers.dev", token="secret",
                        timeout_seconds=120, poll_interval=5, opener=opener,
                        sleep=lambda _: None, monotonic=iter([0, 1]).__next__)
    assert not output.exists()


def test_client_rejects_published_model_result(tmp_path):
    facts = _facts(tmp_path)
    responses = iter([
        {"task_id": "12345678-1234-1234-1234-123456789012", "status": "queued"},
        {"task_id": "12345678-1234-1234-1234-123456789012", "status": "completed", "result": {
            "title": "x", "short_description": "x", "description": "x",
            "tags": [], "ai_disclosure": "x", "status": "published", "published": True,
        }},
    ])
    def opener(request, timeout):
        return FakeResponse(next(responses))
    with pytest.raises(CloudflareWorkerError, match="unpublished draft"):
        submit_and_wait(facts_path=facts, output_path=tmp_path / "draft.json",
                        worker_url="https://aae.example.workers.dev", token="secret",
                        timeout_seconds=120, poll_interval=5, opener=opener,
                        sleep=lambda _: None, monotonic=iter([0, 1]).__next__)
